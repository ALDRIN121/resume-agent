"""
Resume Agent CLI — typer app with Rich live UI.

Commands:
  (none)     Interactive session — wizard on first run, then generate loop
  setup      Run the provider-setup wizard explicitly
  init       Parse your existing resume (.tex or .pdf) into base YAML
  generate   Generate a tailored resume for a job (text or URL input)
  resume     Resume an interrupted HITL session by thread ID
  config     View / update configuration
  doctor     Check that all external tools are available
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import uuid
import warnings
import webbrowser
from pathlib import Path

# Silence LangGraph's noisy "Deserializing unregistered type" messages.
# These fire every time a checkpoint is loaded and are not actionable.
warnings.filterwarnings("ignore", message=".*Deserializing unregistered type.*")
for _lg in ("langgraph", "langgraph.checkpoint", "langgraph.checkpoint.serde",
            "langgraph.checkpoint.serde.msgpack"):
    logging.getLogger(_lg).setLevel(logging.ERROR)

import typer
import yaml
from langgraph.types import Command
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .config import (
    BASE_RESUME_FILE,
    CONFIG_FILE,
    SOURCE_DIR,
    ResumeAgentSettings,
)
from .graph import HITL_MISSING_NODE, HITL_SUGGESTIONS_NODE
from .ui.banner import print_banner
from .ui.console import console, err_console
from .ui.panels import (
    print_error,
    print_error_panel,
    print_info,
    print_section,
    print_success,
    print_warning,
)
from .ui.prompts import confirm, prompt_hitl_questions, prompt_suggestions

app = typer.Typer(
    name="resume-generator",
    help="AI-powered multi-agent resume generator.",
    add_completion=False,
    rich_markup_mode="rich",
    no_args_is_help=False,      # bare `resume-generator` → interactive mode
    invoke_without_command=True,
)


# ══════════════════════════════════════════════════════════════════════════════
#  Default callback — interactive mode
# ══════════════════════════════════════════════════════════════════════════════

@app.callback(invoke_without_command=True)
def _entrypoint(ctx: typer.Context) -> None:
    """Resume Generator — type resume-generator with no command for an interactive session."""
    if ctx.invoked_subcommand is None:
        run_interactive()


def run_interactive() -> None:
    """
    Interactive session: triggered by `resume-generator` alone.

    Flow:
      1. Show banner.
      2. Run setup wizard only if not yet configured (first-time or missing key).
      3. Run init if no base resume exists yet.
      4. Loop: ask for JD → generate → ask to continue.
    """

    if not sys.stdin.isatty():
        print_error('Use init --source or generate with explicit job input; human review requires an interactive terminal.')
        raise typer.Exit(2)

    settings = _load_settings_gracefully()
    print_banner(provider=settings.provider, model=settings.model.default)

    # ── Non-blocking update check ─────────────────────────────────────────────
    try:
        from .updater import check_for_update
        _upd = check_for_update()
        if _upd:
            print_warning(_upd)
    except Exception:
        pass

    # ── Ensure LLM is configured and reachable ────────────────────────────────

    # ── Base resume (only if missing) ─────────────────────────────────────────
    if not BASE_RESUME_FILE.exists():
        print_section("Set Up Your Resume")
        console.print(
            Panel(
                "[bold]No base resume found.[/bold]\n\n"
                "Before generating tailored resumes, the tool needs to read\n"
                "your existing resume once and save it as a starting point.\n\n"
                "Drop your PDF or [bold].tex[/bold] file into the [bold]source/[/bold] folder shown below,\n"
                "or enter the full path when prompted.",
                border_style="yellow",
                padding=(0, 2),
            )
        )
        _interactive_init_resume(settings)
        if not BASE_RESUME_FILE.exists():
            print_error("Cannot generate without a base resume. Run: resume-generator init")
            raise typer.Exit(1)
        print_success("Resume ready! Now let's tailor it for a job.")

    # ── Pre-flight: check tools before first generation ───────────────────────
    _preflight_checks(settings)

    # ── Generation loop ────────────────────────────────────────────────────────
    while True:
        _interactive_generate(settings)
        console.print()
        if not confirm("Generate another resume?", default=False):
            break

    console.print("[muted]Goodbye![/muted]\n")


def _interactive_init_resume(settings: ResumeAgentSettings) -> None:
    """Import into the same explicitly reviewed durable draft as the API."""
    source = _prompt_for_resume_file()
    if source is not None:
        _import_v2_source(source, settings)



def _prompt_for_resume_file() -> Path | None:
    """
    Interactive loop: keep prompting until the user provides a valid .pdf/.tex file.
    Returns the resolved Path, or None if the user types 'q' to abort.
    """
    from rich.markup import escape as _esc

    _VALID_EXTS = {".pdf", ".tex"}  # noqa: N806
    # All quote variants a user might wrap a path in (regular + curly + backtick)
    _QUOTES = '"\'`\u2018\u2019\u201c\u201d'  # noqa: N806

    while True:
        # Re-check source folder on each iteration (user may have just dropped a file in)
        candidates = sorted(SOURCE_DIR.glob("*.pdf")) + sorted(SOURCE_DIR.glob("*.tex"))
        if candidates:
            source = candidates[0]
            print_success(f"Found in source/: {source.name}")
            return source

        raw = Prompt.ask(
            "  [accent]Resume path[/accent] "
            "[muted](.pdf or .tex — or press Enter to re-check source/, q to quit)[/muted]",
            console=console,
            default="",
        )

        # Strip whitespace then all quote variants from both ends
        raw = raw.strip().strip(_QUOTES).strip()

        if raw.lower() in ("q", "quit", "exit"):
            print_warning("Aborted.")
            return None

        if not raw:
            # Re-check source folder silently on next loop iteration
            continue

        path = Path(raw).expanduser().resolve()

        if not path.exists():
            # Escape path for Rich so special chars don't corrupt the output
            console.print(f"[error]✗[/error] File not found: {_esc(str(path))}")
            console.print(f"  [muted]→ Check the path and try again, or drop the file into {_esc(str(SOURCE_DIR))}/[/muted]")
            continue

        if path.suffix.lower() not in _VALID_EXTS:
            console.print(f"[error]✗[/error] Unsupported format [bold]{_esc(path.suffix)}[/bold] — only .pdf and .tex are accepted.")
            continue

        return path


def _read_jd_input() -> str:
    """
    Read a job description from stdin without reprinting a label per line.

    On macOS/Linux we temporarily disable canonical mode (ICANON) so that
    sys.stdin.readline() can return arbitrarily long lines — bypassing
    libedit/readline's ~1024-byte per-line buffer that truncates large pastes.
    Echo stays on so the user sees their input normally.

    Termination:
      • URL   — ends after the first non-blank line
      • Text  — ends on three consecutive blank lines, or Ctrl+D / Ctrl+C
    """
    import os

    console.print("  [bold blue]▶[/bold blue]  ", end="")
    sys.stdout.flush()

    # Attempt to disable canonical mode to bypass libedit's ~1024-byte per-line
    # buffer that truncates large paste operations on macOS. Keep ECHO and ISIG.
    _termios_mod = None
    _fd = -1
    _old: list = []
    use_raw = False

    try:
        import termios as _termios_mod
        _fd = sys.stdin.fileno()
        if not os.isatty(_fd):
            raise OSError
        _old = _termios_mod.tcgetattr(_fd)
        _new = _termios_mod.tcgetattr(_fd)
        _new[3] &= ~_termios_mod.ICANON
        _new[6][_termios_mod.VMIN] = 1
        _new[6][_termios_mod.VTIME] = 0
        _termios_mod.tcsetattr(_fd, _termios_mod.TCSAFLUSH, _new)
        use_raw = True
    except (ImportError, OSError, AttributeError):
        pass

    lines: list[str] = []
    consecutive_blanks = 0

    try:
        while True:
            # sys.stdin.readline() handles arbitrarily long lines in non-canonical
            # mode; input() falls back to canonical mode with libedit's line limit.
            raw = sys.stdin.readline() if use_raw else (input() + "\n")
            if not raw:  # EOF (Ctrl+D)
                break
            line = raw.rstrip("\r\n")
            if not line.strip():
                if not lines:
                    continue  # ignore leading blank lines before any content
                consecutive_blanks += 1
                if lines[0].strip().startswith(("http://", "https://")):
                    break  # URL — any blank line finishes
                if consecutive_blanks >= 3:
                    break  # three blank lines → done
                lines.append("")  # preserve internal blank lines
            else:
                consecutive_blanks = 0
                lines.append(line)
                if lines[0].strip().startswith(("http://", "https://")):
                    break  # URL — single line is enough
    except (EOFError, KeyboardInterrupt):
        pass  # Ctrl+D / Ctrl+C — use whatever was collected
    finally:
        if use_raw and _termios_mod is not None:
            _termios_mod.tcsetattr(_fd, _termios_mod.TCSADRAIN, _old)

    return "\n".join(lines).strip()


def _interactive_generate(settings: ResumeAgentSettings) -> None:
    print_section("Generate Resume")
    console.print("Paste a job URL or full description. Finish text with three empty lines.")
    job = _read_jd_input()
    if job.strip():
        _generate_v2(job, 'url' if job.startswith(('https://', 'http://')) else 'text', settings)



# ══════════════════════════════════════════════════════════════════════════════
#  setup
# ══════════════════════════════════════════════════════════════════════════════

@app.command()
def setup() -> None:
    """Run the interactive provider-setup wizard (re-run at any time)."""
    from .ui.setup_wizard import run_setup_wizard

    settings = _load_settings_gracefully()
    print_banner(provider=settings.provider, model=settings.model.default)
    run_setup_wizard(settings)


# ══════════════════════════════════════════════════════════════════════════════
#  init
# ══════════════════════════════════════════════════════════════════════════════

@app.command()
def init(
    source: Path | None = typer.Option(None, '--source', '-s', help='PDF/TEX resume source to review'),
) -> None:
    """Create a durable import draft and explicitly review it before saving."""
    settings = _load_settings_gracefully()
    if source is None:
        candidates = sorted(SOURCE_DIR.glob('*.pdf')) + sorted(SOURCE_DIR.glob('*.tex'))
        if candidates:
            source = candidates[0]
        elif sys.stdin.isatty():
            source = _prompt_for_resume_file()
        else:
            print_error('Provide --source to create a reviewable import draft.')
            raise typer.Exit(2)
    if source is None:
        raise typer.Exit(2)
    _import_v2_source(source, settings)



# ══════════════════════════════════════════════════════════════════════════════
#  generate
# ══════════════════════════════════════════════════════════════════════════════

@app.command()
def generate(
    jd_text: str | None = typer.Option(None, '--jd-text', help='Complete job description'),
    jd_url: str | None = typer.Option(None, '--jd-url', help='Public job posting URL'),
    jd_file: Path | None = typer.Option(None, '--jd-file', exists=True, file_okay=True, dir_okay=False),
    provider: str | None = typer.Option(None, '--provider', '-p'),
    model_name: str | None = typer.Option(None, '--model', '-m'),
    thread_id: str | None = typer.Option(None, '--thread'),
    max_pages: int = typer.Option(2, '--max-pages', min=1, max=5),
) -> None:
    """Generate through content review, exact PDF review, and approved release."""
    if thread_id:
        resume_session(thread_id)
        return
    if sum(bool(value) for value in (jd_text, jd_url, jd_file)) != 1:
        print_error('Provide exactly one of --jd-text, --jd-file, --jd-url.')
        raise typer.Exit(2)
    if jd_file:
        from .config import MAX_RESUME_UPLOAD_BYTES
        with jd_file.open('rb') as stream:
            raw = stream.read(MAX_RESUME_UPLOAD_BYTES + 1)
        if len(raw) > MAX_RESUME_UPLOAD_BYTES:
            print_error('Job file exceeds 10 MiB.')
            raise typer.Exit(2)
        jd_text = raw.decode('utf-8')
    settings = _load_settings_gracefully()
    if provider:
        settings = ResumeAgentSettings.model_validate(settings.model_dump() | {'provider': provider})
    if model_name:
        settings.model.default = model_name
    _generate_v2(jd_url or jd_text or '', 'url' if jd_url else 'text', settings, max_pages=max_pages)



# ══════════════════════════════════════════════════════════════════════════════
#  resume
# ══════════════════════════════════════════════════════════════════════════════

@app.command(name="resume")
def resume_session(thread_id: str = typer.Argument(..., help='Durable run or import operation ID')) -> None:
    """Resume the same saved reviewed workflow; legacy recovery creates a linked run."""
    from .runtime import Runtime
    runtime = Runtime(settings=_load_settings_gracefully())
    try:
        view = runtime.runs.get(thread_id)
    except KeyError:
        try:
            runtime.imports.get(thread_id)
        except KeyError:
            if not sys.stdin.isatty() or Prompt.ask('Type recover to create a linked safe run', default='') != 'recover':
                print_error('Legacy recovery requires explicit interactive confirmation.')
                raise typer.Exit(2)
            view = runtime.runs.recover_legacy(thread_id, provider=runtime.settings.provider, model=runtime.settings.model.default)
            thread_id = view.id
        else:
            result = asyncio.run(_review_v2_import(runtime, thread_id))
            raise typer.Exit(0 if result['status'] in ('complete', 'cancelled') else 2)
    async def resume_work():
        if view.status == 'queued':
            await runtime.runs.drive(thread_id)
        return await _review_v2_run(runtime, thread_id)
    result = asyncio.run(resume_work())
    raise typer.Exit(0 if result.status in ('complete', 'cancelled') else 2)



# ══════════════════════════════════════════════════════════════════════════════
#  config
# ══════════════════════════════════════════════════════════════════════════════

config_app = typer.Typer(help="Manage resume-generator configuration.")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    """Show current configuration."""
    settings = ResumeAgentSettings.load()
    data = settings.model_dump(exclude={"anthropic_api_key", "openai_api_key", "gemini_api_key", "nvidia_api_key", "ollama_api_key"})
    console.print(Panel(yaml.dump(data, default_flow_style=False), title="[accent]Config[/accent]"))
    console.print(f"[muted]Config file: {CONFIG_FILE}[/muted]")
    console.print(f"[muted]Base resume: {BASE_RESUME_FILE}[/muted]")


@config_app.command("set")
def config_set(key: str = typer.Argument(...), value: str = typer.Argument(...)) -> None:
    """Set a configuration value. Example: config set provider openai"""
    settings = ResumeAgentSettings.load()
    parts = key.split(".")
    data = settings.model_dump(exclude={"anthropic_api_key", "openai_api_key", "gemini_api_key", "nvidia_api_key", "ollama_api_key"})

    target = data
    for part in parts[:-1]:
        if part not in target:
            print_error(f"Unknown config key: {key}")
            raise typer.Exit(1)
        target = target[part]

    leaf = parts[-1]
    if leaf not in target:
        print_error(f"Unknown config key: {key}")
        raise typer.Exit(1)

    existing = target[leaf]
    if isinstance(existing, bool):
        target[leaf] = value.lower() in {"true", "1", "yes"}
    elif isinstance(existing, int):
        try:
            target[leaf] = int(value)
        except ValueError:
            print_error(f"Expected an integer for [bold]{key}[/bold], got: {value!r}")
            raise typer.Exit(1)
    else:
        target[leaf] = value

    new_settings = ResumeAgentSettings.model_validate(data)
    new_settings.save()
    print_success(f"Set [bold]{key}[/bold] = [cyan]{value}[/cyan]")


# ══════════════════════════════════════════════════════════════════════════════
#  doctor
# ══════════════════════════════════════════════════════════════════════════════

@app.command()
def doctor() -> None:
    """Check that all required tools and API keys are configured."""
    settings = ResumeAgentSettings.load()
    print_banner(provider=settings.provider)
    print_section("Environment Check")

    checks: list[tuple[str, bool, str]] = []

    tectonic_ok = shutil.which(settings.latex.tectonic_path) is not None
    checks.append((
        "Tectonic (LaTeX engine)",
        tectonic_ok,
        "Install: https://tectonic-typesetting.github.io/ or  cargo install tectonic",
    ))

    poppler_ok = shutil.which("pdftoppm") is not None or shutil.which("pdfinfo") is not None
    checks.append((
        "Poppler utils (PDF→image)",
        poppler_ok,
        "macOS: brew install poppler  |  Ubuntu: sudo apt install poppler-utils",
    ))

    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        playwright_ok = True
    except ImportError:
        playwright_ok = False
    checks.append((
        "Playwright (JS-site fallback)",
        playwright_ok,
        "Run: uv sync && playwright install chromium",
    ))

    import os
    provider = settings.provider
    if provider == "anthropic":
        key_ok = bool(settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))
        checks.append(("ANTHROPIC_API_KEY", key_ok, "Set in .env or export ANTHROPIC_API_KEY=sk-ant-..."))
    elif provider == "openai":
        key_ok = bool(settings.openai_api_key or os.environ.get("OPENAI_API_KEY"))
        checks.append(("OPENAI_API_KEY", key_ok, "Set in .env or export OPENAI_API_KEY=sk-..."))
    elif provider == "gemini":
        key_ok = bool(
            settings.gemini_api_key
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )
        checks.append(("GOOGLE_API_KEY", key_ok, "Run: resume-generator setup  or  export GOOGLE_API_KEY=..."))
    elif provider == "commandcode":
        key_ok = bool(settings.commandcode_api_key or os.environ.get("COMMAND_CODE_API_KEY"))
        checks.append(("COMMAND_CODE_API_KEY", key_ok, "Set your Command Code API key in Settings."))
    elif provider == "nvidia":
        key_ok = bool(settings.nvidia_api_key or os.environ.get("NVIDIA_API_KEY"))
        checks.append(("NVIDIA_API_KEY", key_ok, "Set in .env or export NVIDIA_API_KEY=nvapi-..."))
    elif provider == "ollama":
        try:
            import httpx
            httpx.get(settings.ollama_base_url, timeout=3)
            key_ok = True
        except Exception:
            key_ok = False
        checks.append(("Ollama reachable", key_ok, f"Ensure Ollama is running at {settings.ollama_base_url}"))

    resume_ok = BASE_RESUME_FILE.exists()
    checks.append((
        "Base resume (source of truth)",
        resume_ok,
        f"Drop your PDF into {SOURCE_DIR}/ then run: resume-generator init",
    ))

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(width=4)
    table.add_column(min_width=32)
    table.add_column(style="muted")

    all_ok = True
    for label, ok, hint in checks:
        icon = "[success]✓[/success]" if ok else "[error]✗[/error]"
        table.add_row(icon, label, "" if ok else hint)
        if not ok:
            all_ok = False

    console.print(table)
    console.print()

    if all_ok:
        print_success("All checks passed. Ready to generate resumes!")
    else:
        print_warning("Some checks failed. See hints above.")
        if not tectonic_ok or not poppler_ok:
            console.print(
                "\n[muted]Run [bold]resume-generator install-deps[/bold] to install missing tools automatically.[/muted]"
            )
        raise typer.Exit(2)


# ══════════════════════════════════════════════════════════════════════════════
#  serve
# ══════════════════════════════════════════════════════════════════════════════

@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Host interface to bind."),
    port: int = typer.Option(8000, "--port", "-p", help="Port for the FastAPI server."),
    reload: bool = typer.Option(False, "--reload", help="Enable uvicorn auto-reload."),
) -> None:
    """Serve the local FastAPI + React Resume Generator app."""
    import uvicorn

    if reload:
        console.print(
            "[yellow]Warning:[/yellow] --reload restarts the worker on file changes, "
            "which drops in-flight runs and live WebSocket subscribers (run state is "
            "in-memory). Use it only for frontend/static development."
        )

    uvicorn.run(
        "resume_agent.api:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  install-deps
# ══════════════════════════════════════════════════════════════════════════════

@app.command("install-deps")
def install_deps() -> None:
    """Auto-install Tectonic and Poppler using the system package manager."""
    import platform
    import subprocess as _sp

    settings = _load_settings_gracefully()
    print_banner(provider=settings.provider)
    print_section("Installing Dependencies")

    system = platform.system()

    # ── Detect package manager ────────────────────────────────────────────────
    has_brew   = shutil.which("brew")    is not None
    has_apt    = shutil.which("apt-get") is not None
    has_dnf    = shutil.which("dnf")     is not None
    has_pacman = shutil.which("pacman")  is not None
    has_yum    = shutil.which("yum")     is not None
    has_cargo  = shutil.which("cargo")   is not None
    # Windows package managers
    has_winget = shutil.which("winget") is not None
    has_scoop  = shutil.which("scoop")  is not None
    has_choco  = shutil.which("choco")  is not None

    def _run(cmd: list[str], label: str) -> bool:
        console.print(f"[muted]  $ {' '.join(cmd)}[/muted]")
        try:
            # On Windows, scoop/choco are batch/PowerShell scripts that cannot be
            # launched by CreateProcess directly — shell=True routes through cmd.exe.
            use_shell = system == "Windows"
            _sp.run(cmd, check=True, shell=use_shell)
            print_success(f"{label} installed.")
            return True
        except _sp.CalledProcessError as exc:
            print_error(f"{label} installation failed (exit {exc.returncode}).")
            return False
        except (FileNotFoundError, OSError) as exc:
            print_error(f"{label} installation failed — '{cmd[0]}' could not be launched: {exc}")
            return False

    # ── Tectonic ──────────────────────────────────────────────────────────────
    tectonic_ok = shutil.which(settings.latex.tectonic_path) is not None
    if tectonic_ok:
        print_success("Tectonic already installed — skipping.")
    else:
        console.print("[bold]Installing Tectonic…[/bold]")
        if has_brew:
            tectonic_ok = _run(["brew", "install", "tectonic"], "Tectonic")
        elif has_apt:
            _sp.run(["sudo", "apt-get", "update", "-qq"], check=False)
            tectonic_ok = _run(["sudo", "apt-get", "install", "-y", "tectonic"], "Tectonic")
        elif has_dnf:
            tectonic_ok = _run(["sudo", "dnf", "install", "-y", "tectonic"], "Tectonic")
        elif has_pacman:
            tectonic_ok = _run(["sudo", "pacman", "-S", "--noconfirm", "tectonic"], "Tectonic")
        elif has_yum:
            tectonic_ok = _run(["sudo", "yum", "install", "-y", "tectonic"], "Tectonic")
        elif has_scoop:
            tectonic_ok = _run(["scoop", "install", "tectonic"], "Tectonic")
        elif has_choco:
            tectonic_ok = _run(["choco", "install", "tectonic", "-y"], "Tectonic")
        elif has_winget:
            # Tectonic is not reliably available in winget — scoop is preferred on Windows.
            tectonic_ok = _run(["winget", "install", "--id", "TectonicProject.Tectonic", "-e"], "Tectonic")
        elif has_cargo:
            tectonic_ok = _run(["cargo", "install", "tectonic"], "Tectonic")
        else:
            print_error(
                "No supported package manager found.\n"
                "Install Tectonic manually: https://tectonic-typesetting.github.io/\n"
                "  macOS:   brew install tectonic\n"
                "  Ubuntu:  sudo apt install tectonic\n"
                "  Arch:    sudo pacman -S tectonic\n"
                "  Windows: scoop install tectonic  (install Scoop from scoop.sh first)"
            )

    # ── Poppler ───────────────────────────────────────────────────────────────
    poppler_ok = shutil.which("pdftoppm") is not None or shutil.which("pdfinfo") is not None
    if poppler_ok:
        print_success("Poppler already installed — skipping.")
    else:
        console.print("[bold]Installing Poppler…[/bold]")
        if has_brew:
            poppler_ok = _run(["brew", "install", "poppler"], "Poppler")
        elif has_apt:
            _sp.run(["sudo", "apt-get", "update", "-qq"], check=False)
            poppler_ok = _run(["sudo", "apt-get", "install", "-y", "poppler-utils"], "Poppler")
        elif has_dnf:
            poppler_ok = _run(["sudo", "dnf", "install", "-y", "poppler-utils"], "Poppler")
        elif has_pacman:
            poppler_ok = _run(["sudo", "pacman", "-S", "--noconfirm", "poppler"], "Poppler")
        elif has_yum:
            poppler_ok = _run(["sudo", "yum", "install", "-y", "poppler-utils"], "Poppler")
        elif has_scoop:
            poppler_ok = _run(["scoop", "install", "poppler"], "Poppler")
        elif has_choco:
            poppler_ok = _run(["choco", "install", "poppler", "-y"], "Poppler")
        elif has_winget:
            print_warning(
                "Poppler isn't available via winget.\n"
                "Install via Scoop (recommended on Windows): scoop install poppler\n"
                "Or download a binary from: https://github.com/oschwartz10612/poppler-windows/releases"
            )
        else:
            print_error(
                "No supported package manager found.\n"
                "Install Poppler manually:\n"
                "  macOS:   brew install poppler\n"
                "  Ubuntu:  sudo apt install poppler-utils\n"
                "  Arch:    sudo pacman -S poppler\n"
                "  Windows: scoop install poppler  (install Scoop first from scoop.sh)"
            )

    console.print()
    if tectonic_ok and poppler_ok:
        print_success("All dependencies installed. Run [bold]resume-generator doctor[/bold] to verify.")
    else:
        print_warning("Some dependencies could not be installed automatically. See hints above.")
        raise typer.Exit(1)


# ══════════════════════════════════════════════════════════════════════════════
#  update
# ══════════════════════════════════════════════════════════════════════════════

@app.command("update")
def update_cmd() -> None:
    """Pull the latest changes from GitHub and re-install."""
    from .updater import perform_update

    settings = _load_settings_gracefully()
    print_banner(provider=settings.provider)
    print_section("Updating resume-generator")

    from .updater import _find_repo_root

    repo = _find_repo_root()
    if repo is None:
        print_error(
            "Cannot locate the resume-generator git repository.\n"
            "Re-run the installer to fix this:\n"
            "  Mac/Linux: curl -sSL https://raw.githubusercontent.com/ALDRIN121/resume-agent/main/install.sh | bash\n"
            "  Windows:   irm https://raw.githubusercontent.com/ALDRIN121/resume-agent/main/install.ps1 | iex"
        )
        raise typer.Exit(1)

    console.print(f"[muted]Repo: {repo}[/muted]")
    console.print("[muted]Pulling latest changes from GitHub…[/muted]")
    ok, hint, detail, did_update = perform_update(repo)
    if ok:
        if did_update:
            print_success(
                "Updated successfully!\n"
                "Open a new terminal window and run [bold]resume-generator[/bold] to use the new version."
            )
        else:
            print_success("Already up to date — you have the latest version.")
    elif hint == "windows_locked":
        console.print()
        console.print(
            Panel(
                "[bold]Almost there — one manual step needed.[/bold]\n\n"
                "The code was updated successfully, but Windows won't let the\n"
                "installer overwrite [bold]resume-generator.exe[/bold] while it is running.\n\n"
                "[bold]Fix:[/bold] Open a [bold]NEW[/bold] Command Prompt or PowerShell window\n"
                "(not this one), then run:\n\n"
                f"  [cyan]cd \"{repo}\"[/cyan]\n"
                "  [cyan]uv tool install . --force[/cyan]\n\n"
                "After that completes, your existing terminals will use the new version.",
                title="[yellow]Windows: open a new terminal first[/yellow]",
                border_style="yellow",
                padding=(1, 2),
            )
        )
        raise typer.Exit(1)
    else:
        msg = (
            "Update failed.\n"
            "Try manually:\n"
            f"  cd \"{repo}\"\n"
            "  git pull\n"
            "  uv tool install . --force"
        )
        if detail:
            msg += f"\n\nError detail:\n  {detail[:400]}"
        print_error(msg)
        raise typer.Exit(1)


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _graph_config(thread_id: str, settings: ResumeAgentSettings) -> dict:
    """
    Build the LangGraph runtime config for a generation thread.

    generator_max counts semantic LaTeX attempts; recursion_limit counts
    LangGraph super-steps, so it must be higher than the attempt budget.
    """
    retry_budget = max(1, settings.retries.generator_max)
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": max(50, 20 + retry_budget * 8),
    }


def _handle_hitl_missing(state_values: dict) -> tuple[dict, str]:
    gap = state_values.get("gap_analysis")
    questions = gap.open_questions if gap else []
    if questions:
        print_section("Human Input Needed")
        answers = prompt_hitl_questions(questions)
        print_info(f"Recorded answers for {len(answers)} question(s).")
    else:
        answers = {}
    return {"hitl_answers": answers}, HITL_MISSING_NODE


def _handle_hitl_suggestions(state_values: dict) -> tuple[dict, str]:
    suggestions = _read_suggestions_from_state(state_values)
    if suggestions:
        print_section("Tailoring Suggestions")
        print_info(f"Found {len(suggestions)} suggestion(s) to review.")
        approved_ids = prompt_suggestions(suggestions)
    else:
        print_info("No tailoring suggestions available.")
        approved_ids = []
    return {"approved_suggestion_ids": approved_ids}, HITL_SUGGESTIONS_NODE


def _read_suggestions_from_state(state_values: dict) -> list:
    """
    Extract Suggestion objects from state, robust to checkpoint deserialization.

    LangGraph's SqliteSaver may deserialize Pydantic models as raw dicts
    (unregistered type fallback), or the suggestions field may be absent from
    get_state().values even though gap_analyzer set it. We try the suggestions
    field first, then fall back to gap_analysis.tailoring_ideas.
    """
    from .agents.suggestion_presenter import read_suggestions_from_state

    return read_suggestions_from_state(state_values)


# Registry: add a new HITL node by adding one entry here.
_HITL_HANDLERS = {
    HITL_MISSING_NODE: _handle_hitl_missing,
    HITL_SUGGESTIONS_NODE: _handle_hitl_suggestions,
}


def _run_with_hitl(graph, initial_input, config: dict) -> dict | None:
    """
    Run the graph, handling LangGraph dynamic interrupts for HITL.
    """
    current_input = initial_input
    max_hitl_rounds = 10

    for _ in range(max_hitl_rounds):
        try:
            result = graph.invoke(current_input, config=config)
        except Exception as exc:
            _handle_graph_error(exc)

        interrupts = _extract_interrupt_payloads(result)
        if interrupts:
            current_input = Command(resume=_handle_interrupt_payload(interrupts[0]))
            continue

        state = graph.get_state(config)

        if not state.next:
            return state.values

        next_nodes = set(state.next)
        handled = False
        for node_name, handler in _HITL_HANDLERS.items():
            if node_name in next_nodes:
                state_update, as_node = handler(state.values)
                graph.update_state(config, state_update, as_node=as_node)
                current_input = None
                handled = True
                break

        if not handled:
            print_warning(f"Unexpected graph interrupt at: {next_nodes}")
            return state.values

    print_warning("Maximum HITL rounds reached — stopping.")
    return graph.get_state(config).values


def _extract_interrupt_payloads(result) -> list:
    """Return JSON payloads from LangGraph interrupt outputs."""
    raw_interrupts = getattr(result, "interrupts", None)
    if raw_interrupts is None and isinstance(result, dict):
        raw_interrupts = result.get("__interrupt__", [])
    if not raw_interrupts:
        return []
    return [getattr(item, "value", item) for item in raw_interrupts]


def _handle_interrupt_payload(payload) -> object:
    """Render a LangGraph interrupt payload and return the resume value."""
    if not isinstance(payload, dict):
        print_warning("Unexpected graph interrupt payload.")
        return {}

    kind = payload.get("kind")

    if kind == "missing_questions":
        from .schemas import Question

        questions = []
        for raw in payload.get("questions", []):
            try:
                questions.append(Question.model_validate(raw))
            except Exception:
                pass
        if questions:
            print_section("Human Input Needed")
            answers = prompt_hitl_questions(questions)
            print_info(f"Recorded answers for {len(answers)} question(s).")
        else:
            answers = {}
        return {"answers": answers}

    if kind == "tailoring_suggestions":
        from .schemas import Suggestion

        suggestions = []
        for raw in payload.get("suggestions", []):
            try:
                suggestions.append(Suggestion.model_validate(raw))
            except Exception:
                pass
        if suggestions:
            print_section("Tailoring Suggestions")
            print_info(f"Found {len(suggestions)} suggestion(s) to review.")
            approved_ids = prompt_suggestions(suggestions)
        else:
            print_info("No tailoring suggestions available.")
            approved_ids = []
        return {"approved_ids": approved_ids}

    print_warning(f"Unexpected graph interrupt kind: {kind!r}")
    return {}


def _handle_graph_error(exc: Exception) -> None:
    """
    Translate known LLM/provider errors into friendly panels, then exit.
    Re-raises for anything we don't recognise so the normal traceback appears.
    """
    exc_type = type(exc).__name__
    exc_msg = str(exc)

    if exc_type == "GraphRecursionError":
        print_error_panel(
            "Generation Loop Stopped",
            "LangGraph stopped the run because it exceeded the configured super-step limit.\n\n"
            "This usually means the generator kept cycling through validation without reaching a stable PDF.",
            hint="Try a stronger model, or reduce the resume content before regenerating.",
        )
        raise typer.Exit(3)

    # ── Ollama: server returned 401 Unauthorized ───────────────────────────────
    if exc_type == "ResponseError" and "401" in exc_msg:
        print_error_panel(
            "Ollama: Unauthorized (401)",
            "The Ollama server rejected the request with HTTP 401.\n\n"
            "Possible causes:\n"
            "  • The server was started with OLLAMA_API_KEY set\n"
            "  • A reverse-proxy in front of Ollama requires authentication\n\n"
            "Fix: export OLLAMA_API_KEY=<your-key> before running resume-generator,\n"
            "or restart Ollama without the API-key requirement.",
            hint="Check: ollama serve  (no extra auth flags)",
        )
        raise typer.Exit(1)

    # ── Ollama: other server-side errors ───────────────────────────────────────
    if exc_type == "ResponseError":
        print_error_panel(
            "Ollama Server Error",
            f"Ollama returned an unexpected error:\n\n  {exc_msg}",
            hint="Ensure Ollama is running: ollama serve",
        )
        raise typer.Exit(1)

    # ── Anthropic / OpenAI / Gemini auth failures ──────────────────────────────
    if "AuthenticationError" in exc_type or (
        "401" in exc_msg and any(p in exc_msg.lower() for p in ("api key", "apikey", "authentication", "unauthorized"))
    ):
        print_error_panel(
            "Authentication Failed",
            f"The API request was rejected (invalid or missing API key).\n\n{exc_msg}",
            hint="Run: resume-generator setup  — to re-enter your API key",
        )
        raise typer.Exit(1)

    # ── Unknown error — let Python show the full traceback ────────────────────
    raise exc


def _load_settings_or_exit() -> ResumeAgentSettings:
    """Load settings, exiting gracefully on config file errors."""
    try:
        return ResumeAgentSettings.load()
    except Exception as e:
        err_console.print(f"[error]Config error:[/error] {e}")
        raise typer.Exit(1)


def _load_settings_gracefully() -> ResumeAgentSettings:
    """Load settings silently, returning defaults if config doesn't exist yet."""
    try:
        return ResumeAgentSettings.load()
    except Exception:
        return ResumeAgentSettings()


def _preflight_checks(settings: ResumeAgentSettings) -> None:
    """
    Warn and offer to install Tectonic / Poppler if they're missing.
    Called once at the start of the generation loop — non-fatal so the user
    can still proceed (maybe they want to fix it mid-session).
    """
    tectonic_ok = shutil.which(settings.latex.tectonic_path) is not None
    poppler_ok = shutil.which("pdftoppm") is not None or shutil.which("pdfinfo") is not None

    missing = []
    if not tectonic_ok:
        missing.append("Tectonic (LaTeX → PDF compiler)")
    if not poppler_ok:
        missing.append("Poppler  (PDF → image renderer)")

    if not missing:
        return

    names = "\n".join(f"  • {m}" for m in missing)
    console.print(
        Panel(
            f"[bold]Required tools not found:[/bold]\n\n{names}\n\n"
            "Generation will fail without these.\n"
            "Run [bold]resume-generator install-deps[/bold] to install automatically.",
            title="[error]Missing Dependencies[/error]",
            border_style="red",
            padding=(1, 2),
        )
    )
    if confirm("Install missing dependencies now?", default=True):
        install_deps()


def _check_base_resume_or_exit() -> None:
    if not BASE_RESUME_FILE.exists():
        print_error_panel(
            "Base Resume Not Found",
            f"No base resume at: {BASE_RESUME_FILE}",
            hint="Run first: resume-generator init --source <your_resume.tex|.pdf>",
        )
        raise typer.Exit(1)


def _prompt_save_and_open(suggested_path: str) -> str:
    """
    Prompt the user for a final save location (default = suggested_path).
    If they enter a different path the file is moved there.
    The PDF is then opened in the system default viewer.
    Returns the path where the file actually ended up.
    """
    console.print()
    entered = Prompt.ask(
        "  [accent]Save PDF to[/accent]",
        console=console,
        default=suggested_path,
    ).strip()

    final_path = suggested_path
    if entered and entered != suggested_path:
        dest = Path(entered).expanduser()
        if dest.is_dir():
            dest = dest / Path(suggested_path).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(suggested_path, str(dest))
        final_path = str(dest)
        print_success(f"PDF moved → [cyan]{final_path}[/cyan]")

    try:
        webbrowser.open(Path(final_path).as_uri())
    except Exception:
        pass

    return final_path


def _ensure_llm_ready(settings: ResumeAgentSettings) -> ResumeAgentSettings:
    """
    Ensure LLM is configured and reachable before any command that needs it.

    - Not configured → runs setup wizard.
    - Configured but unreachable → shows error and offers to re-run setup.

    Returns (possibly updated) settings.
    """
    from .ui.setup_wizard import run_setup_wizard

    if not settings.is_configured():
        console.print(
            Panel(
                "[bold]Welcome to Resume Generator![/bold]\n"
                "[muted]No provider configured yet. Let's set that up first.[/muted]",
                border_style="blue",
                padding=(1, 2),
            )
        )
        return run_setup_wizard(settings)

    console.print("Checking LLM connection… ", end="")
    try:
        from .llm import get_chat_model
        llm = get_chat_model(settings, task="default", temperature=0.0)
        llm.invoke("Reply with the single word: OK")
        console.print("[success]✓[/success]")
        return settings
    except Exception as exc:
        console.print()
        print_error(f"LLM connection failed: {exc}")
        console.print()
        if confirm("Run setup to reconfigure?", default=True):
            return run_setup_wizard(settings)
        raise typer.Exit(1)


async def _review_v2_run(runtime, run_id, *, interactive=None, ask=None):
    """Review shared typed pauses; an empty answer never grants approval."""
    from .contracts import AskMissing, Continue, PresentSuggestions, ReviewPdf
    from .ui.prompts import display_content_preview
    if interactive is None:
        interactive = sys.stdin.isatty()
    ask = ask or (lambda message: Prompt.ask(message, default=''))
    view = runtime.runs.get(run_id)
    while view.pending is not None or view.status == 'interrupted':
        console.print(f'Run: {run_id}', markup=False)
        if not interactive:
            console.print('A human decision is pending. Resume this run interactively.', markup=False)
            return view
        action_id = str(uuid.uuid4())
        if view.status == 'interrupted':
            if ask('Type continue to resume the interrupted work') != 'continue':
                return view
            action = Continue(action_id=action_id)
        else:
            pending = view.pending
            if pending.kind == 'ask_missing':
                answers = {}
                for question in pending.payload['questions']:
                    console.print(question['why_asking'], markup=False)
                    answers[question['id']] = ask(question['prompt'])
                if ask('Type continue to submit these exact answers') != 'continue':
                    return view
                action = AskMissing(action_id=action_id, request_id=pending.request_id, answers=answers)
            elif pending.kind == 'present_suggestions':
                for proposal in pending.payload['proposals']:
                    console.print_json(data=proposal)
                selected_text = ask('Proposal IDs to select, separated by commas (default none)')
                selected = [value.strip() for value in selected_text.split(',') if value.strip()]
                preview = runtime.workflow.content_preview(run_id, pending.review_id, pending.source_revision, selected)
                display_content_preview(preview)
                if ask('Type approve to confirm this complete content and its hash') != 'approve':
                    return view
                action = PresentSuggestions(action_id=action_id, review_id=pending.review_id,
                    source_revision=pending.source_revision, approved_ids=selected, content_hash=preview.manifest.content_hash)
            elif pending.kind == 'review_pdf':
                from .checkpoint import read_v2_checkpoint
                values = read_v2_checkpoint(runtime.store.checkpoint_path, 'run', run_id)['values']
                console.print('Draft PDF: ' + values['render_record']['pdf_path'], markup=False)
                console.print('PDF hash: ' + pending.review.pdf_hash, markup=False)
                console.print_json(data=pending.payload)
                decision = 'approve' if ask('Inspect the exact PDF, then type approve (default reject)') == 'approve' else 'reject'
                review = pending.review
                action = ReviewPdf(action_id=action_id, decision=decision, review_id=review.review_id,
                    content_hash=review.content_hash, render_hash=review.render_hash, pdf_hash=review.pdf_hash)
            else:
                console.print('This decision requires another supported client.', markup=False)
                return view
        view = await runtime.runs.drive(run_id, action)
    if view.release:
        console.print('Released PDF: ' + view.release.destination, markup=False)
        console.print('PDF hash: ' + view.release.pdf_hash, markup=False)
    elif view.diagnostics:
        console.print_json(data=[item.model_dump() for item in view.diagnostics])
    return view


async def _review_v2_import(runtime, operation_id, *, interactive=None, ask=None):
    from .contracts import AcceptImport, Continue, RejectImport
    if interactive is None:
        interactive = sys.stdin.isatty()
    ask = ask or (lambda message: Prompt.ask(message, default=''))
    draft = runtime.imports.get(operation_id)
    console.print('Import operation: ' + operation_id, markup=False)
    if draft['status'] == 'pending_model':
        draft = await runtime.imports.drive(operation_id)
    if draft['status'] == 'interrupted' and interactive:
        if ask('Type continue to resume this interrupted import') == 'continue':
            draft = await runtime.imports.drive(operation_id, Continue(action_id=str(uuid.uuid4())))
    if not interactive or draft['pending'] is None:
        if draft['pending']:
            console.print('Review the source and draft interactively before acceptance.', markup=False)
        return draft
    pending = draft['pending']
    console.print('Complete extracted source:', markup=False)
    for page in draft['source']['pages']:
        console.print(f"Page {page['page_number']}", markup=False)
        console.print(page['text'], markup=False)
        if page['warning']:
            console.print(page['warning'], markup=False)
    console.print('Parsed draft — compare every field with the source:', markup=False)
    console.print_json(data=draft['draft'])
    console.print(draft['coverage_note'], markup=False)
    blanks = []
    for number in pending['unreadable_pages']:
        if ask(f'Type blank to confirm unreadable page {number} is intentionally blank') == 'blank':
            blanks.append(number)
    if (len(blanks) == len(pending['unreadable_pages'])
            and ask('Type accept to save this exact reviewed draft (default reject)') == 'accept'):
        action = AcceptImport(action_id=str(uuid.uuid4()), review_id=pending['review_id'],
            draft_hash=pending['draft_hash'], expected_profile_revision=pending['expected_profile_revision'],
            intentionally_blank_pages=blanks)
    else:
        action = RejectImport(action_id=str(uuid.uuid4()), review_id=pending['review_id'])
    return await runtime.imports.drive(operation_id, action)


def _import_v2_source(source, settings):
    from .config import MAX_RESUME_UPLOAD_BYTES
    from .runtime import Runtime
    runtime = Runtime(settings=settings)
    try:
        with Path(source).expanduser().open('rb') as stream:
            raw = stream.read(MAX_RESUME_UPLOAD_BYTES + 1)
        operation = runtime.imports.create(raw, Path(source).name)
    except (ValueError, OSError) as exc:
        print_error(str(exc))
        raise typer.Exit(2) from None
    async def import_work():
        await runtime.imports.drive(operation['id'])
        return await _review_v2_import(runtime, operation['id'])
    result = asyncio.run(import_work())
    if result['status'] == 'complete':
        print_success('The reviewed profile was saved.')
    elif result['status'] == 'cancelled':
        print_info('Import rejected. The draft and source remain available.')
    else:
        if result['diagnostics']:
            console.print_json(data=result['diagnostics'])
        raise typer.Exit(3 if result['status'] == 'failed' else 2)


def _generate_v2(job, input_type, settings, *, max_pages=2):
    from .contracts import RunRequest
    from .run_store import Conflict
    from .runtime import Runtime
    runtime = Runtime(settings=settings)
    snapshot = runtime.profiles.load_snapshot()
    if snapshot and snapshot.review_required:
        console.print('Current profile requires explicit review before a new run.', markup=False)
        if not sys.stdin.isatty():
            raise typer.Exit(2)
        console.print_json(data=snapshot.profile.model_dump(mode='json'))
        if Prompt.ask('Type review to confirm this exact current profile', default='') != 'review':
            raise typer.Exit(2)
        runtime.profiles.review_current_profile(snapshot.revision)
    try:
        run = runtime.create_run(RunRequest(job_input=job, input_type=input_type, max_pages=max_pages))
    except (ValueError, Conflict):
        for step in runtime.readiness()['next_steps']:
            console.print(step, markup=False)
        raise typer.Exit(2) from None
    console.print('Run: ' + run.id, markup=False)
    async def generate_work():
        await runtime.runs.drive(run.id)
        return await _review_v2_run(runtime, run.id)
    result = asyncio.run(generate_work())
    if result.status not in ('complete', 'cancelled'):
        raise typer.Exit(2 if result.pending or result.status == 'interrupted' else 3)


# Career commands deliberately call the same services as the web application.
jobs_app = typer.Typer(help='Capture and inspect immutable job descriptions.')
memory_app = typer.Typer(help='Review durable corrections and future writing preferences.')
evaluations_app = typer.Typer(help='Inspect, continue or cancel saved role evaluations.')
app.add_typer(jobs_app, name='jobs')
app.add_typer(memory_app, name='memory')
app.add_typer(evaluations_app, name='evaluations')


def _career_runtime():
    from .runtime import Runtime
    return Runtime(settings=_load_settings_gracefully())


def _career_value(value, prefix=''):
    if isinstance(value, dict):
        for key, item in value.items():
            _career_value(item, prefix + key.replace('_', ' ') + ': ')
    elif isinstance(value, list):
        for index, item in enumerate(value, 1):
            _career_value(item, prefix + str(index) + '. ')
    else:
        console.print(prefix + (str(value) if value is not None else 'Not provided'), markup=False)


def _career_error(exc):
    print_error(str(exc))
    raise typer.Exit(2) from None


@jobs_app.command('capture')
def capture_job(text: str | None = typer.Option(None, '--text'),
                source: Path | None = typer.Option(None, '--file', exists=True, dir_okay=False),
                source_key: str | None = typer.Option(None, '--source-key'),
                company: str | None = typer.Option(None, '--company'), role: str | None = typer.Option(None, '--role')):
    try:
        if (text is None) == (source is None):
            raise ValueError('Provide exactly one of --text or --file.')
        if source:
            if source.stat().st_size > 10 * 1024 * 1024:
                raise ValueError('Job source exceeds the 10 MiB limit.')
            text = source.read_text(encoding='utf-8')
        job = _career_runtime().jobs.capture(text, source_key=source_key, company=company, role=role)
        console.print('Job: ' + job.id, markup=False)
        console.print(job.text, markup=False)
    except (ValueError, KeyError, OSError) as exc:
        _career_error(exc)


@jobs_app.command('list')
def list_jobs_cli():
    for job in _career_runtime().jobs.list():
        console.print(f'{job.id} · {job.company or "Company not supplied"} · {job.role or "Role not supplied"}', markup=False)


@jobs_app.command('inspect')
def inspect_job(job_id: str):
    try:
        _career_value(_career_runtime().jobs.get(job_id).model_dump(mode='json'))
    except (KeyError, ValueError) as exc:
        _career_error(exc)


@jobs_app.command('tailor')
def tailor_job(job_id: str, evaluation: str | None = typer.Option(None), override: bool = typer.Option(False),
               max_pages: int = typer.Option(2, min=1, max=5)):
    from .contracts import RunRequest
    from .run_store import Conflict
    try:
        runtime = _career_runtime()
        job = runtime.jobs.get(job_id)
        run = runtime.create_run(RunRequest(job_input=job.text, input_type='text', job_id=job.id,
            evaluation_id=evaluation, evaluation_override=override, max_pages=max_pages))
        console.print('Run: ' + run.id, markup=False)
        async def work():
            await runtime.runs.drive(run.id)
            return await _review_v2_run(runtime, run.id)
        result = asyncio.run(work())
        if result.status not in ('complete', 'cancelled'):
            raise typer.Exit(2 if result.pending or result.status == 'interrupted' else 3)
    except (ValueError, KeyError, Conflict) as exc:
        _career_error(exc)


def _show_evaluation(view):
    console.print('Evaluation: ' + view['id'] + ' · ' + view['status'], markup=False)
    if view['stale']:
        console.print('Changed inputs: ' + ', '.join(view['stale_reasons']), markup=False)
    if view['result']:
        result, fit = view['result'], view['result']['fit']
        console.print('Advisory evidence fit (product defaults; not a hiring probability)', markup=False)
        console.print('Insufficient evidence to score.' if fit['lower'] is None else
                      f"Evidence interval: {fit['lower']}–{fit['upper']} · Coverage: {fit['coverage']}%", markup=False)
        console.print(f"Eligibility: {result['eligibility_status']} · Recommendation: {fit['recommendation']}", markup=False)
        _career_value(result['analysis'])
    elif view['diagnostics']:
        _career_value(view['diagnostics'])


@app.command('evaluate')
def evaluate_job(job_id: str, authorization: str | None = typer.Option(None), clearance: str | None = typer.Option(None),
                 presence: str | None = typer.Option(None), hard_constraint: str | None = typer.Option(None)):
    from .run_store import Conflict
    try:
        runtime = _career_runtime()
        facts = {k: v for k, v in dict(authorization=authorization, clearance=clearance, presence=presence,
                                      user_hard_constraint=hard_constraint).items() if v is not None}
        created = runtime.evaluations.create(job_id, eligibility_facts=facts)
        console.print('Saved evaluation: ' + created['id'], markup=False)
        result = asyncio.run(runtime.evaluations.drive(created['id']))
        _show_evaluation(result)
        if result['status'] == 'failed':
            raise typer.Exit(3)
    except (ValueError, KeyError, Conflict) as exc:
        _career_error(exc)


@evaluations_app.command('inspect')
def inspect_evaluation(evaluation_id: str):
    try:
        _show_evaluation(_career_runtime().evaluations.get(evaluation_id))
    except (ValueError, KeyError) as exc:
        _career_error(exc)


@evaluations_app.command('continue')
def continue_evaluation_cli(evaluation_id: str, action_id: str = typer.Option(...)):
    from .contracts import Continue
    from .run_store import Conflict
    try:
        result = asyncio.run(_career_runtime().evaluations.drive(evaluation_id, Continue(action_id=action_id)))
        _show_evaluation(result)
        if result['status'] == 'failed':
            raise typer.Exit(3)
    except (ValueError, KeyError, Conflict) as exc:
        _career_error(exc)


@evaluations_app.command('cancel')
def cancel_evaluation_cli(evaluation_id: str):
    try:
        _show_evaluation(_career_runtime().evaluations.cancel(evaluation_id))
    except (ValueError, KeyError) as exc:
        _career_error(exc)


@memory_app.command('list')
def list_memory_cli():
    for record in _career_runtime().memory.list():
        console.print(f"{record['id']} · {record['kind']} · {record['status']}", markup=False)
        _career_value(record['payload'])


@memory_app.command('inspect')
def inspect_memory_cli(record_id: str):
    from .run_store import Conflict
    try:
        preview = _career_runtime().memory.preview(record_id)
        console.print('Before', markup=False)
        _career_value(preview['before'])
        console.print('After', markup=False)
        _career_value(preview['after'])
        console.print('Source', markup=False)
        _career_value(preview['record']['source_refs'])
        console.print('Revision: ' + preview['record']['revision'], markup=False)
        if preview['stale']:
            console.print('Profile changed. Create a new proposal before accepting.', markup=False)
    except (ValueError, KeyError, Conflict) as exc:
        _career_error(exc)


@memory_app.command('propose')
def propose_memory_cli(kind: str = typer.Option(...), source: str = typer.Option(...),
                       instruction: str | None = typer.Option(None), payload_file: Path | None = typer.Option(None, exists=True, dir_okay=False),
                       base_revision: str | None = typer.Option(None), supersedes: str | None = typer.Option(None),
                       supersedes_revision: str | None = typer.Option(None)):
    import json

    from .run_store import Conflict
    try:
        if payload_file:
            if payload_file.stat().st_size > 10 * 1024 * 1024:
                raise ValueError('Proposal exceeds the 10 MiB limit.')
            payload = json.loads(payload_file.read_text(encoding='utf-8'))
        elif kind == 'writing_rule' and instruction is not None:
            payload = {'instruction': instruction}
        else:
            raise ValueError('Provide --payload-file, or --instruction for a writing rule.')
        if bool(supersedes) != bool(supersedes_revision):
            raise ValueError('Replacement requires both --supersedes and --supersedes-revision.')
        body = dict(kind=kind, payload=payload, source_refs=[{'kind': 'user_text', 'text': source}])
        if base_revision:
            body['base_profile_revision'] = base_revision
        if supersedes:
            body['supersedes'] = {'id': supersedes, 'revision': supersedes_revision}
        record = _career_runtime().memory.propose(body)
        console.print('Pending proposal: ' + record['id'], markup=False)
        console.print('Inspect the exact before/after values and source before deciding.', markup=False)
    except (ValueError, KeyError, OSError, Conflict) as exc:
        _career_error(exc)


@memory_app.command('decide')
def decide_memory_cli(record_id: str, decision: str = typer.Option(...), revision: str = typer.Option(...),
                      action_id: str = typer.Option(...)):
    from .run_store import Conflict
    try:
        result = _career_runtime().memory.decide(record_id, decision, expected_revision=revision, action_id=action_id)
        console.print('Memory decision: ' + result['status'], markup=False)
    except (ValueError, KeyError, Conflict) as exc:
        _career_error(exc)


discover_app = typer.Typer(help='Configure public boards and run explicit bounded scans.')
applications_app = typer.Typer(help='Record local application events; never submit to employers.')
app.add_typer(discover_app, name='discover')
app.add_typer(applications_app, name='applications')


def _career_call(work):
    from .run_store import Conflict
    try:
        result = work(_career_runtime())
        _career_value(result)
        if isinstance(result, dict) and result.get('status') == 'failed':
            raise typer.Exit(3)
    except (ValueError, KeyError, OSError, Conflict) as exc:
        _career_error(exc)


def _career_file(path, schema):
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError('Action file exceeds 10 MiB.')
    return schema.model_validate_json(path.read_text(encoding='utf-8'))


@discover_app.command('sources')
def discovery_sources_cli():
    _career_call(lambda runtime: runtime.discovery.sources())


@discover_app.command('configure')
def discovery_configure_cli(source: Path = typer.Option(..., '--file', exists=True, dir_okay=False)):
    from .api.routers.discovery import ConfigureSources
    def work(runtime):
        body = _career_file(source, ConfigureSources)
        return runtime.discovery.replace_sources([s.model_dump(mode='json', exclude_none=True) for s in body.sources],
            expected_revision=body.expected_revision, action_id=body.action_id)
    _career_call(work)


@discover_app.command('refresh')
def discovery_refresh_cli(revision: str = typer.Option(...), action_id: str = typer.Option(...)):
    def work(runtime):
        created = runtime.discovery.create_sync(expected_sources_revision=revision, action_id=action_id)
        return asyncio.run(runtime.discovery.drive(created['id']))
    _career_call(work)


@discover_app.command('inspect')
def discovery_inspect_cli(sync_id: str):
    _career_call(lambda runtime: runtime.discovery.get_sync(sync_id))


@discover_app.command('continue')
def discovery_continue_cli(sync_id: str, action_id: str = typer.Option(...)):
    _career_call(lambda runtime: asyncio.run(runtime.discovery.drive(sync_id, continue_action_id=action_id)))


@discover_app.command('cancel')
def discovery_cancel_cli(sync_id: str, action_id: str = typer.Option(...)):
    _career_call(lambda runtime: runtime.discovery.cancel(sync_id, action_id=action_id))


@discover_app.command('postings')
def discovery_postings_cli(source: str | None = typer.Option(None), state: str | None = typer.Option(None),
                          limit: int = typer.Option(50, min=1, max=1000), offset: int = typer.Option(0, min=0)):
    _career_call(lambda runtime: runtime.discovery.postings_page(source_id=source, state=state, limit=limit, offset=offset))


@applications_app.command('list')
def applications_list_cli():
    _career_call(lambda runtime: runtime.applications.list())


@applications_app.command('create')
def application_create_cli(job_id: str, action_id: str = typer.Option(...), company: str | None = typer.Option(None)):
    _career_call(lambda runtime: runtime.applications.create(job_id, action_id=action_id, company=company))


@applications_app.command('inspect')
def application_inspect_cli(application_id: str):
    _career_call(lambda runtime: runtime.applications.get(application_id))


@applications_app.command('event')
def application_event_cli(application_id: str, source: Path = typer.Option(..., '--file', exists=True, dir_okay=False)):
    from .applications import ApplicationEventRequest
    def work(runtime):
        body = _career_file(source, ApplicationEventRequest)
        return runtime.applications.append(application_id, body.event.model_dump(mode='json'),
            action_id=body.action_id, expected_revision=body.expected_revision)
    _career_call(work)


class _AgentJsonCommand(typer.core.TyperCommand):
    def parse_args(self, ctx, args):
        from click import UsageError
        command = args[0] if args and not args[0].startswith('-') else ''
        try:
            return super().parse_args(ctx, args)
        except UsageError:
            from .agent_cli import run_command
            run_command(command, None, None, lambda: None, extra_args=('invalid_arguments',))
            raise typer.Exit(1) from None


@app.command('agent', cls=_AgentJsonCommand, context_settings={'allow_extra_args': True, 'ignore_unknown_options': True})
def agent_json(ctx: typer.Context, command: str | None = typer.Argument(None),
               input_file: Path | None = typer.Option(None, '--input'), resource: str | None = typer.Option(None, '--resource')):
    """Run one non-interactive JSON command. Human reviews remain explicit."""
    from .agent_cli import run_command
    raise typer.Exit(run_command(command, input_file, resource, _career_runtime, ctx.args))

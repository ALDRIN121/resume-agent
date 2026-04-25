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

import logging
import shutil
import time
import uuid
import warnings
import webbrowser
from pathlib import Path
from typing import Optional

# Silence LangGraph's noisy "Deserializing unregistered type" messages.
# These fire every time a checkpoint is loaded and are not actionable.
warnings.filterwarnings("ignore", message=".*Deserializing unregistered type.*")
for _lg in ("langgraph", "langgraph.checkpoint", "langgraph.checkpoint.serde",
            "langgraph.checkpoint.serde.msgpack"):
    logging.getLogger(_lg).setLevel(logging.ERROR)

import typer
import yaml
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .checkpoint import get_checkpointer
from .config import (
    BASE_RESUME_FILE,
    CONFIG_FILE,
    SOURCE_DIR,
    ResumeAgentSettings,
)
from .graph import HITL_MISSING_NODE, HITL_NODES, HITL_SUGGESTIONS_NODE, build_graph
from .state import STATE_SCHEMA_VERSION, ResumeGenState
from .ui.banner import print_banner
from .ui.console import console, err_console
from .ui.panels import (
    print_error,
    print_error_panel,
    print_final_summary,
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
    from .ui.setup_wizard import run_setup_wizard

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
    settings = _ensure_llm_ready(settings)

    # ── Base resume (only if missing) ─────────────────────────────────────────
    if not BASE_RESUME_FILE.exists():
        console.print()
        print_warning("No base resume found.")
        _interactive_init_resume(settings)
        if not BASE_RESUME_FILE.exists():
            print_error("Cannot generate without a base resume.")
            raise typer.Exit(1)

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
    """Ask for a resume file path and parse it."""
    from .agents.base_resume_loader import parse_and_save_resume

    SOURCE_DIR.mkdir(parents=True, exist_ok=True)

    # Auto-detect from the source folder first
    candidates = sorted(SOURCE_DIR.glob("*.pdf")) + sorted(SOURCE_DIR.glob("*.tex"))
    if candidates:
        source = candidates[0]
        if len(candidates) > 1:
            names = ", ".join(c.name for c in candidates)
            print_warning(f"Multiple files in source/: {names}. Using: {source.name}")
        print_info(f"Found resume in source/: {source.name}")
    else:
        # No file in source/ — prompt with validation loop until a valid file is given
        console.print()
        console.print(
            Panel(
                f"[bold]No resume found.[/bold]\n\n"
                f"  Option 1: Drop your PDF/TEX into  [bold]{SOURCE_DIR}/[/bold]\n"
                f"            then press Enter to re-check.\n\n"
                f"  Option 2: Enter the full path to your resume file below.",
                border_style="yellow",
                padding=(0, 2),
            )
        )
        source = _prompt_for_resume_file()
        if source is None:
            return   # user aborted

    try:
        resume = parse_and_save_resume(source)
    except (ValueError, RuntimeError) as exc:
        print_error_panel("Parsing Failed", str(exc))
        return

    print_success(f"Base resume saved for: [bold]{resume.personal.full_name}[/bold]")


def _prompt_for_resume_file() -> Optional[Path]:
    """
    Interactive loop: keep prompting until the user provides a valid .pdf/.tex file.
    Returns the resolved Path, or None if the user types 'q' to abort.
    """
    from rich.markup import escape as _esc

    _VALID_EXTS = {".pdf", ".tex"}
    # All quote variants a user might wrap a path in (regular + curly + backtick)
    _QUOTES = '"\'`\u2018\u2019\u201c\u201d'

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

    Shows a single `▶` prompt, then reads every line silently with plain
    input() so pasted multi-line text flows through naturally — no
    "(continue…)" interrupt after every pasted sentence.

    Termination:
      • URL   — ends after the first non-blank line
      • Text  — ends on three consecutive blank lines, or Ctrl+D / Ctrl+C
    """
    # Print a single, styled caret — cursor lands right after it.
    # All subsequent pasted/typed lines appear below without re-printing any label.
    console.print("  [bold blue]▶[/bold blue]  ", end="")

    lines: list[str] = []
    consecutive_blanks = 0

    try:
        while True:
            line = input()  # reads one line; terminal echoes it naturally
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

    return "\n".join(lines).strip()


def _interactive_generate(settings: ResumeAgentSettings) -> None:
    """Ask for JD input and run the full generation pipeline."""
    print_section("Generate Resume")
    console.print(
        Panel(
            "[bold]Paste a job URL or the full job description below.[/bold]\n\n"
            "  [accent]URL[/accent]   — paste the link and press [bold]Enter[/bold]\n"
            "  [accent]Text[/accent]  — paste the description, then press [bold]Enter[/bold] "
            "three times on an empty line to finish",
            border_style="blue",
            padding=(0, 2),
        )
    )
    console.print()

    jd_input = _read_jd_input()

    if not jd_input:
        print_warning("No input — skipping.")
        return

    is_url = jd_input.startswith(("http://", "https://"))
    t_id = str(uuid.uuid4())

    initial_state: ResumeGenState = {
        "schema_version": STATE_SCHEMA_VERSION,
        "input_type": "url" if is_url else "text",
        "raw_input": jd_input,
        "latex_errors": [],
        "pdf_errors": [],
        "page_images": [],
        "hitl_answers": {},
        "approved_suggestion_ids": [],
        "suggestions": [],
        "generator_retries": 0,
        "validation_passed": False,
        "messages": [],
    }

    cfg = {"configurable": {"thread_id": t_id}}
    console.print(f"\n[muted]Session: {t_id}[/muted]")
    console.print(f"[muted](Resume if interrupted: resume-generator resume {t_id})[/muted]\n")

    start_time = time.perf_counter()

    with get_checkpointer() as checkpointer:
        graph = build_graph(checkpointer=checkpointer, settings=settings)
        final_state = _run_with_hitl(graph, initial_state, cfg)

    elapsed = time.perf_counter() - start_time
    final_pdf = final_state.get("final_pdf_path") if final_state else None

    if final_pdf:
        jd = final_state.get("jd")
        final_pdf = _prompt_save_and_open(final_pdf)
        print_final_summary(
            company=jd.company if jd else "Unknown",
            role=jd.role_title if jd else "Unknown",
            pdf_path=final_pdf,
            elapsed=elapsed,
            retries=max(0, (final_state.get("generator_retries") or 1) - 1),
        )
    elif final_state and final_state.get("scrape_error"):
        print_error_panel(
            "Scraping Failed",
            final_state["scrape_error"],
            hint="Paste the job description text instead of a URL.",
        )
    else:
        print_error("Generation failed. Check the output above for details.")


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
    source: Optional[Path] = typer.Option(
        None,
        "--source",
        "-s",
        help=(
            "Path to your resume (.tex or .pdf). "
            f"If omitted, auto-detects from ~/.resume_generator/source/"
        ),
    ),
) -> None:
    """Parse your resume and save it as the base (source of truth).

    Drop your PDF into ~/.resume_generator/source/ and run this command with no
    arguments, or pass --source to specify a file explicitly.
    Any previously parsed base resume is replaced automatically.
    """
    from .agents.base_resume_loader import parse_and_save_resume

    settings = _load_settings_or_exit()
    print_banner(provider=settings.provider, model=settings.model.default)
    settings = _ensure_llm_ready(settings)

    # ── Resolve source file ────────────────────────────────────────────────────
    if source is None:
        SOURCE_DIR.mkdir(parents=True, exist_ok=True)
        candidates = sorted(SOURCE_DIR.glob("*.pdf")) + sorted(SOURCE_DIR.glob("*.tex"))
        if not candidates:
            console.print(
                Panel(
                    f"[bold]No resume found in source folder.[/bold]\n\n"
                    f"  Option 1: Drop your PDF/TEX into  [bold]{SOURCE_DIR}/[/bold]\n"
                    f"            then press Enter to re-check.\n\n"
                    f"  Option 2: Enter the full path to your resume file below.",
                    border_style="yellow",
                    padding=(0, 2),
                )
            )
            resolved = _prompt_for_resume_file()
            if resolved is None:
                raise typer.Exit(1)
            source = resolved
        else:
            if len(candidates) > 1:
                names = ", ".join(c.name for c in candidates)
                print_warning(f"Multiple files in source/: {names}. Using: {candidates[0].name}")
            source = candidates[0]
    else:
        source = Path(source).expanduser().resolve()
        if not source.suffix.lower() in {".pdf", ".tex"}:
            print_error(f"Unsupported format '{source.suffix}'. Only .pdf and .tex are accepted.")
            raise typer.Exit(1)
        if not source.exists():
            print_error(f"File not found: {source}")
            raise typer.Exit(1)

    print_info(f"Source: {source}")

    # ── Remove stale base resume so a fresh parse always wins ─────────────────
    if BASE_RESUME_FILE.exists():
        BASE_RESUME_FILE.unlink()
        print_info("Removed previous base resume — re-parsing from source…")

    # ── Parse ──────────────────────────────────────────────────────────────────
    try:
        resume = parse_and_save_resume(source)
    except (ValueError, RuntimeError) as e:
        print_error_panel("Parsing Failed", str(e))
        raise typer.Exit(1)

    print_success(f"Base resume saved for: [bold]{resume.personal.full_name}[/bold]")
    print_info(f"File: {BASE_RESUME_FILE}")
    print_info("You can now run: [bold]resume-generator generate --jd-url <URL>[/bold]")


# ══════════════════════════════════════════════════════════════════════════════
#  generate
# ══════════════════════════════════════════════════════════════════════════════

@app.command()
def generate(
    jd_text: Optional[str] = typer.Option(
        None, "--jd-text", help="Paste the full job description text"
    ),
    jd_url: Optional[str] = typer.Option(
        None, "--jd-url", help="URL of the job posting to scrape"
    ),
    jd_file: Optional[Path] = typer.Option(
        None, "--jd-file", help="Path to a text file containing the job description",
        exists=True, file_okay=True, dir_okay=False, resolve_path=True,
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p", help="LLM provider: anthropic | openai | ollama | gemini | nvidia"
    ),
    model_name: Optional[str] = typer.Option(
        None, "--model", "-m", help="Override model name"
    ),
    thread_id: Optional[str] = typer.Option(
        None, "--thread", help="Thread ID to resume an interrupted session"
    ),
) -> None:
    """Generate a tailored resume PDF for a target job."""
    if jd_file:
        jd_text = jd_file.read_text(encoding="utf-8").strip()

    if not jd_text and not jd_url:
        print_error(
            "Provide --jd-text, --jd-file, or --jd-url.",
            hint="Example: resume-generator generate --jd-file job.txt",
        )
        raise typer.Exit(1)

    settings = _load_settings_or_exit()

    if provider:
        settings = settings.model_copy(update={"provider": provider})
    if model_name:
        model_cfg = settings.model.model_copy(update={"default": model_name})
        settings = settings.model_copy(update={"model": model_cfg})

    _check_base_resume_or_exit()
    print_banner(provider=settings.provider, model=settings.model.default)
    settings = _ensure_llm_ready(settings)

    t_id = thread_id or str(uuid.uuid4())
    initial_state: ResumeGenState = {
        "schema_version": STATE_SCHEMA_VERSION,
        "input_type": "url" if jd_url else "text",
        "raw_input": (jd_url or jd_text or "").strip(),
        "latex_errors": [],
        "pdf_errors": [],
        "page_images": [],
        "hitl_answers": {},
        "approved_suggestion_ids": [],
        "suggestions": [],
        "generator_retries": 0,
        "validation_passed": False,
        "messages": [],
    }

    config = {"configurable": {"thread_id": t_id}}
    console.print(f"[muted]Session thread ID: {t_id}[/muted]")
    console.print(
        f"[muted](To resume if interrupted: resume-generator resume {t_id})[/muted]\n"
    )

    start_time = time.perf_counter()

    with get_checkpointer() as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        final_state = _run_with_hitl(graph, initial_state, config)

    elapsed = time.perf_counter() - start_time
    final_pdf = final_state.get("final_pdf_path") if final_state else None

    if final_pdf:
        jd = final_state.get("jd")
        resume = final_state.get("tailored_resume") or final_state.get("base_resume")
        final_pdf = _prompt_save_and_open(final_pdf)
        print_final_summary(
            company=jd.company if jd else "Unknown",
            role=jd.role_title if jd else "Unknown",
            pdf_path=final_pdf,
            elapsed=elapsed,
            retries=max(0, (final_state.get("generator_retries") or 1) - 1),
        )
    elif final_state and final_state.get("scrape_error"):
        print_error_panel(
            "Scraping Failed",
            final_state["scrape_error"],
            hint="Try pasting the job description directly: --jd-text '...'",
        )
        raise typer.Exit(1)
    else:
        raise typer.Exit(3)


# ══════════════════════════════════════════════════════════════════════════════
#  resume
# ══════════════════════════════════════════════════════════════════════════════

@app.command(name="resume")
def resume_session(
    thread_id: str = typer.Argument(..., help="Thread ID of the paused session"),
) -> None:
    """Resume a paused Human-in-the-Loop session."""
    settings = _load_settings_or_exit()
    print_banner(provider=settings.provider, model=settings.model.default)
    settings = _ensure_llm_ready(settings)

    config = {"configurable": {"thread_id": thread_id}}
    console.print(f"[muted]Resuming session: {thread_id}[/muted]\n")

    start_time = time.perf_counter()

    with get_checkpointer() as checkpointer:
        graph = build_graph(checkpointer=checkpointer)

        state = graph.get_state(config)
        if not state.values:
            print_error(
                f"No session found with thread ID: {thread_id}",
                hint="Run 'resume-generator generate' to start a new session.",
            )
            raise typer.Exit(1)

        stored_version = state.values.get("schema_version", 0)
        if stored_version != STATE_SCHEMA_VERSION:
            print_error(
                f"Checkpoint schema mismatch (stored v{stored_version}, current v{STATE_SCHEMA_VERSION}).",
                hint="Start a new session: resume-generator generate ...",
            )
            raise typer.Exit(1)

        if not state.next:
            print_info("This session has already completed.")
            final_pdf = state.values.get("final_pdf_path")
            if final_pdf:
                print_success(f"Output: {final_pdf}")
            raise typer.Exit(0)

        final_state = _run_with_hitl(graph, None, config)

    elapsed = time.perf_counter() - start_time
    final_pdf = final_state.get("final_pdf_path") if final_state else None

    if final_pdf:
        jd = final_state.get("jd")
        final_pdf = _prompt_save_and_open(final_pdf)
        print_final_summary(
            company=jd.company if jd else "Unknown",
            role=jd.role_title if jd else "Unknown",
            pdf_path=final_pdf,
            elapsed=elapsed,
            retries=max(0, (final_state.get("generator_retries") or 1) - 1),
        )
    else:
        raise typer.Exit(3)


# ══════════════════════════════════════════════════════════════════════════════
#  config
# ══════════════════════════════════════════════════════════════════════════════

config_app = typer.Typer(help="Manage resume-generator configuration.")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    """Show current configuration."""
    settings = ResumeAgentSettings.load()
    data = settings.model_dump(exclude={"anthropic_api_key", "openai_api_key", "gemini_api_key", "nvidia_api_key"})
    console.print(Panel(yaml.dump(data, default_flow_style=False), title="[accent]Config[/accent]"))
    console.print(f"[muted]Config file: {CONFIG_FILE}[/muted]")
    console.print(f"[muted]Base resume: {BASE_RESUME_FILE}[/muted]")


@config_app.command("set")
def config_set(key: str = typer.Argument(...), value: str = typer.Argument(...)) -> None:
    """Set a configuration value. Example: config set provider openai"""
    settings = ResumeAgentSettings.load()
    parts = key.split(".")
    data = settings.model_dump(exclude={"anthropic_api_key", "openai_api_key", "gemini_api_key", "nvidia_api_key"})

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
    ok = perform_update()
    if ok:
        print_success(
            "Updated successfully!\n"
            "Restart [bold]resume-generator[/bold] to use the new version."
        )
    else:
        print_error(
            "Update failed.\n"
            "Try manually:\n"
            f"  cd \"{repo}\"\n"
            "  git pull\n"
            "  uv tool install . --force"
        )
        raise typer.Exit(1)


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

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
    from .schemas import GapAnalysis, Suggestion

    def _coerce(raw) -> list:
        if not raw:
            return []
        out = []
        for s in raw:
            if isinstance(s, dict):
                try:
                    out.append(Suggestion.model_validate(s))
                except Exception:
                    pass
            elif hasattr(s, "id") and hasattr(s, "before"):
                out.append(s)
        return out

    # Primary: suggestions field
    result = _coerce(state_values.get("suggestions"))
    if result:
        return result

    # Fallback: gap_analysis.tailoring_ideas (survives checkpoint round-trips
    # better because GapAnalysis is a richer object that LangGraph can fully
    # reconstruct even when suggestions is lost or empty after deserialization)
    gap = state_values.get("gap_analysis")
    if gap is None:
        return []
    if isinstance(gap, dict):
        try:
            gap = GapAnalysis.model_validate(gap)
        except Exception:
            return _coerce(gap.get("tailoring_ideas", []))
    if hasattr(gap, "tailoring_ideas"):
        return _coerce(gap.tailoring_ideas)
    return []


# Registry: add a new HITL node by adding one entry here.
_HITL_HANDLERS = {
    HITL_MISSING_NODE: _handle_hitl_missing,
    HITL_SUGGESTIONS_NODE: _handle_hitl_suggestions,
}


def _run_with_hitl(graph, initial_input, config: dict) -> dict | None:
    """
    Run the graph, handling interrupt_before pauses for HITL via a handler registry.
    """
    current_input = initial_input
    max_hitl_rounds = 10

    for _ in range(max_hitl_rounds):
        try:
            graph.invoke(current_input, config=config)
        except Exception as exc:
            _handle_graph_error(exc)
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


def _handle_graph_error(exc: Exception) -> None:
    """
    Translate known LLM/provider errors into friendly panels, then exit.
    Re-raises for anything we don't recognise so the normal traceback appears.
    """
    exc_type = type(exc).__name__
    exc_msg = str(exc)

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

    console.print("[muted]Checking LLM connection…[/muted] ", end="")
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

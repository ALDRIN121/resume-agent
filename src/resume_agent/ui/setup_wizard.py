"""
Interactive first-time configuration wizard.

Called automatically when `resume-generator` is run without a subcommand and
no config exists. Also callable explicitly via `resume-generator setup`.

The wizard is deliberately skipped if the provider is already configured —
it only fires when config is missing or when the user explicitly asks for it.
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Optional

import questionary
from questionary import Choice, Style as QStyle

from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table

_Q_STYLE = QStyle([
    ("qmark",        "fg:cyan bold"),
    ("question",     "bold"),
    ("answer",       "fg:cyan bold"),
    ("pointer",      "fg:cyan bold"),
    ("highlighted",  "fg:cyan bold"),
    ("selected",     "fg:cyan"),
    ("separator",    "fg:grey"),
    ("instruction",  "fg:grey italic"),
])

from ..config import (
    CONFIG_DIR,
    CONFIG_FILE,
    ModelConfig,
    ResumeAgentSettings,
    SECRETS_FILE,
)
from .console import console
from .panels import print_error, print_info, print_success, print_warning


# ── Provider / model catalogues ────────────────────────────────────────────────

# (provider_id, display_label, description, is_remote_ollama)
_PROVIDERS: list[tuple[str, str, str, bool]] = [
    ("gemini",    "Gemini (Google)",   "Free tier · aistudio.google.com/apikey",  False),
    ("nvidia",    "NVIDIA NIM",        "Free tier · build.nvidia.com",            False),
    ("ollama",    "Ollama — local",    "Free, no internet required",              False),
    ("ollama",    "Ollama — remote",   "Self-hosted server or cloud endpoint",    True),
    ("anthropic", "Anthropic Claude",  "Paid · console.anthropic.com",            False),
    ("openai",    "OpenAI GPT",        "Paid · platform.openai.com/api-keys",     False),
]

_MODELS: dict[str, list[str]] = {
    "gemini":    ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp", "gemini-1.5-flash"],
    "nvidia":    ["meta/llama-3.1-70b-instruct", "nvidia/llama-3.1-nemotron-70b-instruct", "meta/llama-3.3-70b-instruct", "mistralai/mixtral-8x7b-instruct-v0.1"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
    "openai":    ["gpt-4o", "gpt-4o-mini", "o1-mini", "gpt-3.5-turbo"],
    "ollama":    ["llama3.2", "gemma2", "mistral", "qwen2.5", "phi3", "codellama"],
}

_VISION: dict[str, list[str]] = {
    "gemini":    ["gemini-2.0-flash", "gemini-1.5-pro"],
    "nvidia":    ["meta/llama-3.2-11b-vision-instruct", "microsoft/phi-3.5-vision-instruct"],
    "anthropic": ["claude-opus-4-6", "claude-sonnet-4-6"],
    "openai":    ["gpt-4o"],
    "ollama":    ["llava", "llava:13b", "llava:34b"],
}

_KEY_ENV: dict[str, str] = {
    "gemini":    "GOOGLE_API_KEY",
    "nvidia":    "NVIDIA_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai":    "OPENAI_API_KEY",
}

_KEY_URL: dict[str, str] = {
    "gemini":    "aistudio.google.com/apikey",
    "nvidia":    "build.nvidia.com",
    "anthropic": "console.anthropic.com",
    "openai":    "platform.openai.com/api-keys",
}


# ── Public entry point ─────────────────────────────────────────────────────────

def run_setup_wizard(existing: Optional[ResumeAgentSettings] = None) -> ResumeAgentSettings:
    """
    Run the interactive provider-setup wizard.

    Prompts for: provider → credentials → text model → vision model → saves & tests.
    Only completes (and saves) when the LLM connection test passes.
    Returns the saved ResumeAgentSettings so the caller can continue with it.
    """
    console.print()
    console.print(Rule("[bold blue]  Provider Setup  [/bold blue]", style="blue"))
    console.print()

    # Step 1 — provider (asked once; the retry loop only re-asks credentials onward)
    provider, is_remote = _ask_provider(existing)

    while True:
        # Step 2 — credentials (API key or Ollama URL)
        api_key, base_url = _ask_credentials(provider, is_remote, existing)

        # Step 3 — text / reasoning model
        default_model = _ask_model(
            provider,
            label="text model",
            candidates=_MODELS.get(provider, []),
            fallback=existing.model.default if existing else None,
            base_url=base_url,
            api_key=api_key,
        )

        # Step 4 — vision model (optional)
        vision_enabled, vision_model = _ask_vision(
            provider, default_model, existing,
            base_url=base_url, api_key=api_key,
        )

        # Step 5 — build, test, persist
        result = _apply_and_save(
            existing=existing,
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            default_model=default_model,
            vision_model=vision_model if vision_enabled else default_model,
        )

        if result is not None:
            return result

        # LLM test failed — offer retry before giving up
        console.print()
        retry = Confirm.ask(
            "  [accent]Retry with different credentials?[/accent]",
            console=console,
            default=True,
        )
        if not retry:
            raise SystemExit(1)


# ── Step helpers ───────────────────────────────────────────────────────────────

def _ask_provider(existing: Optional[ResumeAgentSettings]) -> tuple[str, bool]:
    """Arrow-key provider selection. Returns (provider_id, is_remote_ollama)."""
    default_idx = 0
    if existing:
        for i, (pid, _, _, _) in enumerate(_PROVIDERS):
            if pid == existing.provider:
                default_idx = i
                break

    choices = [
        Choice(title=f"{label:<22} {desc}", value=i)
        for i, (_, label, desc, _) in enumerate(_PROVIDERS)
    ]

    idx = questionary.select(
        "Choose LLM provider",
        choices=choices,
        default=choices[default_idx],
        instruction="(↑ ↓ to navigate, Enter to select)",
        style=_Q_STYLE,
    ).ask()

    if idx is None:
        raise SystemExit(0)

    pid, label, _, is_remote = _PROVIDERS[idx]
    print_success(f"Provider: [bold]{label}[/bold]")
    return pid, is_remote


def _ask_credentials(
    provider: str,
    is_remote: bool,
    existing: Optional[ResumeAgentSettings],
) -> tuple[Optional[str], str]:
    """
    Ask for API key (keyed providers) or Ollama URL (ollama).
    Returns (api_key_or_None, ollama_base_url).
    """
    console.print()
    api_key: Optional[str] = None
    base_url = "http://localhost:11434"

    if provider in _KEY_ENV:
        env_var = _KEY_ENV[provider]
        url = _KEY_URL[provider]

        # Check if a key is already in the environment / existing settings
        existing_key = (
            os.environ.get(env_var)
            or (existing.gemini_api_key    if provider == "gemini"    and existing else None)
            or (existing.nvidia_api_key    if provider == "nvidia"    and existing else None)
            or (existing.anthropic_api_key if provider == "anthropic" and existing else None)
            or (existing.openai_api_key    if provider == "openai"    and existing else None)
        )

        if existing_key:
            masked = existing_key[:8] + "…" if len(existing_key) > 8 else existing_key
            keep = Confirm.ask(
                f"  [accent]Keep existing {env_var}[/accent] ({masked})?",
                console=console,
                default=True,
            )
            if keep:
                return existing_key, base_url

        console.print(f"  [muted]Get your key at:[/muted] [link]{url}[/link]")
        entered = Prompt.ask(
            f"  [accent]{env_var}[/accent]",
            console=console,
            password=True,
        ).strip()

        if entered:
            _write_secret(env_var, entered)
            os.environ[env_var] = entered   # available for this process immediately
            api_key = entered
            print_success(f"{env_var} saved → [cyan]{SECRETS_FILE}[/cyan]")
        else:
            print_warning(f"No key entered. Set later: export {env_var}=…")

    elif provider == "ollama":
        if is_remote:
            console.print("[muted]Enter the Ollama server base URL.[/muted]")
            default_url = existing.ollama_base_url if existing else "http://my-server:11434"
            base_url = Prompt.ask(
                "  [accent]Base URL[/accent]",
                console=console,
                default=default_url,
            ).strip().rstrip("/")

            # Determine whether this is a cloud / non-local endpoint
            _parsed = urllib.parse.urlparse(base_url)
            _host = (_parsed.hostname or "").lower()
            _is_local = _host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or _host.endswith(".local")

            if _is_local:
                console.print("[muted]API key for this server? (leave blank if none)[/muted]")
                remote_key = Prompt.ask(
                    "  [accent]API key (optional)[/accent]",
                    console=console,
                    password=True,
                    default="",
                ).strip()
            else:
                # Cloud / remote endpoint — API key is required
                console.print("[muted]API key required for cloud/remote Ollama endpoints.[/muted]")
                remote_key = ""
                while not remote_key:
                    remote_key = Prompt.ask(
                        "  [accent]API key[/accent]",
                        console=console,
                        password=True,
                    ).strip()
                    if not remote_key:
                        print_error("An API key is required for remote/cloud Ollama endpoints.")

            if remote_key:
                _write_secret("OLLAMA_API_KEY", remote_key)
                os.environ["OLLAMA_API_KEY"] = remote_key
                api_key = remote_key
                print_success("Ollama API key saved.")
        else:
            base_url = existing.ollama_base_url if existing else "http://localhost:11434"

    return api_key, base_url


def _ask_model(
    provider: str,
    label: str,
    candidates: list[str],
    *,
    fallback: Optional[str],
    base_url: str = "http://localhost:11434",
    api_key: Optional[str] = None,
) -> str:
    """Arrow-key model selection, returns the chosen model name."""
    console.print()

    if provider == "ollama":
        live = _fetch_ollama_models(base_url, api_key=api_key)
        if live:
            candidates = live

    _CUSTOM = "__custom__"
    choices = [
        Choice(title=f"{name}  (recommended)" if i == 0 else name, value=name)
        for i, name in enumerate(candidates)
    ] + [Choice(title="Enter a custom model name…", value=_CUSTOM)]

    default_choice = choices[0]
    if fallback and fallback in candidates:
        default_choice = choices[candidates.index(fallback)]

    result = questionary.select(
        label,
        choices=choices,
        default=default_choice,
        instruction="(↑ ↓ to navigate, Enter to select)",
        style=_Q_STYLE,
    ).ask()

    if result is None:
        raise SystemExit(0)

    if result == _CUSTOM:
        model = Prompt.ask("  [accent]Model name[/accent]", console=console).strip()
        if not model:
            model = candidates[0] if candidates else "default"
    else:
        model = result

    print_success(f"Model: [bold]{model}[/bold]")
    return model


def _ask_vision(
    provider: str,
    default_model: str,
    existing: Optional[ResumeAgentSettings],
    *,
    base_url: str = "http://localhost:11434",
    api_key: Optional[str] = None,
) -> tuple[bool, str]:
    """Ask whether to enable PDF vision validation and choose the model."""
    console.print()
    console.print(
        Panel(
            "[bold]Vision Validation[/bold]\n"
            "[muted]A multimodal model inspects the PDF layout after generation,\n"
            "catching formatting issues like overlapping text or cut-off sections.[/muted]",
            border_style="blue",
            padding=(0, 2),
        )
    )

    enabled = Confirm.ask(
        "  [accent]Enable vision validation?[/accent]",
        console=console,
        default=True,
    )
    if not enabled:
        return False, default_model

    vision_candidates = _VISION.get(provider, [default_model])
    existing_vision = existing.model.vision if existing else vision_candidates[0]

    vision_model = _ask_model(
        provider,
        label="vision model",
        candidates=vision_candidates,
        fallback=existing_vision,
        base_url=base_url,
        api_key=api_key,
    )
    return True, vision_model


def _apply_and_save(
    *,
    existing: Optional[ResumeAgentSettings],
    provider: str,
    api_key: Optional[str],
    base_url: str,
    default_model: str,
    vision_model: str,
) -> Optional[ResumeAgentSettings]:
    """Build the settings object, run a live LLM test, then persist.

    Returns the saved settings on success, or None if the LLM test fails
    (in which case nothing is saved so the wizard can retry).
    """
    console.print()
    console.print(Rule("[dim]Testing connection…[/dim]", style="dim"))
    console.print()

    # Start from existing non-secret settings (or defaults)
    base: dict = {}
    if existing:
        base = existing.model_dump(
            exclude={"anthropic_api_key", "openai_api_key", "gemini_api_key", "nvidia_api_key", "ollama_api_key"}
        )
    base.update({
        "provider": provider,
        "model": {"default": default_model, "vision": vision_model},
        "ollama_base_url": base_url,
    })
    settings = ResumeAgentSettings(**base)

    # Inject the API key into the in-process object so _test_llm can use it
    if provider == "gemini" and api_key:
        settings = settings.model_copy(update={"gemini_api_key": api_key})
    elif provider == "nvidia" and api_key:
        settings = settings.model_copy(update={"nvidia_api_key": api_key})
    elif provider == "anthropic" and api_key:
        settings = settings.model_copy(update={"anthropic_api_key": api_key})
    elif provider == "openai" and api_key:
        settings = settings.model_copy(update={"openai_api_key": api_key})
    elif provider == "ollama" and api_key:
        settings = settings.model_copy(update={"ollama_api_key": api_key})

    ok = _test_llm(settings)
    if not ok:
        print_error("LLM test failed — config not saved. Fix your credentials and try again.")
        return None

    settings.save()
    console.print()
    print_success(f"Config saved → [cyan]{CONFIG_FILE}[/cyan]")
    console.print()

    return settings


# ── Utilities ──────────────────────────────────────────────────────────────────

def _test_llm(settings: ResumeAgentSettings) -> bool:
    """Do a minimal LLM invoke to verify credentials and connectivity."""
    from ..llm import get_chat_model
    try:
        llm = get_chat_model(settings, task="default", temperature=0.0)
        resp = llm.invoke("Reply with the single word: OK")
        snippet = str(resp.content).strip()[:60]
        print_success(f"Connected — [dim]{snippet}[/dim]")
        return True
    except Exception as exc:
        print_error(f"Connection failed: {exc}")
        return False


def _fetch_ollama_models(base_url: str, *, api_key: Optional[str] = None) -> list[str]:
    """Query Ollama /api/tags to get the list of installed models."""
    try:
        import httpx
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = httpx.get(f"{base_url}/api/tags", timeout=4, headers=headers)
        if resp.status_code == 200:
            return [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        pass
    return []


def _write_secret(key: str, value: str) -> None:
    """Write/update a KEY=value line in ~/.resume_generator/.env (chmod 600)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines: dict[str, str] = {}
    if SECRETS_FILE.exists():
        for raw in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if "=" in raw and not raw.startswith("#"):
                k, v = raw.split("=", 1)
                lines[k.strip()] = v.strip()
    lines[key] = value
    SECRETS_FILE.write_text(
        "\n".join(f"{k}={v}" for k, v in lines.items()) + "\n",
        encoding="utf-8",
    )
    try:
        SECRETS_FILE.chmod(0o600)
    except OSError:
        pass  # Windows doesn't support chmod

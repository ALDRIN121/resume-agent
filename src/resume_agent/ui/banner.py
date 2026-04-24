"""Startup banner displayed when the CLI launches."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from resume_agent import __version__
from .console import console

_LOGO = """\
 ██████╗ ███████╗███████╗██╗   ██╗███╗   ███╗███████╗
 ██╔══██╗██╔════╝██╔════╝██║   ██║████╗ ████║██╔════╝
 ██████╔╝█████╗  ███████╗██║   ██║██╔████╔██║█████╗
 ██╔══██╗██╔══╝  ╚════██║██║   ██║██║╚██╔╝██║██╔══╝
 ██║  ██║███████╗███████║╚██████╔╝██║ ╚═╝ ██║███████╗
 ╚═╝  ╚═╝╚══════╝╚══════╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝
       A G E N T"""


def print_banner(
    provider: str = "anthropic",
    model: str = "",
    source_dir: Optional[Path] = None,
) -> None:
    """Print the startup banner — two-column layout with info and quick-start tips."""
    from resume_agent.config import BASE_RESUME_FILE, SOURCE_DIR

    if source_dir is None:
        source_dir = SOURCE_DIR

    user_name = _get_user_name(BASE_RESUME_FILE)
    source_pdf = _get_source_pdf(source_dir)
    last_updated = _get_last_updated(BASE_RESUME_FILE)
    recent = _get_recent_resumes()

    model_info = f" / {model}" if model else ""

    # ── Left column: logo + welcome + status ─────────────────────────────────
    left = Text()
    left.append(_LOGO + "\n", style="bold blue")

    if user_name:
        left.append("\n  Welcome back, ", style="dim white")
        left.append(user_name, style="bold white")
        left.append("!\n", style="bold white")
    else:
        left.append("\n  Welcome to Resume Agent!\n", style="bold white")

    left.append(f"\n  ◆  {provider}{model_info}\n", style="dim cyan")

    if source_pdf:
        left.append(f"  ◆  {source_pdf}\n", style="dim white")
    else:
        left.append("  ◆  No resume  →  resume-generator init\n", style="dim yellow")

    if last_updated:
        left.append(f"  ◆  Last updated: {last_updated}\n", style="dim white")

    # ── Right column: quick start + recent resumes ────────────────────────────
    right = Text()
    right.append("Quick Start\n", style="bold cyan")
    right.append("─" * 24 + "\n", style="dim")
    for cmd, desc in [
        ("init    ", "Parse your PDF"),
        ("generate", "Create a resume"),
        ("doctor  ", "Check tools"),
        ("setup   ", "Change provider"),
    ]:
        right.append(f"  {cmd}  ", style="bold")
        right.append(f"{desc}\n", style="dim")

    if recent:
        right.append("\nRecent Resumes\n", style="bold cyan")
        right.append("─" * 24 + "\n", style="dim")
        for company, role_hint, age in recent[:3]:
            right.append(f"  {age:<8}", style="dim")
            right.append(f"  {company}", style="bold")
            if role_hint:
                right.append(f"  ·  {role_hint}", style="dim")
            right.append("\n")

    # ── Two-column grid ───────────────────────────────────────────────────────
    grid = Table.grid(padding=(0, 2), expand=True)
    grid.add_column(ratio=3)
    grid.add_column(ratio=2, vertical="top")
    grid.add_row(left, right)

    panel = Panel(
        grid,
        title=f"[bold blue]  Resume Agent  v{__version__}  [/bold blue]",
        border_style="blue",
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    console.print()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_user_name(base_resume_file: Path) -> Optional[str]:
    """Read full_name from the parsed base resume YAML."""
    try:
        import yaml
        if base_resume_file.exists():
            data = yaml.safe_load(base_resume_file.read_text(encoding="utf-8")) or {}
            personal = data.get("personal", {})
            return personal.get("full_name") or personal.get("name")
    except Exception:
        pass
    return None


def _get_source_pdf(source_dir: Path) -> Optional[str]:
    """Return the filename of the first PDF/TEX in the source folder."""
    try:
        candidates = sorted(source_dir.glob("*.pdf")) + sorted(source_dir.glob("*.tex"))
        if candidates:
            return candidates[0].name
    except Exception:
        pass
    return None


def _get_last_updated(base_resume_file: Path) -> Optional[str]:
    """Return a human-readable age of the base resume YAML."""
    try:
        if not base_resume_file.exists():
            return None
        elapsed = time.time() - base_resume_file.stat().st_mtime
        if elapsed < 60:
            return "just now"
        if elapsed < 3600:
            return f"{int(elapsed / 60)}m ago"
        if elapsed < 86400:
            return f"{int(elapsed / 3600)}h ago"
        return f"{int(elapsed / 86400)}d ago"
    except Exception:
        return None


def _get_recent_resumes() -> list[tuple[str, str, str]]:
    """
    Scan ./output/ for recently generated PDFs.
    Returns list of (company, role_hint, age_string).
    Filename format: aldrin-joseph_kone_2026-04-16.pdf → company = "KONE"
    """
    try:
        output_dir = Path("output")
        if not output_dir.exists():
            return []
        pdfs = sorted(
            output_dir.rglob("*.pdf"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        result = []
        for pdf in pdfs[:4]:
            elapsed = time.time() - pdf.stat().st_mtime
            if elapsed < 3600:
                age = f"{int(elapsed / 60)}m ago"
            elif elapsed < 86400:
                age = f"{int(elapsed / 3600)}h ago"
            else:
                age = f"{int(elapsed / 86400)}d ago"
            # Parse company from "firstname-lastname_company_date.pdf"
            parts = pdf.stem.split("_")
            company = parts[1].upper() if len(parts) > 1 else pdf.stem
            role_hint = ""
            result.append((company, role_hint, age))
        return result
    except Exception:
        return []

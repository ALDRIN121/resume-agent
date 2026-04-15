"""Rich panel and status helpers for consistent CLI output."""

from __future__ import annotations

from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .console import console


def print_section(title: str) -> None:
    """Print a section rule."""
    console.print(Rule(f"[accent]{title}[/accent]", style="blue"))


def print_success(message: str) -> None:
    console.print(f"[success]✓[/success] {message}")


def print_error(message: str, hint: str = "") -> None:
    console.print(f"[error]✗[/error] {message}")
    if hint:
        console.print(f"  [muted]→ {hint}[/muted]")


def print_warning(message: str) -> None:
    console.print(f"[warning]![/warning] {message}")


def print_info(message: str) -> None:
    console.print(f"[info]·[/info] {message}")


def print_phase(phase: str, status: str = "running") -> None:
    """Print a phase status update."""
    icons = {"running": "⏳", "done": "✓", "fail": "✗", "skip": "–"}
    icon = icons.get(status, "·")
    style_map = {"running": "phase", "done": "success", "fail": "error", "skip": "muted"}
    style = style_map.get(status, "info")
    console.print(f"[{style}]{icon}[/{style}] [bold]{phase}[/bold]")


def print_final_summary(
    company: str,
    role: str,
    pdf_path: str,
    elapsed: float,
    retries: int,
) -> None:
    """Print a success summary panel at the end."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="muted", no_wrap=True)
    table.add_column()

    table.add_row("Company:", f"[bold]{company}[/bold]")
    table.add_row("Role:", role)
    table.add_row("Output:", f"[cyan]{pdf_path}[/cyan]")
    table.add_row("Time:", f"{elapsed:.1f}s")
    if retries > 0:
        table.add_row("Retries:", f"[warning]{retries}[/warning]")

    panel = Panel(
        table,
        title="[success]Resume Generated[/success]",
        border_style="green",
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    console.print()


def print_error_panel(title: str, body: str, hint: str = "") -> None:
    """Print a formatted error panel."""
    text = Text(body)
    if hint:
        text.append(f"\n\n→ {hint}", style="muted")
    panel = Panel(text, title=f"[error]{title}[/error]", border_style="red", padding=(1, 2))
    console.print()
    console.print(panel)
    console.print()

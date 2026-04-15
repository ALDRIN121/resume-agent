"""Rich-based interactive prompts for Human-in-the-Loop interactions."""

from __future__ import annotations

from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from .console import console
from ..schemas import Question, Suggestion


def prompt_hitl_questions(questions: list[Question]) -> dict[str, str]:
    """
    Present HITL questions to the user one at a time.
    Returns dict mapping question_id -> user answer.
    """
    console.print()
    console.print(
        Panel(
            "[bold]The agent needs a few details not found in your base resume.[/bold]\n"
            "[muted]Answer honestly — the agent will never fabricate experience.[/muted]",
            title="[hitl]Human Input Needed[/hitl]",
            border_style="yellow",
            padding=(1, 2),
        )
    )
    console.print()

    answers: dict[str, str] = {}
    for i, q in enumerate(questions, 1):
        console.print(
            Panel(
                Text.assemble(
                    Text(f"Q{i}: ", style="bold yellow"),
                    Text(q.prompt + "\n", style="bold"),
                    Text(f"Why: {q.why_asking}", style="muted"),
                ),
                border_style="yellow",
                padding=(0, 2),
            )
        )
        answer = Prompt.ask(
            f"  [yellow]Your answer[/yellow]",
            console=console,
            default="",
        )
        answers[q.id] = answer.strip()
        console.print()

    return answers


def prompt_suggestions(suggestions: list[Suggestion]) -> list[str]:
    """
    Present tailoring suggestions as a table and let user approve/reject each.
    Returns list of approved suggestion IDs.
    """
    if not suggestions:
        console.print("[muted]No tailoring suggestions for this role.[/muted]")
        return []

    console.print()
    console.print(
        Panel(
            "[bold]The agent suggests the following resume tailoring:[/bold]\n"
            "[muted]These rewrite existing bullets to better match the job description.\n"
            "No new experience will be fabricated.[/muted]",
            title="[accent]Tailoring Suggestions[/accent]",
            border_style="blue",
            padding=(1, 2),
        )
    )
    console.print()

    table = Table(
        show_header=True,
        header_style="bold blue",
        box=None,
        padding=(0, 1),
    )
    table.add_column("#", style="bold", width=3)
    table.add_column("Section", style="cyan", width=12)
    table.add_column("Before", style="dim", max_width=35)
    table.add_column("After", style="green", max_width=35)
    table.add_column("Why", style="muted", max_width=25)

    for s in suggestions:
        section = s.section
        if s.role_company:
            section += f"\n[muted]{s.role_company}[/muted]"
        table.add_row(s.id, section, s.before, s.after, s.rationale)

    console.print(table)
    console.print()
    console.print(
        "[muted]Enter suggestion numbers to accept (comma-separated), "
        "[bold]a[/bold] for all, [bold]n[/bold] for none:[/muted]"
    )

    choice = Prompt.ask(
        "  [accent]Your selection[/accent]",
        console=console,
        default="a",
    ).strip().lower()

    if choice == "a":
        approved = [s.id for s in suggestions]
    elif choice == "n" or choice == "":
        approved = []
    else:
        # Parse comma-separated IDs
        parts = {p.strip() for p in choice.replace(" ", ",").split(",")}
        valid_ids = {s.id for s in suggestions}
        approved = [sid for sid in parts if sid in valid_ids]

    console.print()
    if approved:
        console.print(f"[success]✓[/success] Accepted {len(approved)} suggestion(s).")
    else:
        console.print("[muted]No suggestions applied — using base resume content.[/muted]")
    console.print()

    return approved


def prompt_resume_feedback() -> str:
    """Ask user for free-text feedback when regenerating suggestions."""
    return Prompt.ask(
        "  [yellow]What should be different?[/yellow]",
        console=console,
        default="",
    ).strip()


def confirm(message: str, default: bool = True) -> bool:
    """Simple yes/no confirmation."""
    suffix = "[Y/n]" if default else "[y/N]"
    answer = Prompt.ask(f"  {message} {suffix}", console=console, default="").strip().lower()
    if answer == "":
        return default
    return answer in {"y", "yes"}

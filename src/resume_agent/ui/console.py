"""Singleton Rich console used across the entire application."""

from rich.console import Console
from rich.theme import Theme

_THEME = Theme(
    {
        "success": "bold green",
        "error": "bold red",
        "warning": "bold yellow",
        "info": "bold cyan",
        "muted": "dim white",
        "accent": "bold blue",
        "phase": "bold magenta",
        "hitl": "bold yellow",
    }
)

console = Console(theme=_THEME, highlight=False)
err_console = Console(stderr=True, theme=_THEME, highlight=False)

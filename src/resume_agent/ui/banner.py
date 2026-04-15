"""Startup banner displayed when the CLI launches."""

from rich.align import Align
from rich.panel import Panel
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


def print_banner(provider: str = "anthropic", model: str = "") -> None:
    """Print the startup banner with version and provider info."""
    logo_text = Text(_LOGO, style="bold blue")
    model_info = f" / {model}" if model else ""
    subtitle = Text(
        f"\n  AI-powered resume generator  ·  v{__version__}  ·  {provider}{model_info}",
        style="dim cyan",
    )
    content = Text.assemble(logo_text, subtitle)
    panel = Panel(
        Align.center(content),
        border_style="blue",
        padding=(0, 2),
    )
    console.print()
    console.print(panel)
    console.print()

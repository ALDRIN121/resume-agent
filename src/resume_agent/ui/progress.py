"""Phase-aware progress tracking using Rich."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator

from rich.console import Console
from rich.spinner import Spinner
from rich.status import Status

from .console import console

PHASES = [
    "Scraping job description",
    "Extracting structured JD",
    "Loading base resume",
    "Analyzing gaps",
    "Human review",
    "Applying suggestions",
    "Generating LaTeX",
    "Compiling PDF",
    "Validating layout",
    "Saving output",
]


@contextmanager
def phase_spinner(description: str, console: Console = console) -> Generator[None, None, None]:
    """Context manager that shows a spinner while a phase runs."""
    with Status(
        f"[phase]{description}...[/phase]",
        console=console,
        spinner="dots",
    ) as status:
        start = time.perf_counter()
        try:
            yield
            elapsed = time.perf_counter() - start
            console.print(f"[success]✓[/success] {description} [muted]({elapsed:.1f}s)[/muted]")
        except Exception:
            elapsed = time.perf_counter() - start
            console.print(f"[error]✗[/error] {description} [muted]({elapsed:.1f}s)[/muted]")
            raise

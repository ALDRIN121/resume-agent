"""Phase-aware progress tracking using Rich."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Generator

from rich.console import Console
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
    """
    Context manager that shows a spinner with a live elapsed-time counter.

    The status line updates every second:
      ⠋ Extracting text from resume…  3s
    On success: ✓ description  (3.2s)
    On failure: ✗ description  (3.2s)
    """
    with Status("", console=console, spinner="dots", refresh_per_second=4) as status:
        start = time.perf_counter()
        stop_event = threading.Event()

        def _tick() -> None:
            while not stop_event.wait(1.0):
                elapsed = time.perf_counter() - start
                status.update(
                    f"[phase]{description}[/phase]  [muted]{elapsed:.0f}s[/muted]"
                )

        status.update(f"[phase]{description}[/phase]")
        ticker = threading.Thread(target=_tick, daemon=True)
        ticker.start()

        try:
            yield
        except Exception:
            stop_event.set()
            ticker.join(timeout=1.0)
            elapsed = time.perf_counter() - start
            console.print(
                f"[error]✗[/error] {description}  [muted]({elapsed:.1f}s)[/muted]"
            )
            raise
        else:
            stop_event.set()
            ticker.join(timeout=1.0)
            elapsed = time.perf_counter() - start
            console.print(
                f"[success]✓[/success] {description}  [muted]({elapsed:.1f}s)[/muted]"
            )

"""SQLite checkpointer for LangGraph — enables HITL resume across sessions."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from langgraph.checkpoint.sqlite import SqliteSaver

from .config import CONFIG_DIR, STATE_DB


@contextmanager
def get_checkpointer() -> Generator[SqliteSaver, None, None]:
    """
    Context manager returning a SqliteSaver checkpointer.
    Creates ~/.resume_agent/ if it doesn't exist.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(STATE_DB)) as checkpointer:
        yield checkpointer

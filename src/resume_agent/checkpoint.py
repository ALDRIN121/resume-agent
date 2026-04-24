"""SQLite checkpointer for LangGraph — enables HITL resume across sessions."""

from __future__ import annotations

import logging
import warnings
from contextlib import contextmanager
from typing import Generator

from langgraph.checkpoint.sqlite import SqliteSaver

from .config import CONFIG_DIR, STATE_DB

# Suppress noisy "Deserializing unregistered type" warnings from LangGraph's
# msgpack serializer. Our Pydantic schemas are stored as-is in checkpoints;
# LangGraph can restore them correctly — the warning is purely informational.
logging.getLogger("langgraph.checkpoint.serde.msgpack").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message="Deserializing unregistered type.*")


@contextmanager
def get_checkpointer() -> Generator[SqliteSaver, None, None]:
    """
    Context manager returning a SqliteSaver checkpointer.
    Creates ~/.resume_generator/ if it doesn't exist.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(STATE_DB)) as checkpointer:
        yield checkpointer

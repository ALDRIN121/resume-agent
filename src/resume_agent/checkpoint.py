"""SQLite checkpointer for LangGraph — enables HITL resume across sessions."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .config import CONFIG_DIR, STATE_DB

# Persist the application schemas explicitly so interactive resumes remain usable
# when LangGraph enforces strict msgpack deserialization.
_CHECKPOINT_TYPES = tuple(
    ("resume_agent.schemas", name)
    for name in (
        "PersonalInfo", "Role", "Project", "Education", "Certification",
        "UserResume", "WorkPreferences", "JobDescription", "Question", "Suggestion", "GapAnalysis",
    )
)


@contextmanager
def get_checkpointer() -> Generator[SqliteSaver, None, None]:
    """
    Context manager returning a SqliteSaver checkpointer.
    Creates ~/.resume_generator/ if it doesn't exist.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(STATE_DB)) as checkpointer:
        checkpointer.serde = JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_TYPES)
        yield checkpointer


@asynccontextmanager
async def get_async_checkpointer() -> AsyncGenerator[AsyncSqliteSaver, None]:
    """
    Async context manager returning an AsyncSqliteSaver checkpointer.
    Used by the FastAPI/LangGraph streaming path.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(STATE_DB)) as checkpointer:
        checkpointer.serde = JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_TYPES)
        yield checkpointer

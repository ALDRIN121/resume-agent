"""SQLite checkpointer for LangGraph — enables HITL resume across sessions."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

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


def read_v2_checkpoint(path: Path, owner_kind: str, owner_id: str) -> dict | None:
    """Read JSON service state via LangGraph, without owning its SQL schema."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(path)) as saver:
        saved = saver.get_tuple(_v2_config(owner_kind, owner_id))
        return saved.checkpoint["channel_values"]["state"] if saved else None


def write_v2_checkpoint(path: Path, owner_kind: str, owner_id: str, state: dict) -> None:
    """Append an ordinary LangGraph checkpoint containing validated JSON only."""
    import json

    from langgraph.checkpoint.base import empty_checkpoint
    from pydantic import JsonValue, TypeAdapter

    from .contracts import canonical_json

    values = TypeAdapter(dict[str, JsonValue]).validate_python(state, strict=True)
    values = json.loads(canonical_json(values))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(path)) as saver:
        config = _v2_config(owner_kind, owner_id)
        previous = saver.get_tuple(config)
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"state": values}
        version = 1 if previous is None else previous.checkpoint["channel_versions"]["state"] + 1
        checkpoint["channel_versions"] = {"state": version}
        if previous:
            config = previous.config
        saver.put(config, checkpoint, {"source": "update", "step": version}, {"state": version})


def _v2_config(owner_kind: str, owner_id: str) -> dict:
    return {"configurable": {"thread_id": f"{owner_kind}:{owner_id}", "checkpoint_ns": "resume-agent-v2"}}

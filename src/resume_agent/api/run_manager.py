"""Single-user in-memory run orchestration for the FastAPI app."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

from langgraph.types import Command

from ..checkpoint import get_async_checkpointer
from ..config import CONFIG_DIR, ResumeAgentSettings
from ..graph import build_graph
from ..state import STATE_SCHEMA_VERSION, ResumeGenState
from .events import CompleteEvent, Event, FailedEvent, LogLineEvent, NodeEndEvent, NodeStartEvent, dump_event
from .streaming import StreamTranslator

_HISTORY_FILE = CONFIG_DIR / "run_history.jsonl"
_HISTORY_MAX_ENTRIES = 200

# Statuses after which a run will never publish another event. A subscriber that
# connects once a run is in one of these must be released, not left blocking.
_TERMINAL_STATUSES = frozenset({"complete", "failed", "cancelled"})


@dataclass
class RunSession:
    thread_id: str
    status: str = "queued"
    created_at: float = field(default_factory=perf_counter)
    started_wall_ts: float = field(default_factory=lambda: __import__("time").time())
    company: str = "Unknown"
    role: str = "Unknown"
    pdf_path: str | None = None
    error: str | None = None
    events: list[Event] = field(default_factory=list)
    subscribers: set[asyncio.Queue[Event | None]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None
    stored_duration_s: float | None = None  # set on completion; used for history replay

    def get_duration_s(self) -> float:
        if self.stored_duration_s is not None:
            return self.stored_duration_s
        return perf_counter() - self.created_at


class RunManager:
    """Holds local run sessions and bridges LangGraph to WebSockets."""

    def __init__(self) -> None:
        self._sessions: dict[str, RunSession] = {}
        self._lock = asyncio.Lock()
        self._load_history()

    async def start_run(self, jd_input: dict[str, Any]) -> RunSession:
        thread_id = str(uuid.uuid4())
        is_url = bool(jd_input.get("jd_url"))
        raw_input = (jd_input.get("jd_url") or jd_input.get("jd_text") or "").strip()
        initial_state: ResumeGenState = {
            "schema_version": STATE_SCHEMA_VERSION,
            "input_type": "url" if is_url else "text",
            "raw_input": raw_input,
            "latex_errors": [],
            "pdf_errors": [],
            "page_images": [],
            "suggestions": [],
            "generator_retries": 0,
            "validation_passed": False,
            "messages": [],
        }

        session = RunSession(thread_id=thread_id, status="running")
        async with self._lock:
            self._sessions[thread_id] = session
        session.task = asyncio.create_task(self._drive(session, initial_state))
        return session

    async def resume_run(self, thread_id: str, payload: dict[str, Any]) -> RunSession:
        session = self.get_run(thread_id)
        if session.task and not session.task.done():
            raise ValueError("Run is already active.")

        kind = payload.get("kind")
        body = payload.get("payload") or {}
        if kind == "ask_missing":
            resume_payload = {"answers": body.get("answers", body)}
        elif kind == "present_suggestions":
            resume_payload = {
                "approved_ids": body.get(
                    "approved_ids",
                    body.get("approved_suggestion_ids", []),
                )
            }
        else:
            resume_payload = body

        session.status = "running"
        session.task = asyncio.create_task(self._drive(session, Command(resume=resume_payload)))
        await self._publish(session, LogLineEvent(line="human input received; resuming graph"))
        return session

    async def subscribe(self, thread_id: str) -> AsyncIterator[Event]:
        session = self.get_run(thread_id)
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        for event in session.events:
            await queue.put(event)
        if session.status in _TERMINAL_STATUSES:
            # Run already finished — replay the history, then release. Don't
            # register as a live subscriber (it would block forever otherwise).
            await queue.put(None)
        else:
            session.subscribers.add(queue)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            session.subscribers.discard(queue)

    def get_run(self, thread_id: str) -> RunSession:
        try:
            return self._sessions[thread_id]
        except KeyError as exc:
            raise KeyError(f"No run found for thread ID {thread_id}") from exc

    def list_runs(self) -> list[RunSession]:
        return sorted(self._sessions.values(), key=lambda run: run.started_wall_ts, reverse=True)

    async def cancel(self, thread_id: str) -> RunSession:
        session = self.get_run(thread_id)
        if session.task and not session.task.done():
            session.task.cancel()
        session.status = "cancelled"
        session.stored_duration_s = session.get_duration_s()
        await self._publish(session, FailedEvent(reason="Run cancelled by user."))
        await self._close_subscribers(session)
        self._save_run(session)
        return session

    async def shutdown(self) -> None:
        """Cancel any in-flight graph runs (called on server shutdown)."""
        tasks = [s.task for s in self._sessions.values() if s.task and not s.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _drive(self, session: RunSession, graph_input: Any) -> None:
        settings = ResumeAgentSettings.load()
        config = _graph_config(session.thread_id, settings)
        translator = StreamTranslator()
        try:
            async with get_async_checkpointer() as checkpointer:
                graph = build_graph(checkpointer=checkpointer, settings=settings)
                await self._publish(session, NodeStartEvent(node_id="route_input"))
                await self._publish(session, NodeEndEvent(node_id="route_input", duration_ms=0))
                async for raw in graph.astream_events(graph_input, config=config, version="v2"):
                    for event in translator.translate(raw):
                        if event.type == "hitl_pending":
                            session.status = "awaiting-input"
                        await self._publish(session, event)

                state = await graph.aget_state(config)
                values = state.values or {}
                self._refresh_meta(session, values)

                if state.next:
                    session.status = "awaiting-input"
                    return

                final_pdf = values.get("final_pdf_path")
                if final_pdf:
                    session.status = "complete"
                    session.pdf_path = str(final_pdf)
                    session.stored_duration_s = session.get_duration_s()
                    await self._publish(
                        session,
                        CompleteEvent(
                            pdf_url=f"/api/runs/{session.thread_id}/pdf",
                            duration_s=round(session.stored_duration_s, 2),
                        ),
                    )
                    await self._close_subscribers(session)
                    self._save_run(session)
                    return

                reason = values.get("scrape_error") or "Generation finished without a PDF."
                session.status = "failed"
                session.error = str(reason)
                session.stored_duration_s = session.get_duration_s()
                await self._publish(session, FailedEvent(reason=str(reason)))
                await self._close_subscribers(session)
                self._save_run(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            session.status = "failed"
            session.error = str(exc)
            session.stored_duration_s = session.get_duration_s()
            await self._publish(session, FailedEvent(reason=str(exc)))
            await self._close_subscribers(session)
            self._save_run(session)

    def _save_run(self, session: RunSession) -> None:
        """Append a completed/failed run to the on-disk history file."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            record = {
                "thread_id": session.thread_id,
                "company": session.company,
                "role": session.role,
                "started_wall_ts": session.started_wall_ts,
                "status": session.status,
                "pdf_path": session.pdf_path,
                "error": session.error,
                "duration_s": session.stored_duration_s,
            }
            with _HISTORY_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
            self._trim_history()
        except Exception:
            pass  # history write failure must never crash the server

    def _trim_history(self) -> None:
        """Keep only the most recent _HISTORY_MAX_ENTRIES lines."""
        try:
            lines = _HISTORY_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
            if len(lines) > _HISTORY_MAX_ENTRIES:
                _HISTORY_FILE.write_text(
                    "".join(lines[-_HISTORY_MAX_ENTRIES:]), encoding="utf-8"
                )
        except Exception:
            pass

    def _load_history(self) -> None:
        """Populate _sessions with completed runs from the on-disk history file."""
        if not _HISTORY_FILE.exists():
            return
        try:
            for line in _HISTORY_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tid = rec.get("thread_id")
                if not tid or tid in self._sessions:
                    continue
                session = RunSession(
                    thread_id=tid,
                    status=rec.get("status", "complete"),
                    started_wall_ts=rec.get("started_wall_ts", 0.0),
                    company=rec.get("company", "Unknown"),
                    role=rec.get("role", "Unknown"),
                    pdf_path=rec.get("pdf_path"),
                    error=rec.get("error"),
                    stored_duration_s=rec.get("duration_s"),
                )
                self._sessions[tid] = session
        except Exception:
            pass  # corrupted history must not prevent startup

    async def _publish(self, session: RunSession, event: Event) -> None:
        session.events.append(event)
        for subscriber in list(session.subscribers):
            await subscriber.put(event)

    async def _close_subscribers(self, session: RunSession) -> None:
        for subscriber in list(session.subscribers):
            await subscriber.put(None)

    def _refresh_meta(self, session: RunSession, values: dict[str, Any]) -> None:
        jd = values.get("jd")
        if jd is not None:
            session.company = getattr(jd, "company", None) or (
                jd.get("company") if isinstance(jd, dict) else session.company
            )
            session.role = getattr(jd, "role_title", None) or (
                jd.get("role_title") if isinstance(jd, dict) else session.role
            )
        final_pdf = values.get("final_pdf_path")
        if final_pdf:
            session.pdf_path = str(final_pdf)


def _graph_config(thread_id: str, settings: ResumeAgentSettings) -> dict[str, Any]:
    retry_budget = max(1, settings.retries.generator_max)
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": max(50, 20 + retry_budget * 8),
    }


def run_summary(session: RunSession) -> dict[str, Any]:
    return {
        "id": session.thread_id,
        "thread_id": session.thread_id,
        "company": session.company,
        "role": session.role,
        "created_at": session.started_wall_ts,
        "status": session.status,
        "duration": _format_duration(session.get_duration_s()) if session.status != "awaiting-input" else "-",
        "retries": sum(1 for event in session.events if event.type == "retry"),
        "pdf": Path(session.pdf_path).name if session.pdf_path else None,
        "pdf_url": f"/api/runs/{session.thread_id}/pdf" if session.pdf_path else None,
        "error": session.error,
    }


def run_detail(session: RunSession) -> dict[str, Any]:
    data = run_summary(session)
    data["events"] = [dump_event(event) for event in session.events]
    return data


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    return f"{minutes}m {int(seconds % 60):02d}s"


run_manager = RunManager()

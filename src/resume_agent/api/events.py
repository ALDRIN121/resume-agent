"""Typed events sent from the backend to the React live-run UI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


def now_iso() -> str:
    """Return a compact UTC timestamp for API events."""
    return datetime.now(timezone.utc).isoformat()


class BaseEvent(BaseModel):
    type: str
    ts: str = Field(default_factory=now_iso)


class NodeStartEvent(BaseEvent):
    type: Literal["node_start"] = "node_start"
    node_id: str


class NodeEndEvent(BaseEvent):
    type: Literal["node_end"] = "node_end"
    node_id: str
    duration_ms: int | None = None


class LogLineEvent(BaseEvent):
    type: Literal["log_line"] = "log_line"
    line: str


class HITLPendingEvent(BaseEvent):
    type: Literal["hitl_pending"] = "hitl_pending"
    kind: Literal["ask_missing", "present_suggestions"]
    questions: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class LintWarning(BaseModel):
    code: str = "LINT"
    severity: Literal["info", "warn", "fail"] = "warn"
    message: str


class LintEvent(BaseEvent):
    type: Literal["lint"] = "lint"
    warnings: list[LintWarning] = Field(default_factory=list)


class VisionIssue(BaseModel):
    page: int = 1
    section: str = "Layout"
    issue: str
    fix: str | None = None


class VisionEvent(BaseEvent):
    type: Literal["vision"] = "vision"
    issues: list[VisionIssue] = Field(default_factory=list)


class RetryAttempt(BaseModel):
    n: int
    stage: str
    verdict: str
    detail: str


class RetryEvent(BaseEvent):
    type: Literal["retry"] = "retry"
    attempt: RetryAttempt


class CompleteEvent(BaseEvent):
    type: Literal["complete"] = "complete"
    pdf_url: str
    duration_s: float


class FailedEvent(BaseEvent):
    type: Literal["failed"] = "failed"
    reason: str
    debug_path: str | None = None


class ResumeParseEvent(BaseEvent):
    type: Literal["resume_parse"] = "resume_parse"
    stage_id: str
    label: str
    status: Literal["running", "done", "failed"] = "running"
    detail: str | None = None


Event = Annotated[
    NodeStartEvent
    | NodeEndEvent
    | LogLineEvent
    | HITLPendingEvent
    | LintEvent
    | VisionEvent
    | RetryEvent
    | CompleteEvent
    | FailedEvent
    | ResumeParseEvent,
    Field(discriminator="type"),
]


def dump_event(event: Event | BaseEvent) -> dict[str, Any]:
    """Serialize an event for FastAPI/WebSocket responses."""
    return event.model_dump(mode="json")

"""Adapters from LangGraph event streams to API event models."""

from __future__ import annotations

from collections.abc import Iterator
from time import perf_counter
from typing import Any

from .events import (
    Event,
    HITLPendingEvent,
    LintEvent,
    LintWarning,
    LogLineEvent,
    NodeEndEvent,
    NodeStartEvent,
    RetryAttempt,
    RetryEvent,
    VisionEvent,
    VisionIssue,
)

PIPELINE_NODE_IDS: tuple[str, ...] = (
    "route_input",
    "scrape_url",
    "extract_jd",
    "load_base_resume",
    "analyze_gaps",
    "hitl_ask_missing",
    "present_suggestions",
    "generate_latex",
    "resume_lint",
    "validate_latex",
    "compile_pdf",
    "render_pages",
    "validate_alignment",
    "hr_review",
    "save_output",
    "terminal_failure",
)

_PIPELINE_NODE_SET = set(PIPELINE_NODE_IDS)


class StreamTranslator:
    """Stateful mapper for LangGraph's raw stream-event dictionaries."""

    def __init__(self) -> None:
        self._starts: dict[str, float] = {}
        self._retry_seen = 0

    def translate(self, raw: dict[str, Any]) -> list[Event]:
        events: list[Event] = []
        name = str(raw.get("name") or "")
        event_name = str(raw.get("event") or "")
        node = _node_from_raw(raw)

        for payload in _interrupt_payloads(raw):
            hitl = _hitl_event(payload)
            if hitl:
                events.append(hitl)

        if node and event_name.endswith("_start"):
            self._starts[node] = perf_counter()
            events.append(NodeStartEvent(node_id=node))
            events.append(LogLineEvent(line=_log_line(node, "started")))

        if node and event_name.endswith("_end"):
            started = self._starts.pop(node, None)
            duration = int((perf_counter() - started) * 1000) if started else None
            events.append(NodeEndEvent(node_id=node, duration_ms=duration))
            events.append(LogLineEvent(line=_log_line(node, "finished")))

            output = _event_output(raw)
            events.extend(self._state_events(node, output))

        if event_name == "on_chain_stream":
            chunk = _event_chunk(raw)
            events.extend(self._state_events(node or name, chunk))

        return events

    def _state_events(self, node: str, output: Any) -> list[Event]:
        if not isinstance(output, dict):
            return []

        events: list[Event] = []
        lint_feedback = output.get("lint_feedback")
        if node == "resume_lint" and lint_feedback:
            events.append(
                LintEvent(
                    warnings=[
                        LintWarning(
                            code="RESUME_LINT",
                            severity="fail",
                            message=str(lint_feedback),
                        )
                    ]
                )
            )

        validation_feedback = output.get("validation_feedback")
        if node in {"validate_alignment", "hr_review"} and validation_feedback:
            events.append(
                VisionEvent(
                    issues=[
                        VisionIssue(
                            page=1,
                            section="Layout",
                            issue=str(validation_feedback),
                            fix="Review the generated PDF and rerun after edits.",
                        )
                    ]
                )
            )

        errors = output.get("latex_errors") or output.get("pdf_errors") or []
        if errors:
            self._retry_seen += 1
            events.append(
                RetryEvent(
                    attempt=RetryAttempt(
                        n=self._retry_seen,
                        stage=node,
                        verdict="fail",
                        detail="; ".join(map(str, errors[:3])),
                    )
                )
            )

        return events


def _node_from_raw(raw: dict[str, Any]) -> str | None:
    metadata = raw.get("metadata") or {}
    candidates = [
        raw.get("name"),
        metadata.get("langgraph_node"),
        metadata.get("checkpoint_ns"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        value = str(candidate).split(":")[0]
        if value in _PIPELINE_NODE_SET:
            return value
    return None


def _event_output(raw: dict[str, Any]) -> Any:
    data = raw.get("data") or {}
    if isinstance(data, dict):
        return data.get("output")
    return None


def _event_chunk(raw: dict[str, Any]) -> Any:
    data = raw.get("data") or {}
    if isinstance(data, dict):
        return data.get("chunk")
    return None


def _interrupt_payloads(raw: Any) -> Iterator[Any]:
    if isinstance(raw, dict):
        for key in ("__interrupt__", "interrupts"):
            value = raw.get(key)
            if value:
                yield from _normalize_interrupts(value)
        data = raw.get("data")
        if isinstance(data, dict):
            yield from _interrupt_payloads(data)
        for key in ("chunk", "output"):
            if isinstance(raw.get(key), dict):
                yield from _interrupt_payloads(raw[key])


def _normalize_interrupts(value: Any) -> Iterator[Any]:
    if isinstance(value, (list, tuple)):
        for item in value:
            yield getattr(item, "value", item)
    else:
        yield getattr(value, "value", value)


def _hitl_event(payload: Any) -> HITLPendingEvent | None:
    if not isinstance(payload, dict):
        return None
    kind = payload.get("kind")
    if kind == "missing_questions":
        return HITLPendingEvent(
            kind="ask_missing",
            questions=list(payload.get("questions") or []),
        )
    if kind == "tailoring_suggestions":
        return HITLPendingEvent(
            kind="present_suggestions",
            suggestions=list(payload.get("suggestions") or []),
        )
    return None


def _log_line(node: str, message: str) -> str:
    return f"{node:<20} | {message}"

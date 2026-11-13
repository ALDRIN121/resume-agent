"""Validated, JSON-only contracts for the private v2 services.

These contracts are deliberately independent of API/CLI settings and credentials.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator

from .schemas import UserResume

Identifier = Annotated[str, Field(min_length=1)]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def canonical_json(value: JsonValue | BaseModel) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value: JsonValue | BaseModel) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RunRequest(Contract):
    job_input: Annotated[str, Field(min_length=1)]
    input_type: Literal["text", "url"]
    execution_mode: Literal["app", "host"] = "app"
    max_pages: Annotated[int, Field(ge=1, le=5)] = 2
    job_id: str | None = None
    evaluation_id: str | None = None
    evaluation_override: bool = False
    parent_run_id: str | None = None
    job_location: str | None = None
    work_mode: str | None = None


class FixedRunInput(Contract):
    request: RunRequest
    profile_snapshot: dict[str, JsonValue]
    profile_revision: Hash
    profile_provenance: dict[str, JsonValue] | None = None
    memory_snapshot: dict[str, JsonValue] = Field(default_factory=dict)
    memory_revision: Hash
    provider: str | None = None
    model: str | None = None
    app_version: str | None = None
    build_revision: str | None = None

    @model_validator(mode="after")
    def verify_snapshots(self):
        normalized = UserResume.model_validate(self.profile_snapshot).model_dump(mode="json")
        if normalized != self.profile_snapshot or content_hash(normalized) != self.profile_revision:
            raise ValueError("profile snapshot/revision mismatch")
        if self.memory_snapshot:
            from .memory import MemorySnapshot
            MemorySnapshot.model_validate(self.memory_snapshot)
        if self.memory_revision != content_hash(self.memory_snapshot):
            raise ValueError("memory snapshot/revision mismatch")
        return self


class Action(Contract):
    action_id: Identifier


class AskMissing(Action):
    kind: Literal["ask_missing"] = "ask_missing"
    request_id: Identifier
    answers: dict[str, str]


class PresentSuggestions(Action):
    kind: Literal["present_suggestions"] = "present_suggestions"
    review_id: Identifier
    source_revision: Hash
    approved_ids: list[str]
    content_hash: Hash


class ReviewPdf(Action):
    kind: Literal["review_pdf"] = "review_pdf"
    review_id: Identifier
    content_hash: Hash
    render_hash: Hash
    pdf_hash: Hash
    decision: Literal["approve", "reject"]


class Continue(Action):
    kind: Literal["continue"] = "continue"


class ModelResponse(Action):
    kind: Literal["model_request"] = "model_request"
    request_id: Identifier
    input_hash: Hash
    result: JsonValue


ResumeAction = Annotated[
    AskMissing | PresentSuggestions | ReviewPdf | Continue | ModelResponse,
    Field(discriminator="kind"),
]


class AcceptImport(Action):
    kind: Literal["accept_import"] = "accept_import"
    review_id: Identifier
    draft_hash: Hash
    expected_profile_revision: Hash | None
    intentionally_blank_pages: list[int] = Field(default_factory=list)


class RejectImport(Action):
    kind: Literal["reject_import"] = "reject_import"
    review_id: Identifier


OperationAction = Annotated[
    AskMissing | PresentSuggestions | ReviewPdf | Continue | ModelResponse | AcceptImport | RejectImport,
    Field(discriminator="kind"),
]
ACTION_ADAPTER = TypeAdapter(OperationAction)
RUN_ACTION_ADAPTER = TypeAdapter(ResumeAction)


class PdfReview(Contract):
    review_id: Identifier
    content_hash: Hash
    render_hash: Hash
    pdf_hash: Hash
    template_version: Identifier
    layout_id: Identifier
    created_at: str = Field(default_factory=utc_now)


class AskMissingRequest(Contract):
    kind: Literal["ask_missing"] = "ask_missing"
    request_id: Identifier
    question_ids: list[str]
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class SuggestionReviewRequest(Contract):
    kind: Literal["present_suggestions"] = "present_suggestions"
    review_id: Identifier
    source_revision: Hash
    content_hash: Hash
    proposal_ids: list[str]
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class PdfReviewRequest(Contract):
    kind: Literal["review_pdf"] = "review_pdf"
    review: PdfReview
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class ModelRequest(Contract):
    kind: Literal["model_request"] = "model_request"
    request_id: Identifier
    input_hash: Hash
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class ImportReviewRequest(Contract):
    kind: Literal["import_review"] = "import_review"
    review_id: Identifier
    draft_hash: Hash
    expected_profile_revision: Hash | None
    unreadable_pages: list[int] = Field(default_factory=list)
    payload: dict[str, JsonValue] = Field(default_factory=dict)


PendingAction = Annotated[
    AskMissingRequest | SuggestionReviewRequest | PdfReviewRequest | ModelRequest | ImportReviewRequest,
    Field(discriminator="kind"),
]
PENDING_ADAPTER = TypeAdapter(PendingAction)


class Diagnostic(Contract):
    code: Identifier
    stage: Identifier


class ReleaseRecord(Contract):
    run_id: str
    review_id: str
    action_id: str
    content_hash: Hash
    render_hash: Hash
    pdf_hash: Hash
    canonical_pdf_path: str
    destination: str
    temporary_path: str
    ownership_token: str
    status: Literal["approved", "exporting", "released"]
    approved_at: str
    released_at: str | None


RunStatus = Literal["queued", "running", "awaiting-input", "interrupted", "complete", "failed", "cancelled"]
OperationStatus = Literal["pending_model", "pending_review", "running", "interrupted", "complete", "failed", "cancelled"]


class RunView(Contract):
    id: str
    artifact_id: str
    status: RunStatus
    artifact_status: Literal["pending", "available", "missing", "legacy_unverified"] = "pending"
    fixed_input_hashes: dict[str, str]
    pending: PendingAction | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    release: ReleaseRecord | None = None
    cancellation_requested: bool = False
    result: JsonValue = None


class OperationRequest(Contract):
    kind: Literal["profile_import", "role_evaluation"]
    input: dict[str, JsonValue]


class OperationView(Contract):
    id: str
    kind: Literal["profile_import", "role_evaluation"]
    status: OperationStatus
    pending: PendingAction | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    cancellation_requested: bool = False
    result: JsonValue = None


class DriverResult(Contract):
    status: Literal["awaiting-input", "pending_review", "pending_model", "interrupted", "complete"]
    pending: PendingAction | None = None
    result: JsonValue = None

    @model_validator(mode="after")
    def validate_pause(self):
        if self.status in {"awaiting-input", "pending_review", "pending_model"} and self.pending is None:
            raise ValueError("a pause requires pending action data")
        if self.status in {"interrupted", "complete"} and self.pending is not None:
            raise ValueError("terminal/interrupted result cannot have a pending request")
        return self


class Event(Contract):
    kind: Literal["state"] = "state"
    view: RunView | OperationView

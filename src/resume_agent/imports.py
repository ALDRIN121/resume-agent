"""Complete source extraction and durable, explicitly reviewed profile imports."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import io
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from .checkpoint import read_v2_checkpoint
from .config import MAX_RESUME_PARSE_CHARS, MAX_RESUME_UPLOAD_BYTES
from .contracts import (
    AcceptImport,
    DriverResult,
    ImportReviewRequest,
    OperationAction,
    OperationRequest,
    OperationView,
    content_hash,
)
from .operation_service import OperationService
from .profile_store import ProfileConflictError, ProfileStore
from .run_service import DriverContext, DriverFailureError
from .run_store import Conflict, RunStore
from .schemas import UserResume


class ImportInputError(ValueError):
    code = "invalid_import_input"


@dataclass(frozen=True)
class SourcePage:
    page_number: int
    text: str
    readable: bool
    warning: str | None = None
    source_sha256: str = ""


@dataclass(frozen=True)
class ExtractedSource:
    filename: str
    text: str
    pages: list[SourcePage]
    source_sha256: str

    @property
    def unreadable_pages(self) -> list[int]:
        return [page.page_number for page in self.pages if not page.readable]


def validate_resume_text(text: str) -> None:
    if len(text) > MAX_RESUME_PARSE_CHARS:
        raise ImportInputError("Resume text exceeds the supported limit of 48,000 characters")
    if not text.strip():
        raise ImportInputError("Could not extract readable text; provide a text-based source")


def extract_source(raw: bytes, filename: str) -> ExtractedSource:
    if len(raw) > MAX_RESUME_UPLOAD_BYTES:
        raise ImportInputError("Source exceeds the supported upload limit of 10 MiB")
    suffix = Path(filename).suffix.lower()
    if suffix == ".tex":
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ImportInputError("TEX source must contain UTF-8 text") from exc
        extracted = [(text, None)]
    elif suffix == ".pdf":
        extracted = _extract_pdf(raw)
    else:
        raise ImportInputError("Only .pdf and .tex resumes are supported")
    source_sha256 = hashlib.sha256(raw).hexdigest()
    pages = [
        SourcePage(
            number,
            text,
            bool(text.strip()),
            warning
            or (
                None
                if text.strip()
                else "No readable text; confirm intentionally blank or provide a text-based source"
            ),
            source_sha256,
        )
        for number, (text, warning) in enumerate(extracted, 1)
    ]
    text = "\n".join(page.text for page in pages)
    validate_resume_text(text)
    return ExtractedSource(Path(filename).name, text, pages, source_sha256)


def _extract_pdf(raw: bytes) -> list[tuple[str, str | None]]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        pages = []
        for page in reader.pages:
            try:
                pages.append((page.extract_text() or "", None))
            except Exception:
                pages.append(("", "Page text extraction failed; provide a text-based source"))
        return pages
    except Exception as exc:
        raise ImportInputError("Invalid or unreadable PDF source") from exc


class ImportService:
    """Profile import adapter over OperationService, kept private until client activation.

    ``create(raw, filename)`` persists source and a frozen expected profile revision.
    ``drive(id, action=None)`` parses or applies a typed reviewed action. ``get(id)``
    always includes the full source and draft, including after rejection/restart.
    """

    def __init__(
        self,
        store: RunStore,
        profiles: ProfileStore | None = None,
        *,
        parser: Callable[[str], UserResume | dict | Awaitable] | None = None,
        context_parser: Callable[[DriverContext, str], Awaitable] | None = None,
        model_selection: Callable[[], dict] | None = None,
    ):
        self.profiles = profiles if profiles is not None else ProfileStore()
        self.parser = parser
        self.context_parser = context_parser
        self.model_selection = model_selection
        self.operations = OperationService(
            store, driver=self._driver, action_validator=self._validate_action
        )

    def create(self, raw: bytes, filename: str, *, execution_mode='app') -> dict:
        if execution_mode not in ('app', 'host'):
            raise ValueError('invalid_execution_mode')
        if execution_mode == 'host' and self.context_parser is None:
            raise ValueError('host_parser_not_configured')
        # Validate the complete source before durable storage or any external work.
        source = extract_source(raw, filename)
        current = self.profiles.load_snapshot()
        source_data = asdict(source) | {"unreadable_pages": source.unreadable_pages}
        operation = self.operations.create(
            OperationRequest(
                kind="profile_import",
                input={
                    **({'provider': 'external_agent', 'model': 'host_agent', 'request': {'execution_mode': 'host'}}
                       if execution_mode == 'host' else (self.model_selection() if self.model_selection else {})),
                    "source": source_data,
                    "source_base64": base64.b64encode(raw).decode("ascii"),
                    "expected_profile_revision": current.revision if current else None,
                },
            )
        )
        return self._view(operation)

    def get(self, operation_id: str) -> dict:
        return self._view(self.operations.get(operation_id))

    def list(self, *, active_only=True, limit=50, offset=0):
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise ValueError('invalid_import_page')
        where = "kind='profile_import'" + (" AND status NOT IN ('complete','failed','cancelled')" if active_only else '')
        with self.operations.store.connection() as conn:
            rows = conn.execute('SELECT id,created_at,updated_at FROM operations WHERE ' + where + ' ORDER BY rowid DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
        items = []
        for row in rows:
            view = self.get(row['id'])
            if active_only and view['status'] in ('complete', 'failed', 'cancelled'):
                continue
            items.append({'id': row['id'], 'status': view['status'], 'filename': view['source']['filename'],
                          'created_at': row['created_at'], 'updated_at': row['updated_at'],
                          'pending_kind': view['pending']['kind'] if view['pending'] else None})
        with self.operations.store.connection() as conn:
            total = conn.execute('SELECT count(*) FROM operations WHERE ' + where).fetchone()[0]
        return {'items': items, 'total': total, 'limit': limit, 'offset': offset, 'has_more': offset + len(rows) < total}

    async def drive(self, operation_id: str, action: OperationAction | None = None) -> dict:
        self._inputs(operation_id)  # reject other operation kinds before running anything
        operation = await self.operations.drive(operation_id, action)
        # A profile revision race can happen after command validation. Preserve the
        # stable failed command result and expose it as a conflict on every replay.
        if any(item.code == "profile_conflict" for item in operation.diagnostics):
            raise Conflict("profile_conflict")
        return self._view(operation)

    def read_source(self, operation_id: str) -> tuple[str, bytes]:
        values = self._inputs(operation_id)
        return values["source"]["filename"], base64.b64decode(
            values["source_base64"], validate=True
        )

    def _inputs(self, operation_id: str) -> dict:
        row = self.operations.store.row("operation", operation_id)
        if row["kind"] != "profile_import":
            raise KeyError(operation_id)
        return self.operations.store.input("operation", operation_id)

    def _view(self, operation: OperationView) -> dict:
        fixed = self._inputs(operation.id)
        envelope = read_v2_checkpoint(
            self.operations.store.checkpoint_path, "operation", operation.id
        )
        values = envelope["values"] if envelope else {}
        return operation.model_dump(mode="json") | {
            "source": fixed["source"],
            "draft": values.get("draft"),
            "expected_profile_revision": fixed["expected_profile_revision"],
            "coverage_note": "Full source delivery and schema validity do not prove complete factual extraction; review the source and draft.",
        }

    def _validate_action(self, checkpoint: dict, action: OperationAction) -> None:
        if not isinstance(action, AcceptImport):
            return
        self._validated_draft(checkpoint, action)
        current = self.profiles.load_snapshot()
        if (current.revision if current else None) != action.expected_profile_revision:
            raise Conflict("profile_conflict")

    @staticmethod
    def _validated_draft(checkpoint: dict, action: AcceptImport) -> UserResume:
        draft = UserResume.model_validate(checkpoint.get("draft"))
        review = checkpoint.get("review", {})
        if (
            content_hash(draft) != action.draft_hash
            or review.get("review_id") != action.review_id
            or review.get("draft_hash") != action.draft_hash
            or review.get("expected_profile_revision") != action.expected_profile_revision
            or len(action.intentionally_blank_pages) != len(set(action.intentionally_blank_pages))
            or sorted(action.intentionally_blank_pages)
            != sorted(review.get("unreadable_pages", []))
        ):
            raise Conflict("stale_import_draft")
        return draft

    async def _driver(self, context: DriverContext) -> DriverResult:
        fixed, values = context.fixed_inputs, context.checkpoint
        context.control.check_cancelled()
        if isinstance(context.action, AcceptImport):
            action = context.action
            draft = self._validated_draft(values, action)
            current = self.profiles.load_snapshot()
            # YAML and checkpoint are separate stores. A crash after YAML replacement
            # is recoverable by the review/action identity in the same YAML commit.
            provenance = current.provenance if current else None
            already_saved = bool(
                current
                and not current.review_required
                and current.revision == action.draft_hash
                and provenance
                and provenance.get("import_id") == context.owner_id
                and provenance.get("action_id") == action.action_id
                and provenance.get("review_id") == action.review_id
                and provenance.get("draft_hash") == action.draft_hash
            )
            if not already_saved:
                context.control.check_cancelled()
                metadata = {
                    "import_id": context.owner_id,
                    "action_id": action.action_id,
                    "review_id": action.review_id,
                    "draft_hash": action.draft_hash,
                    "source_sha256": fixed["source"]["source_sha256"],
                    "intentionally_blank_pages": action.intentionally_blank_pages,
                }
                try:
                    current = self.profiles.save_reviewed(
                        action.expected_profile_revision, draft, metadata
                    )
                except ProfileConflictError:
                    raise DriverFailureError("profile_conflict", "profile_save") from None
            result = {
                "profile_revision": current.revision,
                "review_id": action.review_id,
                "draft_hash": action.draft_hash,
                "accepted": True,
            }
            context.control.checkpoint({"accepted": result, "applied_action_id": action.action_id})
            return DriverResult(status="complete", result=result)
        if values.get("review"):
            context.control.checkpoint({})
            return DriverResult(
                status="pending_review",
                pending=ImportReviewRequest.model_validate(values["review"]),
            )
        source = fixed["source"]
        context.control.checkpoint({"parse_attempts": values.get("parse_attempts", 0) + 1})
        parser = self.parser
        if self.context_parser is not None:
            parsed = await self.context_parser(context, source["text"])
        elif parser is None:
            from .agents.base_resume_loader import parse_resume_text

            parser = parse_resume_text
        if self.context_parser is not None:
            pass
        elif inspect.iscoroutinefunction(parser):
            parsed = await parser(source["text"])
        else:
            parsed = await asyncio.to_thread(parser, source["text"])
            if inspect.isawaitable(parsed):
                parsed = await parsed
        context.control.check_cancelled()
        draft = UserResume.model_validate(parsed)
        review = ImportReviewRequest(
            review_id=str(uuid.uuid4()),
            draft_hash=content_hash(draft),
            expected_profile_revision=fixed["expected_profile_revision"],
            unreadable_pages=source["unreadable_pages"],
            payload={"draft": draft.model_dump(mode="json"), "source": source},
        )
        context.control.checkpoint(
            {"draft": draft.model_dump(mode="json"), "review": review.model_dump(mode="json")}
        )
        return DriverResult(status="pending_review", pending=review)

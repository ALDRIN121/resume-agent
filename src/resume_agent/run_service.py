"""Private durable run lifecycle, shared with non-generation operations.

External work belongs to an injected async driver. The service owns persistence,
command validation, ownership, and cancellation; importing it activates no client.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import JsonValue, TypeAdapter

from . import __version__
from .checkpoint import read_v2_checkpoint, write_v2_checkpoint
from .contracts import (
    ACTION_ADAPTER,
    PENDING_ADAPTER,
    RUN_ACTION_ADAPTER,
    AskMissing,
    Continue,
    Diagnostic,
    DriverResult,
    Event,
    FixedRunInput,
    OperationAction,
    OperationView,
    PendingAction,
    RunRequest,
    RunView,
    canonical_json,
    content_hash,
)
from .run_store import TERMINAL, Conflict, RunStore
from .schemas import UserResume


class DriverConfigurationError(RuntimeError):
    pass


class _CancelledError(Exception):
    pass


class DriverFailureError(RuntimeError):
    """A trusted driver adapter's sanitized, stable error category and stage.

    Convert domain failures explicitly; never pass a provider exception message.
    """

    def __init__(self, code: str, stage: str = "driver"):
        if not all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) for value in (code, stage)):
            raise ValueError("invalid diagnostic identifier")
        self.code, self.stage = code, stage
        super().__init__(code)


class _DriverContractError(DriverFailureError):
    pass


class DriverControl:
    """Durable cancellation checkpoints, usable around each external call."""

    def __init__(self, lifecycle: _Lifecycle, owner_id: str, envelope: dict):
        self._lifecycle = lifecycle
        self._owner_id = owner_id
        self._envelope = envelope
        self.checkpointed = False

    def check_cancelled(self) -> None:
        if self._lifecycle.store.cancellation(self._lifecycle.kind, self._owner_id):
            raise _CancelledError()

    def checkpoint(self, values: dict[str, JsonValue]) -> None:
        """Merge JSON values before a pause/call; attempts and applied IDs survive restart."""
        self.check_cancelled()
        clean = TypeAdapter(dict[str, JsonValue]).validate_python(values, strict=True)
        clean = json.loads(canonical_json(clean))
        self._envelope["values"].update(clean)
        self._lifecycle._checkpoint(self._owner_id, self._envelope)
        self.checkpointed = True


@dataclass(frozen=True)
class DriverContext:
    owner_id: str
    owner_kind: str
    _fixed_inputs_json: str
    action: OperationAction | None
    checkpoint: dict[str, JsonValue]
    control: DriverControl
    recovering: bool = False

    @property
    def fixed_inputs(self) -> dict[str, JsonValue]:
        """A detached copy on every read: nested mutation cannot change fixed input."""
        return json.loads(self._fixed_inputs_json)


Driver = Callable[[DriverContext], Awaitable[DriverResult]]
ActionValidator = Callable[[dict[str, JsonValue], OperationAction], None]


def _validate_action(action: OperationAction | None, status: str, pending: PendingAction | None) -> None:
    if isinstance(action, Continue):
        if status != "interrupted" or pending is not None:
            raise Conflict("continue_not_allowed")
        return
    if action is None:
        if pending is not None or status not in {"queued", "pending_model"}:
            raise Conflict("action_required")
        return
    if pending is None:
        raise Conflict("no_pending_action")
    a, p = action.model_dump(mode="json"), pending.model_dump(mode="json")
    if p["kind"] == "import_review":
        if a["kind"] not in {"accept_import", "reject_import"} or a["review_id"] != p["review_id"]:
            raise Conflict("stale_action")
        if a["kind"] == "accept_import":
            if any(a[key] != p[key] for key in ("draft_hash", "expected_profile_revision")):
                raise Conflict("stale_action")
            if set(a["intentionally_blank_pages"]) != set(p["unreadable_pages"]):
                raise Conflict("blank_pages_unconfirmed")
        return
    if a["kind"] != p["kind"]:
        raise Conflict("wrong_action_stage")
    if p["kind"] == "review_pdf":
        p = p["review"]
        keys = ("review_id", "content_hash", "render_hash", "pdf_hash")
    else:
        keys = {
            "ask_missing": ("request_id",),
            "present_suggestions": ("review_id", "source_revision"),
            "model_request": ("request_id", "input_hash"),
        }[p["kind"]]
    if any(a[key] != p[key] for key in keys):
        raise Conflict("stale_action")
    if isinstance(action, AskMissing) and not set(action.answers) <= set(p["question_ids"]):
        raise Conflict("unknown_question")
    if action.kind == "present_suggestions":
        if len(set(a["approved_ids"])) != len(a["approved_ids"]) or not set(a["approved_ids"]) <= set(p["proposal_ids"]):
            raise Conflict("unknown_proposal")


class _Lifecycle:
    """One command path for run and operation owners, composed by both services."""

    def __init__(self, store: RunStore, kind: str, driver: Driver | None,
                 action_validator: ActionValidator | None = None):
        self.store, self.kind, self.driver = store, kind, driver
        self.action_validator = action_validator
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    def _checkpoint(self, owner_id: str, envelope: dict) -> None:
        write_v2_checkpoint(self.store.checkpoint_path, self.kind, owner_id, envelope)

    def _latest(self, owner_id: str) -> dict:
        return read_v2_checkpoint(self.store.checkpoint_path, self.kind, owner_id) or {
            "schema_version": 2, "values": {}, "index": None, "inflight_action_ids": [],
        }

    def _view(self, owner_id: str, conn=None) -> RunView | OperationView:
        row = self.store.row(self.kind, owner_id, conn)
        output = json.loads(row["result_json"]) if row["result_json"] else {}
        args = dict(id=owner_id, status=row["status"],
                    pending=PENDING_ADAPTER.validate_json(row["pending_json"]) if row["pending_json"] else None,
                    diagnostics=output.get("diagnostics", []), result=output.get("result"),
                    cancellation_requested=self.store.cancellation(self.kind, owner_id, conn))
        if self.kind == "operation":
            return OperationView(kind=row["kind"], **args)
        fixed = json.loads(row["input_json"])
        release = self.store.release(owner_id, conn)
        artifact_status = "pending"
        if release and release["status"] == "released":
            from pathlib import Path
            artifact_status = "available" if Path(release["canonical_pdf_path"]).is_file() else "missing"
        return RunView(artifact_id=row["artifact_id"], release=release, artifact_status=artifact_status,
                       fixed_input_hashes={"profile": fixed["profile_revision"], "memory": fixed["memory_revision"],
                                           "job": content_hash(fixed["request"]["job_input"]), "input": content_hash(fixed)}, **args)

    def _commit_index(self, owner_id: str, index: dict, action_ids: list[str]) -> RunView | OperationView:
        with self.store.connection(immediate=True) as conn:
            row = self.store.row(self.kind, owner_id, conn)
            # Release commit is authoritative; cancellation can never erase it.
            release = self.store.release(owner_id, conn) if self.kind == "run" else None
            status = "complete" if release and release["status"] == "released" else index["status"]
            if not (release and release["status"] == "released") and (
                row["status"] == "cancelled" or self.store.cancellation(self.kind, owner_id, conn)
            ):
                status = "cancelled"
            if self.kind == "run" and status == "complete" and not (release and release["status"] == "released"):
                raise _DriverContractError("release_required")
            previous_output = json.loads(row["result_json"]) if row["result_json"] else {}
            diagnostics = index.get("diagnostics", previous_output.get("diagnostics", []))
            self.store.update(self.kind, owner_id, status=status,
                              pending=index.get("pending") if status not in TERMINAL else None,
                              result={"result": index.get("result", previous_output.get("result")), "diagnostics": diagnostics},
                              code=diagnostics[0]["code"] if diagnostics else None,
                              stage=diagnostics[0]["stage"] if diagnostics else None, conn=conn)
            view = self._view(owner_id, conn)
            self.store.finish_actions(self.kind, owner_id, action_ids, view.model_dump(mode="json"), conn)
        self._publish(owner_id, view)
        return view

    def _reconcile(self, owner_id: str) -> None:
        row = self.store.row(self.kind, owner_id)
        release = self.store.release(owner_id) if self.kind == "run" else None
        if release and release["status"] == "released":
            with self.store.connection() as conn:
                unfinished = self.store.unfinished(self.kind, owner_id, conn)
            if row["status"] != "complete" or unfinished:
                self._commit_index(owner_id, {"status": "complete"}, [a["action_id"] for a in unfinished])
            return
        if self.store.cancellation(self.kind, owner_id) and row["status"] != "complete":
            with self.store.connection() as conn:
                unfinished = self.store.unfinished(self.kind, owner_id, conn)
            self._commit_index(owner_id, {"status": "cancelled"}, [a["action_id"] for a in unfinished])
            return
        if row["status"] in TERMINAL:
            return
        saved = self._latest(owner_id)
        index = saved.get("index")
        with self.store.connection() as conn:
            unfinished = self.store.unfinished(self.kind, owner_id, conn)
        unfinished_ids = {item["action_id"] for item in unfinished}
        checkpoint_finished = set(saved.get("finished_action_ids", []))
        if unfinished_ids - checkpoint_finished:
            self._commit_index(owner_id, {"status": "interrupted"}, [])
        elif index and index["status"] != "running":
            self._commit_index(owner_id, index, saved.get("finished_action_ids", []))
        elif row["status"] == "running":
            self._commit_index(owner_id, {"status": "interrupted"}, [])

    def get(self, owner_id: str) -> RunView | OperationView:
        try:
            with self.store.ownership(self.kind, owner_id):
                self._reconcile(owner_id)
        except Conflict:
            pass  # active worker owns reconciliation; readers still see cancellation commands
        return self._view(owner_id)

    def cancel(self, owner_id: str) -> RunView | OperationView:
        self.store.cancel(self.kind, owner_id)
        view = self.get(owner_id)
        self._publish(owner_id, view)
        return view

    def _publish(self, owner_id: str, view: RunView | OperationView) -> None:
        for queue in self._subscribers.get(owner_id, ()):
            queue.put_nowait(Event(view=view))

    async def subscribe(self, owner_id: str) -> AsyncIterator[Event]:
        queue = asyncio.Queue()
        self._subscribers.setdefault(owner_id, set()).add(queue)
        try:
            yield Event(view=self.get(owner_id))
            while True:
                yield await queue.get()
        finally:
            self._subscribers[owner_id].discard(queue)
            if not self._subscribers[owner_id]:
                del self._subscribers[owner_id]

    async def drive(self, owner_id: str, action: OperationAction | None = None) -> RunView | OperationView:
        if action is not None:
            adapter = RUN_ACTION_ADAPTER if self.kind == "run" else ACTION_ADAPTER
            action = adapter.validate_python(action.model_dump(mode="json") if hasattr(action, "model_dump") else action)
        with self.store.ownership(self.kind, owner_id):
            self._reconcile(owner_id)
            with self.store.connection(immediate=True) as conn:
                row = self.store.row(self.kind, owner_id, conn)
                if action:
                    previous = self.store.action(self.kind, owner_id, action.action_id, conn)
                    if previous:
                        if previous["request_hash"] != content_hash(action):
                            raise Conflict("action_payload_conflict")
                        if previous["result_json"]:
                            cls = RunView if self.kind == "run" else OperationView
                            return cls.model_validate_json(previous["result_json"])
                        raise Conflict("action_recovery_required")
                if row["status"] in TERMINAL:
                    if action:
                        raise Conflict("owner_terminal")
                    return self._view(owner_id, conn)
                pending = PENDING_ADAPTER.validate_json(row["pending_json"]) if row["pending_json"] else None
                _validate_action(action, row["status"], pending)
                if action is not None and action.kind != "continue":
                    if action.kind == "present_suggestions" and self.action_validator is None:
                        raise Conflict("content_validator_not_configured")
                    if self.action_validator is not None:
                        try:
                            self.action_validator(self._latest(owner_id)["values"], action)
                        except Exception:
                            raise Conflict("action_validation_failed") from None
                if self.driver is None:
                    raise DriverConfigurationError("v2_driver_not_configured")
                unfinished = self.store.unfinished(self.kind, owner_id, conn)
                if unfinished and not isinstance(action, Continue):
                    raise Conflict("action_recovery_required")
                action_ids = [item["action_id"] for item in unfinished]
                driver_action = ACTION_ADAPTER.validate_json(unfinished[0]["request_json"]) if unfinished else action
                if action:
                    self.store.accept(self.kind, owner_id, action.model_dump(mode="json"), content_hash(action), conn)
                    action_ids.append(action.action_id)
                self.store.update(self.kind, owner_id, status="running", pending=None, conn=conn)
            saved = self._latest(owner_id)
            envelope = {**saved, "index": {"status": "running"}, "inflight_action_ids": action_ids,
                        "finished_action_ids": []}
            self._checkpoint(owner_id, envelope)
            control = DriverControl(self, owner_id, envelope)
            context = DriverContext(owner_id, self.kind, row["input_json"], driver_action,
                                    json.loads(canonical_json(envelope["values"])), control, bool(unfinished))
            try:
                control.check_cancelled()
                if driver_action and driver_action.kind in {"review_pdf", "reject_import"} and (
                    driver_action.kind == "reject_import" or driver_action.decision == "reject"
                ):
                    self.store.cancel(self.kind, owner_id)
                    raise _CancelledError()
                outcome = await self.driver(context)
                control.check_cancelled()
                if not isinstance(outcome, DriverResult):
                    raise _DriverContractError("invalid_driver_result")
                outcome = DriverResult.model_validate(outcome.model_dump(mode="json"))
                if not control.checkpointed:
                    raise _DriverContractError("checkpoint_required")
                allowed = {"awaiting-input", "interrupted", "complete"} if self.kind == "run" else {"pending_model", "pending_review", "interrupted", "complete"}
                if outcome.status not in allowed:
                    raise _DriverContractError("invalid_driver_status")
                if self.kind == "run" and outcome.status == "complete":
                    release = self.store.release(owner_id)
                    if not release or release["status"] != "released":
                        raise _DriverContractError("release_required")
                index = outcome.model_dump(mode="json")
            except _CancelledError:
                index = {"status": "cancelled"}
            except asyncio.CancelledError:
                # Explicit recovery is required, including accepted commands without results.
                envelope["index"] = {"status": "interrupted"}
                self._checkpoint(owner_id, envelope)
                self._commit_index(owner_id, envelope["index"], [])
                raise
            except sqlite3.Error:
                raise  # required persistence failures must remain visible to the caller
            except Exception as exc:
                code = exc.code if isinstance(exc, DriverFailureError) else "driver_failed"
                stage = exc.stage if isinstance(exc, DriverFailureError) else "driver"
                index = {"status": "failed", "diagnostics": [Diagnostic(code=code, stage=stage).model_dump()]}
            envelope["index"] = index
            envelope["finished_action_ids"] = action_ids
            self._checkpoint(owner_id, envelope)
            return self._commit_index(owner_id, index, action_ids)


class RunService:
    def __init__(self, store: RunStore, *, driver: Driver | None = None,
                 action_validator: ActionValidator | None = None):
        self.store = store
        self._lifecycle = _Lifecycle(store, "run", driver, action_validator)

    def create(self, request: RunRequest, *, profile_snapshot: UserResume | dict[str, Any],
               profile_revision: str | None = None, memory_snapshot: dict | None = None,
               memory_revision: str | None = None, provider: str | None = None, model: str | None = None,
               app_version: str | None = None, build_revision: str | None = None) -> RunView:
        request = RunRequest.model_validate(request.model_dump(mode="json"))
        profile = UserResume.model_validate(profile_snapshot).model_dump(mode="json")
        fixed = FixedRunInput(request=request, profile_snapshot=profile,
                              profile_revision=content_hash(profile) if profile_revision is None else profile_revision,
                              memory_snapshot={} if memory_snapshot is None else memory_snapshot,
                              memory_revision=content_hash({}) if memory_revision is None else memory_revision, provider=provider, model=model,
                              app_version=__version__ if app_version is None else app_version, build_revision=build_revision)
        owner_id = self.store.create_run(fixed.model_dump(mode="json"))
        return self.get(owner_id)

    def get(self, run_id: str) -> RunView:
        return self._lifecycle.get(run_id)

    async def drive(self, run_id: str, action=None) -> RunView:
        return await self._lifecycle.drive(run_id, action)

    def subscribe(self, run_id: str) -> AsyncIterator[Event]:
        return self._lifecycle.subscribe(run_id)

    def cancel(self, run_id: str) -> RunView:
        return self._lifecycle.cancel(run_id)

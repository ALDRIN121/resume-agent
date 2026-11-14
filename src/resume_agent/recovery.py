"""Safe legacy recovery and boot reconciliation, with no automatic execution."""
from __future__ import annotations

import json
import sqlite3

from pydantic import ValidationError

from . import __version__
from .checkpoint import inspect_v1_checkpoint, read_v2_checkpoint
from .contracts import FixedRunInput, PdfReviewRequest, RunRequest, content_hash
from .run_store import TERMINAL, Conflict, RunStore
from .schemas import UserResume


class LegacyRecoveryError(ValueError):
    """The saved source cannot safely reconstruct a fresh run."""


def recover_legacy(store: RunStore, run_id: str, *, provider: str | None = None,
                   model: str | None = None) -> str:
    existing = store.legacy_child(run_id)
    if existing:
        return existing
    with store.connection() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        historical = conn.execute("SELECT status FROM resumes WHERE thread_id=?", (run_id,)).fetchone() if 'resumes' in tables else None
        if historical and historical[0] not in {'awaiting-input', 'interrupted', 'running'}:
            raise LegacyRecoveryError('legacy_recovery_not_allowed')
        if conn.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone():
            raise LegacyRecoveryError('legacy_run_required')
    try:
        saved = inspect_v1_checkpoint(store.checkpoint_path, run_id)
    except (sqlite3.Error, ValueError, TypeError) as exc:
        raise LegacyRecoveryError('legacy_checkpoint_invalid') from exc
    if not saved:
        raise LegacyRecoveryError('legacy_checkpoint_missing')
    if saved.get('schema_version', 1) != 1:
        raise LegacyRecoveryError('legacy_checkpoint_invalid')
    if not saved.get('base_resume') or not saved.get('raw_input') or not saved.get('input_type'):
        raise LegacyRecoveryError('legacy_source_missing')
    try:
        profile = UserResume.model_validate(saved['base_resume']).model_dump(mode='json')
        request = RunRequest(job_input=saved['raw_input'], input_type=saved['input_type'],
            parent_run_id=run_id, job_location=saved.get('job_location'), work_mode=saved.get('work_mode'))
        answers = saved.get('hitl_answers') or {}
        if not isinstance(answers, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in answers.items()):
            raise ValueError('invalid saved answers')
        fixed = FixedRunInput(request=request, profile_snapshot=profile, profile_revision=content_hash(profile),
            memory_snapshot={}, memory_revision=content_hash({}), provider=provider, model=model, app_version=__version__)
    except (ValidationError, ValueError, TypeError) as exc:
        raise LegacyRecoveryError('legacy_source_invalid') from exc
    return store.create_legacy_child(run_id, fixed.model_dump(mode='json'), answers)


def _reconcile_frozen_review(service, release_service, run_id: str) -> None:
    """Bridge the frozen-review/index handoff while retaining command authority."""
    with service.store.ownership('run', run_id):
        row = service.store.row('run', run_id)
        if row['status'] in TERMINAL or service.store.cancellation('run', run_id):
            return
        # An approved export is already past review and requires its own explicit
        # continuation. A released record remains the final completion authority.
        if service.store.release(run_id) is not None:
            return
        inspection = release_service.inspect(run_id)
        binding = read_v2_checkpoint(service.store.checkpoint_path, 'release', run_id)
        lifecycle = service._lifecycle
        saved = lifecycle._latest(run_id)
        with service.store.connection() as conn:
            unfinished = service.store.unfinished('run', run_id, conn)
        values = saved['values']
        frozen_hash = binding['manifest']['content_hash']
        applied_ids = set(values.get('applied_action_ids', []))

        def applied_content(action: dict) -> bool:
            request = json.loads(action['request_json'])
            return (request.get('kind') == 'present_suggestions'
                    and action['action_id'] in applied_ids
                    and request.get('content_hash') == frozen_hash == inspection.review.content_hash
                    and values.get('manifest', {}).get('content_hash') == frozen_hash)

        # A frozen review proves that bytes were checked, never that an accepted
        # PDF approval/rejection was completed. Unproven content commands also
        # keep their accepted state and require Continue through the same command.
        proven = inspection.status == 'review' and all(applied_content(action) for action in unfinished)
        unfinished_ids = {action['action_id'] for action in unfinished}
        finished = [item for item in saved.get('finished_action_ids', []) if item not in unfinished_ids]
        if proven:
            review = inspection.review.model_dump(mode='json')
            pending = PdfReviewRequest(review=inspection.review).model_dump(mode='json')
            for candidate in ((saved.get('index') or {}).get('pending'),
                              json.loads(row['pending_json']) if row['pending_json'] else None):
                if candidate and candidate.get('kind') == 'review_pdf' and candidate.get('review') == review:
                    pending = candidate
                    break
            index = {'status': 'awaiting-input', 'pending': pending}
            completed_ids = [action['action_id'] for action in unfinished]
            finished.extend(completed_ids)
        else:
            index, completed_ids = {'status': 'interrupted'}, []
        lifecycle._checkpoint(run_id, {**saved, 'index': index, 'finished_action_ids': finished,
            'inflight_action_ids': [] if proven else [action['action_id'] for action in unfinished]})
        lifecycle._commit_index(run_id, index, completed_ids)


def _startup_diagnostic(service, run_id, code=None):
    """Keep an artifact conflict local to its owner; never hide database failures."""
    lifecycle = service._lifecycle
    try:
        with service.store.ownership('run', run_id):
            saved = lifecycle._latest(run_id)
            with service.store.connection() as conn:
                view = lifecycle._view(run_id, conn)
            diagnostics = [d.model_dump() for d in view.diagnostics if d.stage != 'release_recovery']
            if code:
                diagnostics.append({'code': code, 'stage': 'release_recovery'})
            if diagnostics == [d.model_dump() for d in view.diagnostics]:
                return
            index = {'status': 'cancelled' if view.cancellation_requested else view.status,
                     'pending': view.pending.model_dump(mode='json') if view.pending else None,
                     'diagnostics': diagnostics}
            lifecycle._checkpoint(run_id, {**saved, 'index': index})
            lifecycle._commit_index(run_id, index, [])
    except Conflict as exc:
        if str(exc) != 'owner_busy':
            raise


def reconcile_startup(service) -> list:
    """Rebuild durable indexes and finish already-commanded cancellation cleanup."""
    from .release_service import ReleaseService

    release_service = ReleaseService(service.store)
    views = []
    for run_id in service.store.run_ids():
        binding = read_v2_checkpoint(service.store.checkpoint_path, 'release', run_id)
        if binding and service.store.cancellation('run', run_id):
            try:
                release_service.recover_unfinished(run_id, cancel=True)
            except Conflict as exc:
                if str(exc) != 'owner_busy':
                    _startup_diagnostic(service, run_id, str(exc))
            else:
                _startup_diagnostic(service, run_id)
        elif binding:
            try:
                _reconcile_frozen_review(service, release_service, run_id)
            except Conflict as exc:
                if str(exc) != 'owner_busy':
                    _startup_diagnostic(service, run_id, str(exc))
            else:
                _startup_diagnostic(service, run_id)
        views.append(service.get(run_id))
    return views

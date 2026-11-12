"""Safe legacy recovery and boot reconciliation, with no automatic execution."""
from __future__ import annotations

import sqlite3

from pydantic import ValidationError

from . import __version__
from .checkpoint import inspect_v1_checkpoint, read_v2_checkpoint
from .contracts import FixedRunInput, RunRequest, content_hash
from .run_store import Conflict, RunStore
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
                    raise
        views.append(service.get(run_id))
    return views

"""Private reviewed-PDF release boundary; importing this module mounts no routes.

The run worker lock serializes release workers. Cancellation uses library.sqlite
without that lock, and races the atomic rename through the same immediate SQLite
transaction. LangGraph owns a separate ``release:<run_id>`` checkpoint binding;
ordinary lifecycle checkpoints cannot overwrite the frozen review or intent.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .approved_render import RenderRecord, render_identity
from .artifacts import (
    ExportPlan,
    cleanup_export,
    commit_export,
    hash_file,
    prepare_copy,
    prepare_export,
)
from .checkpoint import read_v2_checkpoint, write_v2_checkpoint
from .contracts import (
    PdfReview,
    PdfReviewRequest,
    ReviewPdf,
    RunView,
    content_hash,
    utc_now,
)
from .pdf_content_check import verify_pdf_content
from .run_store import Conflict, RunStore
from .schemas import RenderManifest


class ReleaseConflict(Conflict):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ReleaseError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ReleaseInspection:
    status: str
    review: PdfReview | None
    release: dict | None
    plan: ExportPlan | None
    orphan_plans: tuple[ExportPlan, ...] = ()
    cleanup_pending: bool = False


class ReleaseService:
    def __init__(self, store: RunStore, *, crash_hook: Callable[[str], None] | None = None):
        self.store = store
        self._crash_hook = crash_hook

    def _boundary(self, name: str) -> None:
        # Only tests inject this callable. BaseException models process death and
        # deliberately bypasses normal Exception cleanup/transaction recovery.
        if self._crash_hook is not None:
            self._crash_hook(name)

    def _binding(self, run_id: str) -> dict:
        self.store.row('run', run_id)
        value = read_v2_checkpoint(self.store.checkpoint_path, 'release', run_id)
        if value is None:
            raise ReleaseConflict('review_required')
        return value

    def _save(self, run_id: str, binding: dict) -> None:
        write_v2_checkpoint(self.store.checkpoint_path, 'release', run_id, binding)

    def _check(self, run_id: str, manifest: RenderManifest, record: RenderRecord) -> None:
        row = self.store.row('run', run_id)
        path = Path(record.pdf_path)
        if (record.artifact_id != row['artifact_id'] or record.content_hash != manifest.content_hash
                or record.template_version != manifest.template_version
                or record.render_hash != render_identity(record.content_hash, record.template_hash, record.layout)
                or record.overflow or record.overfull_boxes
                or record.page_count > json.loads(row['input_json'])['request']['max_pages']
                or not path.is_absolute() or path.resolve() != path
                or path.name != 'resume.pdf' or path.parent.name != str(record.attempt_number)
                or path.parent.parent.name != 'attempts'
                or path.parent.parent.parent.name != row['artifact_id']):
            raise ReleaseConflict('render_identity_mismatch')
        try:
            if hash_file(path) != record.pdf_hash:
                raise ReleaseConflict('canonical_pdf_mismatch')
        except (OSError, ValueError) as exc:
            raise ReleaseConflict('canonical_pdf_unavailable') from exc
        checked = verify_pdf_content(manifest, path)
        if not checked.ok or checked.page_count != record.page_count:
            raise ReleaseConflict('pdf_content_mismatch')
        if hash_file(path) != record.pdf_hash:
            raise ReleaseConflict('canonical_pdf_mismatch')

    def create_review(self, run_id: str, manifest: RenderManifest, record: RenderRecord,
                      *, worker_owned: bool = False) -> PdfReview:
        """Freeze verified review bytes. Driver callers already owning run lock opt in."""
        with nullcontext() if worker_owned else self.store.ownership('run', run_id):
            self._check(run_id, manifest, record)
            if self.store.release(run_id) is not None:
                raise ReleaseConflict('release_already_approved')
            if self.store.cancellation('run', run_id):
                raise ReleaseConflict('run_cancelled')
            old = read_v2_checkpoint(self.store.checkpoint_path, 'release', run_id)
            if old and old['record'] == record.to_dict() and old['manifest'] == manifest.model_dump(mode='json'):
                review = PdfReview.model_validate(old['review'])
            else:
                review = PdfReview(review_id=str(uuid4()), content_hash=record.content_hash,
                    render_hash=record.render_hash, pdf_hash=record.pdf_hash,
                    template_version=record.template_version, layout_id=record.layout_id)
                self._save(run_id, {'review': review.model_dump(mode='json'),
                    'manifest': manifest.model_dump(mode='json'), 'record': record.to_dict()})
            with self.store.connection(immediate=True) as conn:
                if self.store.cancellation('run', run_id, conn):
                    raise ReleaseConflict('run_cancelled')
                self.store.update('run', run_id, status='awaiting-input',
                    pending=PdfReviewRequest(review=review).model_dump(mode='json'), conn=conn)
            return review

    def _view(self, run_id: str, conn) -> RunView:
        from .contracts import PENDING_ADAPTER
        row = self.store.row('run', run_id, conn)
        fixed = json.loads(row['input_json'])
        output = json.loads(row['result_json']) if row['result_json'] else {}
        released = self.store.release(run_id, conn)
        available = released and released['status'] == 'released'
        return RunView(id=run_id, artifact_id=row['artifact_id'], status=row['status'],
            artifact_status=('available' if Path(released['canonical_pdf_path']).is_file() else 'missing')
                if available else 'pending',
            fixed_input_hashes={'profile': fixed['profile_revision'], 'memory': fixed['memory_revision'],
                'job': content_hash(fixed['request']['job_input']), 'input': content_hash(fixed)},
            pending=PENDING_ADAPTER.validate_json(row['pending_json']) if row['pending_json'] else None,
            release=released, diagnostics=output.get('diagnostics', []), result=output.get('result'),
            cancellation_requested=self.store.cancellation('run', run_id, conn))

    def _replay(self, run_id: str, action: ReviewPdf, conn) -> RunView | None:
        previous = self.store.action('run', run_id, action.action_id, conn)
        if previous:
            if previous['request_hash'] != content_hash(action):
                raise ReleaseConflict('action_id_reused')
            if previous['result_json'] is not None:
                return RunView.model_validate_json(previous['result_json'])
        return None

    def _action(self, run_id: str, action: ReviewPdf, binding: dict) -> None:
        review = PdfReview.model_validate(binding['review'])
        if any(getattr(action, key) != getattr(review, key)
               for key in ('review_id', 'content_hash', 'render_hash', 'pdf_hash')):
            raise ReleaseConflict('stale_review')
        self._check(run_id, RenderManifest.model_validate(binding['manifest']),
                    RenderRecord.from_dict(binding['record']))

    def _plan(self, release: dict) -> ExportPlan:
        """The indexed destination/token selects the fsynced complete-plan sidecar."""
        ownership = Path(release['destination']).with_name(
            f".{Path(release['destination']).name}.{release['ownership_token']}.owner.json")
        binding = self._binding(release['run_id'])
        try:
            plan = ExportPlan.from_dict(binding['plan'])
            if ownership.exists():
                if json.loads(ownership.read_text())['plan'] != plan.to_dict():
                    raise ValueError('Sidecar differs from checkpoint plan')
            elif not (self.store.cancellation('run', release['run_id'])
                      and not plan.destination.exists() and not plan.temporary_path.exists()):
                raise ValueError('Export ownership missing')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ReleaseConflict('export_ownership_unavailable') from exc
        if any(str(getattr(plan, source)) != str(release[target]) for source, target in (
                ('canonical_pdf_path', 'canonical_pdf_path'), ('destination', 'destination'),
                ('temporary_path', 'temporary_path'), ('ownership_token', 'ownership_token'),
                ('expected_hash', 'pdf_hash'))):
            raise ReleaseConflict('export_plan_mismatch')
        return plan

    def _orphans(self, run_id: str, binding: dict) -> tuple[ExportPlan, ...]:
        intent = binding.get('intent')
        if not intent:
            return ()
        artifact = self.store.row('run', run_id)['artifact_id']
        found = []
        for path in Path(intent['base_dir']).rglob('.*.owner.json'):
            try:
                plan = ExportPlan.from_dict(json.loads(path.read_text())['plan'])
            except (OSError, ValueError, KeyError, TypeError):
                continue  # Unknown sidecars are never candidates for deletion.
            if (plan.artifact_id == artifact and plan.ownership_path == path
                    and str(plan.canonical_pdf_path) == binding['record']['pdf_path']
                    and plan.expected_hash == binding['review']['pdf_hash']):
                found.append(plan)
        return tuple(found)

    def inspect(self, run_id: str) -> ReleaseInspection:
        """Read-only startup inspection: never prepares copies or releases bytes."""
        released = self.store.release(run_id)
        if released and released['status'] == 'released':
            binding = read_v2_checkpoint(self.store.checkpoint_path, 'release', run_id)
            review = PdfReview.model_validate(binding['review']) if binding else None
            owner = Path(released['destination']).with_name(
                f".{Path(released['destination']).name}.{released['ownership_token']}.owner.json")
            return ReleaseInspection('complete', review, released, None, cleanup_pending=owner.exists())
        binding = self._binding(run_id)
        review = PdfReview.model_validate(binding['review'])
        if released:
            with self.store.connection() as conn:
                action = self.store.action('run', run_id, released['action_id'], conn)
            if (action and action['result_json'] is not None
                    and json.loads(action['result_json'])['status'] == 'cancelled'):
                plan = ExportPlan.from_dict(binding['plan'])
                if not any(path.exists() for path in (plan.ownership_path, plan.destination, plan.temporary_path)):
                    return ReleaseInspection('cancelled', review, released, None)
                return ReleaseInspection('cancelled', review, released, self._plan(released), cleanup_pending=True)
            return ReleaseInspection('interrupted', review, released, self._plan(released))
        orphans = self._orphans(run_id, binding)
        status = 'cancelled' if self.store.cancellation('run', run_id) else 'interrupted' if orphans else 'review'
        return ReleaseInspection(status, review, None, None, orphans)

    def _cleanup(self, plan: ExportPlan, *, cancelled: bool = False) -> None:
        if (cancelled and not plan.ownership_path.exists()
                and not plan.destination.exists() and not plan.temporary_path.exists()):
            return  # Cleanup succeeded before an interrupted cancellation commit.
        try:
            cleanup_export(plan, remove_export=cancelled)
        except ValueError as exc:
            raise ReleaseConflict('export_ownership_conflict') from exc

    def _finish_cancel(self, run_id: str, action_id: str, conn, plan=None) -> RunView:
        if plan is not None:
            self._cleanup(plan, cancelled=True)
        self.store.update('run', run_id, status='cancelled', pending=None, conn=conn)
        view = self._view(run_id, conn)
        self.store.finish_actions('run', run_id, [action_id], view.model_dump(mode='json'), conn)
        return view

    def release(self, run_id: str, action: ReviewPdf | dict, *, base_dir: Path,
                company_name: str, user_full_name: str, worker_owned: bool = False,
                recover_reservation: bool = False) -> RunView:
        action = ReviewPdf.model_validate(action.model_dump() if isinstance(action, ReviewPdf) else action)
        with nullcontext() if worker_owned else self.store.ownership('run', run_id):
            with self.store.connection() as conn:
                replay = self._replay(run_id, action, conn)
                if replay is not None:
                    return replay
            binding = self._binding(run_id)
            self._action(run_id, action, binding)
            previous = self.store.release(run_id)
            if previous is not None:
                if previous['action_id'] != action.action_id:
                    raise ReleaseConflict('release_already_approved')
                raise ReleaseConflict('explicit_recovery_required')
            if action.decision == 'reject':
                with self.store.connection(immediate=True) as conn:
                    if self.store.action('run', run_id, action.action_id, conn) is None:
                        self.store.accept('run', run_id, action.model_dump(mode='json'), content_hash(action), conn)
                    conn.execute('INSERT OR IGNORE INTO cancellations VALUES(?,?,?,?)',
                                 ('run', run_id, action.action_id, utc_now()))
                    return self._finish_cancel(run_id, action.action_id, conn)
            if self.store.cancellation('run', run_id):
                raise ReleaseConflict('run_cancelled')
            # A persisted intent makes even the reservation-before-row window
            # discoverable by this artifact's UUID. No approval is inferred there.
            orphans = self._orphans(run_id, binding)
            if orphans and not recover_reservation:
                raise ReleaseConflict('orphan_reservation_requires_recovery')
            if len(orphans) > 1:
                raise ReleaseConflict('export_ownership_conflict')
            if recover_reservation and binding.get('intent'):
                base_dir = Path(binding['intent']['base_dir'])
            binding['intent'] = {'base_dir': str(Path(base_dir).resolve())}
            self._save(run_id, binding)
            record = RenderRecord.from_dict(binding['record'])
            plan = orphans[0] if orphans else prepare_export(record.artifact_id, record.pdf_path, record.pdf_hash,
                                                           base_dir, company_name, user_full_name)
            try:
                binding['plan'] = plan.to_dict()
                self._save(run_id, binding)
                with self.store.connection(immediate=True) as conn:
                    if self.store.cancellation('run', run_id, conn):
                        raise ReleaseConflict('run_cancelled')
                    if self.store.action('run', run_id, action.action_id, conn) is None:
                        self.store.accept('run', run_id, action.model_dump(mode='json'), content_hash(action), conn)
                    conn.execute('INSERT INTO release_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (run_id, action.review_id, action.action_id, action.content_hash, action.render_hash,
                         action.pdf_hash, str(plan.canonical_pdf_path), str(plan.destination),
                         str(plan.temporary_path), plan.ownership_token, 'approved', utc_now(), None))
                    self.store.update('run', run_id, status='running', pending=None, conn=conn)
            except Exception as exc:
                try:
                    self._cleanup(plan, cancelled=True)
                except (ReleaseConflict, OSError):
                    exc.add_note('Owned reservation cleanup requires explicit recovery.')
                raise
            self._boundary('after_approval')
            return self._continue(run_id, binding, plan)

    def _continue(self, run_id: str, binding: dict, plan: ExportPlan) -> RunView:
        released = self.store.release(run_id)
        action = ReviewPdf(action_id=released['action_id'], decision='approve',
            **{key: released[key] for key in ('review_id', 'content_hash', 'render_hash', 'pdf_hash')})
        self._action(run_id, action, binding)
        with self.store.connection(immediate=True) as conn:
            if self.store.cancellation('run', run_id, conn):
                return self._finish_cancel(run_id, action.action_id, conn, plan)
            conn.execute("UPDATE release_records SET status='exporting' WHERE run_id=?", (run_id,))
        self._boundary('before_copy')
        # After-rename recovery is recognized optimistically here, then proven by
        # commit_export's sidecar/inode/hash validation inside the transaction.
        renamed = (not plan.temporary_path.exists() and plan.destination.exists()
                   and hash_file(plan.destination) == plan.expected_hash)
        if not renamed:
            try:
                prepare_copy(plan, recover=True)
            except ValueError as exc:
                raise ReleaseConflict('export_ownership_conflict') from exc
        self._boundary('after_copy')
        with self.store.connection(immediate=True) as conn:
            if self.store.cancellation('run', run_id, conn):
                return self._finish_cancel(run_id, action.action_id, conn, plan)
            self._action(run_id, action, binding)
            try:
                commit_export(plan)
            except ValueError as exc:
                raise ReleaseConflict('export_ownership_conflict') from exc
            self._boundary('after_rename')
            conn.execute("UPDATE release_records SET status='released',released_at=? WHERE run_id=?",
                         (utc_now(), run_id))
            self.store.update('run', run_id, status='complete', pending=None,
                              result={'result': {'destination': str(plan.destination)}, 'diagnostics': []}, conn=conn)
            result = self._view(run_id, conn)
            self.store.finish_actions('run', run_id, [action.action_id], result.model_dump(mode='json'), conn)
        self._boundary('after_commit')
        try:
            self._cleanup(plan)
        except (ReleaseConflict, OSError):
            # Release is durable and authoritative. Inspection exposes unfinished
            # cleanup; a later explicit recovery may retry without copying.
            pass
        return result

    def recover_unfinished(self, run_id: str, *, continue_export: bool = False,
                           cancel: bool = False, worker_owned: bool = False) -> RunView:
        """Explicit continuation/cancellation only; startup callers use inspect."""
        if continue_export == cancel:
            raise ReleaseConflict('explicit_recovery_decision_required')
        if cancel:
            self.store.cancel('run', run_id)  # never wait for the worker lock
        with nullcontext() if worker_owned else self.store.ownership('run', run_id):
            inspection = self.inspect(run_id)
            if inspection.status == 'complete':
                if inspection.cleanup_pending:
                    try:
                        self._cleanup(self._plan(inspection.release))
                    except (ReleaseConflict, OSError):
                        pass
                with self.store.connection() as conn:
                    action = self.store.action('run', run_id, inspection.release['action_id'], conn)
                    if action and action['result_json']:
                        return RunView.model_validate_json(action['result_json'])
                    return self._view(run_id, conn)
            if inspection.plan is None:
                for orphan in inspection.orphan_plans:
                    self._cleanup(orphan, cancelled=True)
                if not cancel:
                    raise ReleaseConflict('review_action_required')
                with self.store.connection() as conn:
                    return self._view(run_id, conn)
            if cancel or self.store.cancellation('run', run_id):
                with self.store.connection(immediate=True) as conn:
                    return self._finish_cancel(run_id, inspection.release['action_id'], conn, inspection.plan)
            return self._continue(run_id, self._binding(run_id), inspection.plan)

    def get_preview(self, run_id: str) -> bytes:
        binding = self._binding(run_id)
        record = RenderRecord.from_dict(binding['record'])
        self._check(run_id, RenderManifest.model_validate(binding['manifest']), record)
        data = Path(record.pdf_path).read_bytes()
        if hashlib.sha256(data).hexdigest() != record.pdf_hash:
            raise ReleaseConflict('canonical_pdf_mismatch')
        return data

    def get_final(self, run_id: str) -> bytes:
        released = self.store.release(run_id)
        if released is None or released['status'] != 'released':
            raise ReleaseConflict('release_required')
        # Final download authority comes from the released row, including after
        # a crash before any lifecycle checkpoint has been reconciled.
        path = Path(released['canonical_pdf_path'])
        try:
            if path.resolve() != path or hash_file(path) != released['pdf_hash']:
                raise ReleaseConflict('canonical_pdf_mismatch')
            data = path.read_bytes()
        except ValueError as exc:
            raise ReleaseConflict('canonical_pdf_mismatch') from exc
        except OSError as exc:
            raise ReleaseError('released_pdf_unavailable') from exc
        if hashlib.sha256(data).hexdigest() != released['pdf_hash']:
            raise ReleaseConflict('canonical_pdf_mismatch')
        return data

    def _reexport_candidates(self, binding: dict) -> tuple[ExportPlan, ...]:
        """Find only reservations created after this durable action intent."""
        found = []
        for path in Path(binding['base_dir']).rglob('.*.owner.json'):
            try:
                plan = ExportPlan.from_dict(json.loads(path.read_text())['plan'])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if (plan.artifact_id == binding['artifact_id']
                    and plan.ownership_path == path
                    and str(plan.canonical_pdf_path) == binding['canonical_pdf_path']
                    and plan.expected_hash == binding['pdf_hash']
                    and plan.ownership_token not in binding['excluded_tokens']):
                found.append(plan)
        return tuple(found)

    def reexport(self, run_id: str, action_id: str, expected_pdf_hash: str, *,
                 base_dir: Path, company_name: str, user_full_name: str,
                 recover: bool = False) -> dict:
        """Explicitly export approved canonical bytes without replacing approval.

        Each action has its own durable plan and result. Intent precedes filename
        reservation, so explicit recovery also finds a process-death window
        before the plan checkpoint. Final rename and action result share a txn.
        """
        if not isinstance(action_id, str) or not action_id:
            raise ReleaseConflict('action_id_required')
        payload = {'action_id': action_id, 'expected_pdf_hash': expected_pdf_hash,
                   'base_dir': str(Path(base_dir).resolve()), 'company_name': company_name,
                   'user_full_name': user_full_name}
        request_hash = content_hash(payload)
        checkpoint_id = run_id + ':' + action_id
        with self.store.ownership('run', run_id):
            with self.store.connection() as conn:
                previous = self.store.action('run_reexport', run_id, action_id, conn)
                if previous:
                    if previous['request_hash'] != request_hash:
                        raise ReleaseConflict('action_payload_conflict')
                    if previous['result_json'] is not None:
                        if recover:
                            saved = read_v2_checkpoint(self.store.checkpoint_path, 'reexport', checkpoint_id)
                            if saved and 'plan' in saved:
                                plan = ExportPlan.from_dict(saved['plan'])
                                if plan.ownership_path.exists():
                                    self._cleanup(plan)
                        return json.loads(previous['result_json'])
                    if not recover:
                        raise ReleaseConflict('explicit_recovery_required')
                elif self.store.unfinished('run_reexport', run_id, conn):
                    raise ReleaseConflict('explicit_recovery_required')
            released = self.store.release(run_id)
            if not released or released['status'] != 'released':
                raise ReleaseConflict('release_required')
            if released['pdf_hash'] != expected_pdf_hash:
                raise ReleaseConflict('canonical_pdf_mismatch')
            self.get_final(run_id)
            artifact_id = self.store.row('run', run_id)['artifact_id']
            binding = read_v2_checkpoint(self.store.checkpoint_path, 'reexport', checkpoint_id)
            if previous is None:
                with self.store.connection(immediate=True) as conn:
                    self.store.accept('run_reexport', run_id, payload, request_hash, conn)
            if binding is None:
                # Existing reservations belong to the original release or earlier
                # reexports and must never be claimed by this action's recovery.
                binding = {'base_dir': payload['base_dir'], 'artifact_id': artifact_id,
                    'canonical_pdf_path': released['canonical_pdf_path'], 'pdf_hash': expected_pdf_hash,
                    'excluded_tokens': []}
                binding['excluded_tokens'] = [plan.ownership_token for plan in self._reexport_candidates(binding)]
                write_v2_checkpoint(self.store.checkpoint_path, 'reexport', checkpoint_id, binding)
            if (binding['artifact_id'] != artifact_id or binding['canonical_pdf_path'] != released['canonical_pdf_path']
                    or binding['pdf_hash'] != expected_pdf_hash or binding['base_dir'] != payload['base_dir']):
                raise ReleaseConflict('export_plan_mismatch')
            if 'plan' in binding:
                plan = ExportPlan.from_dict(binding['plan'])
            else:
                candidates = self._reexport_candidates(binding)
                if len(candidates) > 1:
                    raise ReleaseConflict('export_ownership_conflict')
                plan = candidates[0] if candidates else prepare_export(artifact_id,
                    released['canonical_pdf_path'], expected_pdf_hash, Path(payload['base_dir']),
                    company_name, user_full_name)
                self._boundary('reexport_after_reservation')
                binding['plan'] = plan.to_dict()
                write_v2_checkpoint(self.store.checkpoint_path, 'reexport', checkpoint_id, binding)
            if (plan.artifact_id != artifact_id or str(plan.canonical_pdf_path) != released['canonical_pdf_path']
                    or plan.expected_hash != expected_pdf_hash
                    or not plan.destination.is_relative_to(Path(payload['base_dir']))):
                raise ReleaseConflict('export_plan_mismatch')
            self._boundary('reexport_after_plan')
            try:
                renamed = (not plan.temporary_path.exists() and plan.destination.exists()
                           and hash_file(plan.destination) == plan.expected_hash)
                if not renamed:
                    prepare_copy(plan, recover=True)
            except (OSError, ValueError) as exc:
                raise ReleaseConflict('export_ownership_conflict') from exc
            self._boundary('reexport_after_copy')
            with self.store.connection(immediate=True) as conn:
                self.get_final(run_id)
                try:
                    commit_export(plan)
                except (OSError, ValueError) as exc:
                    raise ReleaseConflict('export_ownership_conflict') from exc
                self._boundary('reexport_after_rename')
                result = {'status': 'complete', 'run_id': run_id, 'destination': str(plan.destination),
                          'canonical_pdf_path': released['canonical_pdf_path'], 'pdf_hash': expected_pdf_hash}
                self.store.finish_actions('run_reexport', run_id, [action_id], result, conn)
            self._boundary('reexport_after_commit')
            try:
                self._cleanup(plan)
            except (ReleaseConflict, OSError):
                pass  # The durable action result remains authoritative.
            return result

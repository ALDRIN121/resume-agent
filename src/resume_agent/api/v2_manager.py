"""Durable API facade; background tasks are handles, never persistence authority."""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .. import library
from ..checkpoint import read_v2_checkpoint
from ..config import MAX_JD_TEXT_CHARS
from ..contracts import RUN_ACTION_ADAPTER, RunRequest
from .events import now_iso


def typed_action(body):
    if 'payload' in body:
        if (set(body) != {'kind', 'payload'} or not isinstance(body['payload'], dict)
                or 'kind' in body['payload']):
            raise ValueError('invalid_action_envelope')
        body = {'kind': body['kind'], **body['payload']}
    try:
        return RUN_ACTION_ADAPTER.validate_python(body)
    except ValidationError:
        raise ValueError('invalid_typed_action') from None


class V2RunManager:
    def __init__(self, services):
        self.services = services
        self._tasks = {}
        self._jd_files = {}

    def store_jd_file(self, text):
        import uuid
        if not text.strip() or len(text) > MAX_JD_TEXT_CHARS:
            raise ValueError('invalid_jd_input')
        file_id = str(uuid.uuid4())
        self._jd_files[file_id] = text
        return file_id

    async def start_run(self, body):
        alternatives = [key for key in ('jd_text', 'jd_url', 'jd_file_id') if body.get(key)]
        if len(alternatives) != 1:
            raise ValueError('provide_exactly_one_jd_input')
        key = alternatives[0]
        source = body[key]
        if key == 'jd_file_id':
            try:
                source = self._jd_files[source]
            except KeyError:
                raise ValueError('unknown_jd_upload') from None
        if key != 'jd_url' and len(source) > MAX_JD_TEXT_CHARS:
            raise ValueError('jd_input_too_large')
        request = RunRequest(job_input=source, input_type='url' if key == 'jd_url' else 'text',
            max_pages=body.get('max_pages', 2), parent_run_id=body.get('parent_run_id'), job_location=body.get('job_location'), work_mode=body.get('work_mode'))
        view = self.services.create_run(request)
        queued = self.get_run(view.id)
        if key == 'jd_file_id':
            self._jd_files.pop(body[key])
        self._tasks[view.id] = asyncio.create_task(self.services.runs.drive(view.id))
        return queued

    def recover_legacy(self, run_id):
        view = self.services.runs.recover_legacy(run_id, provider=self.services.settings.provider,
                                                model=self.services.settings.model.default)
        result = self.get_run(view.id)
        if view.status == 'queued' and (view.id not in self._tasks or self._tasks[view.id].done()):
            self._tasks[view.id] = asyncio.create_task(self.services.runs.drive(view.id))
        return result

    async def wait(self, run_id):
        task = self._tasks.get(run_id)
        if task is not None:
            await task

    async def resume_run(self, run_id, body):
        action = typed_action(body)
        # Await validation and drive under the shared owner lock; stale decisions
        # return conflict before any new external work can be scheduled.
        view = await self.services.runs.drive(run_id, action)
        return self.get_run(run_id, view=view)

    def get_run(self, run_id, *, view=None):
        try:
            view = view if view is not None else self.services.runs.get(run_id)
        except KeyError:
            record = library.get_resume(run_id, library_path=self.services.store.library_path)
            if record is None:
                raise
            return self._legacy(record)
        row = self.services.store.row('run', run_id)
        fixed = self.services.store.input('run', run_id)
        checkpoint = read_v2_checkpoint(self.services.store.checkpoint_path, 'run', run_id)
        values = checkpoint['values'] if checkpoint else {}
        jd = values.get('jd', {})
        release = view.release
        created = datetime.fromisoformat(row['created_at']).timestamp()
        duration = (datetime.fromisoformat(row['updated_at']) - datetime.fromisoformat(row['created_at'])).total_seconds()
        pdf_url = f'/api/runs/{run_id}/pdf' if release and release.status == 'released' else None
        preview_url = f'/api/runs/{run_id}/preview' if view.pending and view.pending.kind == 'review_pdf' else None
        availability = library.artifact_availability(run_id, library_path=self.services.store.library_path)
        with self.services.store.connection() as conn:
            reexports = self.services.store.unfinished('run_reexport', run_id, conn)
        return view.model_dump(mode='json') | availability | {
            'contract_version': 2, 'thread_id': run_id, 'company': jd.get('company', 'Unknown'),
            'role': jd.get('role_title', 'Unknown'), 'location': jd.get('location', fixed['request'].get('job_location')),
            'work_mode': jd.get('work_mode', fixed['request'].get('work_mode')), 'remote_policy': jd.get('remote_policy'),
            'work_preferences': fixed['profile_snapshot']['work_preferences'],
            'source_revision': fixed['profile_revision'], 'created_at': created,
            'provider': fixed.get('provider'), 'model': fixed.get('model'),
            'review_stats': {
                'questions': len(values['questions']) if 'questions' in values else None,
                'answered': sum(bool(answer.strip()) for answer in values.get('answers', {}).values()) if 'questions' in values else None,
                'suggestions': len(values['snapshot']['proposals']) if 'snapshot' in values else None,
                'approved': len(values['manifest']['approved_proposal_ids']) if 'manifest' in values else None,
            },
            'duration_s': duration, 'duration': f'{int(duration)}s', 'retries': sum(max(0, t['attempts'] - 1) for t in values.get('model_tasks', {}).values()),
            'pdf': Path(release.destination).name if release else None, 'pdf_url': pdf_url,
            'preview_url': preview_url, 'error': view.diagnostics[0].code if view.diagnostics else None,
            'pending_reexport': ({'action_id': reexports[0]['action_id'], 'expected_pdf_hash': release.pdf_hash}
                                 if reexports and release else None),
            'events': [], 'stage': view.pending.kind if view.pending else values.get('stage', view.status),
            'advisories': values.get('advisories', []), 'render_failure': values.get('render_failure'), 'parent_run_id': fixed['request'].get('parent_run_id'),
        }

    @staticmethod
    def _legacy(record):
        run_id = record['thread_id']
        return record | {'id': run_id, 'contract_version': 2, 'legacy': True,
            'pending': None, 'diagnostics': [], 'release': None, 'fixed_input_hashes': {},
            'source_revision': None, 'preview_url': None, 'cancellation_requested': False, 'events': [],
            'pdf_url': record.get('pdf_url')}

    def list_runs(self):
        ids = self.services.store.run_ids()
        result = [self.get_run(run_id) for run_id in ids]
        result.extend(self._legacy(r) for r in library.list_resumes(library_path=self.services.store.library_path)
                      if r['thread_id'] not in ids)
        return sorted(result, key=lambda item: str(item.get('created_at', '')), reverse=True)

    async def cancel(self, run_id):
        self.services.runs.cancel(run_id)
        return self.get_run(run_id)

    async def subscribe(self, run_id):
        # Always reconstruct a fresh snapshot, including after a process restart.
        state = self.get_run(run_id)
        yield {'type': 'run_state', 'ts': now_iso(), 'run': state}
        if state.get('legacy'):
            if state['status'] == 'complete':
                yield {'type': 'complete', 'ts': now_iso(), 'pdf_url': state.get('pdf_url'),
                       'duration_s': state.get('duration_s') or 0, 'artifact_status': state['artifact_status']}
            elif state['status'] in ('failed', 'cancelled'):
                yield {'type': 'failed', 'ts': now_iso(), 'reason': state.get('error') or state['status']}
            return
        async for event in self.services.runs.subscribe(run_id):
            state = self.get_run(run_id)
            yield {'type': 'run_state', 'ts': now_iso(), 'run': state}
            pending = state.get('pending')
            if pending:
                payload = pending.get('payload', {})
                yield {'type': 'hitl_pending', 'ts': now_iso(), 'kind': pending['kind'],
                       'questions': payload.get('questions', []), 'suggestions': payload.get('proposals', []),
                       'pending': pending, 'review': pending.get('review'), 'run_id': run_id,
                       'preview_url': state['preview_url']}
            if state['status'] == 'complete':
                yield {'type': 'complete', 'ts': now_iso(), 'pdf_url': state['pdf_url'], 'duration_s': state['duration_s'],
                       'artifact_status': state['artifact_status'], 'release': state['release'],
                       **{k: state['release'][k] for k in ('content_hash', 'render_hash', 'pdf_hash')}}
                return
            elif state['status'] in ('failed', 'cancelled'):
                yield {'type': 'failed', 'ts': now_iso(), 'reason': state['error'] or state['status']}
                return

    async def shutdown(self):
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

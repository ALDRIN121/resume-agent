"""Explicit local application events; document generation never records submission."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field, TypeAdapter, field_validator, model_validator

from .contracts import Contract, Hash, Identifier, canonical_json, content_hash, utc_now
from .library import _artifact_available
from .run_store import Conflict

Stage = Literal['planned', 'submitted', 'screening', 'interviewing', 'offer', 'rejected', 'withdrawn', 'closed']
Reason = Annotated[str, Field(min_length=1, max_length=48000, pattern=r'\S')]
_RANK = dict(planned=0, submitted=1, screening=2, interviewing=3, offer=4, rejected=5, withdrawn=5, closed=5)


class Occurrence(Contract):
    occurred_at: str | None = None

    @field_validator('occurred_at')
    @classmethod
    def known_date_or_instant(cls, value):
        if value is not None:
            if len(value) == 10:
                date.fromisoformat(value)
            elif datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
                raise ValueError('timestamp_timezone_required')
        return value


class SubmissionEvent(Occurrence):
    kind: Literal['submit'] = 'submit'
    artifact_run_id: Identifier | None = None
    artifact_unknown: bool = False
    evaluation_id: Identifier | None = None

    @model_validator(mode='after')
    def explicit_artifact_choice(self):
        if bool(self.artifact_run_id) == self.artifact_unknown:
            raise ValueError('choose_released_artifact_or_explicit_unknown')
        return self


class StageEvent(Occurrence):
    kind: Literal['stage_change'] = 'stage_change'
    stage: Literal['screening', 'interviewing', 'offer', 'rejected', 'withdrawn', 'closed']
    closure_without_response: bool = False

    @model_validator(mode='after')
    def explicit_closure_only(self):
        if self.closure_without_response and self.stage != 'closed':
            raise ValueError('closure_confirmation_requires_closed_stage')
        return self


class ResponseEvent(Occurrence):
    kind: Literal['response_received'] = 'response_received'
    category: Literal['acknowledgment', 'rejection', 'favorable', 'other']


class ReopenEvent(Occurrence):
    kind: Literal['reopen'] = 'reopen'
    stage: Literal['planned', 'submitted', 'screening', 'interviewing', 'offer']
    reason: Reason


ProgressEvent = Annotated[SubmissionEvent | StageEvent | ResponseEvent | ReopenEvent, Field(discriminator='kind')]


class CorrectionEvent(Occurrence):
    kind: Literal['correction'] = 'correction'
    target_event_id: Identifier
    reason: Reason
    replacement: ProgressEvent | None = None


ApplicationEvent = Annotated[SubmissionEvent | StageEvent | ResponseEvent | ReopenEvent | CorrectionEvent, Field(discriminator='kind')]
EVENT_ADAPTER = TypeAdapter(ApplicationEvent)


class Application(Contract):
    id: str
    job_id: str
    company: str | None
    role: str | None
    created_at: str


class ApplicationEventRequest(Contract):
    action_id: Identifier
    expected_revision: Hash
    event: ApplicationEvent


def effective_events(events):
    """Keep raw audit untouched; apply explicit corrections at original positions."""
    originals = {event['id']: event for event in events if event['payload']['kind'] != 'correction'}
    corrections = {}
    for event in events:
        payload = event['payload']
        if payload['kind'] == 'correction':
            if payload['target_event_id'] not in originals:
                raise Conflict('correction_requires_original_event_in_same_application')
            corrections[payload['target_event_id']] = event
    result = []
    for event in originals.values():
        correction = corrections.get(event['id'])
        if correction:
            replacement = correction['payload']['replacement']
            if replacement is not None:
                result.append(event | {'payload': replacement, 'binding': correction['binding'], 'corrected_by': correction['id']})
        else:
            result.append(event | {'corrected_by': None})
    return result


def project_progress(events):
    stage, submission = 'planned', None
    effective = effective_events(events)
    for event in effective:
        payload = event['payload']
        if payload['kind'] == 'submit':
            if submission is not None:
                raise Conflict('one_submission_per_attempt')
            submission = {**event['binding']['submission'], 'event_id': event['id'], 'occurred_at': payload['occurred_at']}
            if stage == 'planned':
                stage = 'submitted'
        elif payload['kind'] == 'reopen':
            stage = payload['stage']
        elif payload['kind'] == 'stage_change':
            if _RANK[payload['stage']] < _RANK[stage]:
                raise Conflict('backward_progress_requires_reopen_or_correction')
            stage = payload['stage']
        elif payload['kind'] == 'response_received' and payload['category'] == 'rejection':
            stage = 'rejected'
    return stage, submission, effective


class ApplicationService:
    def __init__(self, store, jobs, evaluations):
        self.store, self.jobs, self.evaluations = store, jobs, evaluations

    def _read(self, application_id, conn):
        row = conn.execute('SELECT document FROM applications WHERE id=?', (application_id,)).fetchone()
        if row is None:
            raise KeyError(application_id)
        base = json.loads(row[0])
        events = [dict(id=row['id'], seq=row['seq'], payload=json.loads(row['payload_json']),
                       binding=json.loads(row['binding_json']), recorded_at=row['recorded_at']) for row in conn.execute(
                           'SELECT * FROM application_events WHERE application_id=? ORDER BY seq', (application_id,))]
        return base, events

    def _view(self, base, events):
        stage, submission, effective = project_progress(events)
        revision = content_hash({'application': base, 'events': events})
        if submission and submission['artifact']:
            artifact = submission['artifact']
            submission['artifact'] = artifact | {'available': _artifact_available(artifact['canonical_pdf_path'], artifact['pdf_hash'])}
        return base | {'revision': revision, 'stage': stage, 'submission': submission, 'events': events, 'effective_events': effective}

    def get(self, application_id):
        with self.store.connection() as conn:
            return self._view(*self._read(application_id, conn))

    def list(self):
        with self.store.connection() as conn:
            ids = [row[0] for row in conn.execute('SELECT id FROM applications ORDER BY rowid DESC')]
        return [self.get(application_id) for application_id in ids]

    def _replay(self, scope, owner_id, action_id, request_hash, conn):
        previous = self.store.action(scope, owner_id, action_id, conn)
        if previous:
            if previous['request_hash'] != request_hash:
                raise Conflict('action_payload_conflict')
            if previous['result_json'] is None:
                raise Conflict('application_action_incomplete')
            return json.loads(previous['result_json'])
        return None

    def _finish(self, scope, owner_id, action_id, result, conn):
        conn.execute("UPDATE actions SET status='complete',result_json=? WHERE owner_kind=? AND owner_id=? AND action_id=?",
                     (canonical_json(result), scope, owner_id, action_id))
        return result

    def create(self, job_id, *, action_id, company=None):
        if not isinstance(action_id, str) or not action_id or (company is not None and (not isinstance(company, str) or not company.strip())):
            raise ValueError('invalid_application_creation')
        job = self.jobs.get(job_id)
        request = {'job_id': job_id, 'action_id': action_id, 'company': company}
        digest = content_hash(request)
        with self.store.connection(immediate=True) as conn:
            replay = self._replay('application_create', job_id, action_id, digest, conn)
            if replay:
                return replay
            base = Application(id=str(uuid4()), job_id=job_id, company=company or job.company, role=job.role,
                               created_at=utc_now()).model_dump(mode='json')
            self.store.accept('application_create', job_id, request, digest, conn)
            conn.execute('INSERT INTO applications VALUES (?,?,?)', (base['id'], job_id, canonical_json(base)))
            if base['company']:
                conn.execute("INSERT OR IGNORE INTO company_references VALUES (?,'application',?)", (base['company'], base['id']))
            return self._finish('application_create', job_id, action_id, self._view(base, []), conn)

    def _submission(self, payload, base):
        artifact = None
        if payload['artifact_run_id']:
            released = self.store.release(payload['artifact_run_id'])
            if not released or released['status'] != 'released':
                raise Conflict('selected_artifact_must_be_released')
            fixed = self.store.input('run', payload['artifact_run_id'])
            selected_job = self.jobs.get(base['job_id'])
            matches = (fixed['request']['job_id'] == base['job_id'] if fixed['request'].get('job_id') else
                       content_hash(fixed['request']['job_input']) == selected_job.content_hash)
            artifact = {key: released[key] for key in ('review_id', 'content_hash', 'render_hash', 'pdf_hash', 'canonical_pdf_path', 'destination')}
            artifact.update(run_id=payload['artifact_run_id'], job_match=matches)
        evaluation = None
        if payload['evaluation_id']:
            selected = self.evaluations.get(payload['evaluation_id'])
            if selected['status'] != 'complete' or selected['result'] is None or selected['job_id'] != base['job_id']:
                raise Conflict('matching_completed_evaluation_required')
            result = selected['result']
            exact = result['fit']['exact']
            evaluation = {'id': selected['id'], 'lower_exact': exact['lower'] if exact else None,
                          'fit': result['fit'], 'rubric_version': result['rubric_version'],
                          'input_identities': selected['fixed_identities'], 'stale_at_recording': selected['stale'],
                          'provider': result['provider'], 'model': result['model']}
        return {'artifact': artifact, 'artifact_unknown': payload['artifact_unknown'], 'evaluation': evaluation}

    def append(self, application_id, payload, *, expected_revision, action_id):
        typed = ApplicationEventRequest(action_id=action_id, expected_revision=expected_revision, event=EVENT_ADAPTER.validate_python(payload))
        request = typed.model_dump(mode='json')
        digest = content_hash(request)
        with self.store.ownership('operation', 'application:' + application_id):
            with self.store.connection() as conn:
                replay = self._replay('application_event', application_id, action_id, digest, conn)
                if replay:
                    return replay
                base, events = self._read(application_id, conn)
                if self._view(base, events)['revision'] != expected_revision:
                    raise Conflict('application_revision_changed')
            event = request['event']
            binding = {}
            active_payload = event['replacement'] if event['kind'] == 'correction' else event
            if active_payload and active_payload['kind'] == 'submit':
                binding['submission'] = self._submission(active_payload, base)
            with self.store.connection(immediate=True) as conn:
                base, events = self._read(application_id, conn)
                if self._view(base, events)['revision'] != expected_revision:
                    raise Conflict('application_revision_changed')
                self.store.accept('application_event', application_id, {'action_id': action_id, **request}, digest, conn)
                conn.execute('INSERT INTO application_events(id,application_id,payload_json,binding_json,recorded_at) VALUES (?,?,?,?,?)',
                             (str(uuid4()), application_id, canonical_json(event), canonical_json(binding), utc_now()))
                result = self._view(*self._read(application_id, conn))
                return self._finish('application_event', application_id, action_id, result, conn)

"""Explicit durable corrections, with a journal across SQLite and profile YAML."""
from __future__ import annotations

import copy
import json
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field, JsonValue, model_validator

from .content_review import pointer_parts, resolve_pointer
from .contracts import Contract, Hash, canonical_json, content_hash, utc_now
from .profile_store import ProfileConflictError
from .run_store import Conflict
from .schemas import UserResume, WorkMode

Text = Annotated[str, Field(min_length=1, max_length=48000)]
UUID = Annotated[str, Field(pattern=r'^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$')]


class MemorySource(Contract):
    kind: Literal['user_text', 'confirmed_source']
    text: Text


class FactChange(Contract):
    operation: Literal['replace', 'append']
    target_path: Text
    before_hash: Hash
    after: JsonValue


class HardConstraint(Contract):
    category: Literal['authorization', 'clearance', 'presence', 'other']
    value: Text
    text: Text


class TargetPreference(Contract):
    preferred_locations: list[Text] = Field(default_factory=list)
    work_modes: list[WorkMode] = Field(default_factory=list)
    hard_constraints: list[HardConstraint] = Field(default_factory=list)


class WritingRule(Contract):
    instruction: Text


PAYLOAD_TYPES = {'candidate_fact': FactChange, 'target_preference': TargetPreference, 'writing_rule': WritingRule}


class Supersedes(Contract):
    id: UUID
    revision: Hash


class MemoryProposal(Contract):
    kind: Literal['candidate_fact', 'target_preference', 'writing_rule']
    payload: dict[str, JsonValue]
    source_refs: Annotated[list[MemorySource], Field(min_length=1)]
    source_run: UUID | None = None
    base_profile_revision: Hash | None = None
    supersedes: Supersedes | None = None

    @model_validator(mode='after')
    def typed_payload(self):
        PAYLOAD_TYPES[self.kind].model_validate(self.payload)
        if self.kind == 'candidate_fact' and (self.base_profile_revision is None or self.supersedes):
            raise ValueError('fact_requires_current_profile_and_cannot_supersede')
        return self


class MemoryRecord(MemoryProposal):
    id: UUID
    status: Literal['pending', 'applying', 'accepted', 'rejected', 'revoked', 'superseded', 'conflict']
    created_at: str
    projection: dict[str, JsonValue] | None = None
    promotion: dict[str, JsonValue] | None = None


class MemorySnapshotEntry(Contract):
    id: UUID
    revision: Hash
    kind: Literal['target_preference', 'writing_rule']
    payload: dict[str, JsonValue]
    source_refs: list[MemorySource]

    @model_validator(mode='after')
    def typed_payload(self):
        PAYLOAD_TYPES[self.kind].model_validate(self.payload)
        return self


class MemorySnapshot(Contract):
    schema_version: Literal[1] = 1
    records: list[MemorySnapshotEntry]

    @model_validator(mode='after')
    def ordered_unique(self):
        ids = [r.id for r in self.records]
        if ids != sorted(set(ids)):
            raise ValueError('memory_records_must_be_unique_and_sorted')
        return self


def _view(document):
    return document | {'revision': content_hash(document)}


class MemoryService:
    def __init__(self, store, profiles, *, crash_hook=None):
        self.store, self.profiles, self.crash_hook = store, profiles, crash_hook
        try:
            self.reconcile()
        except Conflict as exc:
            if str(exc) != 'owner_busy':
                raise

    def _boundary(self, stage):
        if self.crash_hook:
            self.crash_hook(stage)

    def _read(self, record_id, conn):
        row = conn.execute('SELECT document FROM memory_records WHERE id=?', (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return json.loads(row[0])

    def _write(self, document, conn):
        MemoryRecord.model_validate(document)
        conn.execute('UPDATE memory_records SET document=? WHERE id=?', (canonical_json(document), document['id']))

    def get(self, record_id):
        with self.store.connection() as conn:
            return _view(self._read(record_id, conn))

    def list(self):
        with self.store.connection() as conn:
            return [_view(json.loads(r[0])) for r in conn.execute('SELECT document FROM memory_records ORDER BY id')]

    def history(self, record_id):
        with self.store.connection() as conn:
            self._read(record_id, conn)
            return [dict(row) for row in conn.execute('SELECT * FROM memory_decisions WHERE record_id=? ORDER BY recorded_at,action_id', (record_id,))]

    def snapshot(self):
        # Candidate facts are already in the profile; never overlay them again.
        entries = [{key: r[key] for key in ('id', 'revision', 'kind', 'payload', 'source_refs')}
                   for r in self.list() if r['status'] == 'accepted' and r['kind'] != 'candidate_fact']
        return MemorySnapshot(records=entries).model_dump(mode='json')

    def _projection(self, proposal):
        current = self.profiles.load_snapshot()
        if current is None or current.review_required or current.revision != proposal['base_profile_revision']:
            raise Conflict('profile_revision_changed')
        source = current.profile.model_dump(mode='json')
        change = FactChange.model_validate(proposal['payload'])
        parts = pointer_parts(change.target_path)
        if not parts or parts[0] == 'work_preferences':
            raise ValueError('unsupported_fact_target')
        before = resolve_pointer(source, change.target_path)
        if content_hash(before) != change.before_hash:
            raise Conflict('fact_before_hash_changed')
        projected = copy.deepcopy(source)
        if change.operation == 'append':
            target = resolve_pointer(projected, change.target_path)
            if not isinstance(target, list):
                raise ValueError('append_requires_existing_list')
            target.append(change.after)
        else:
            parent = projected
            for part in parts[:-1]:
                parent = parent[int(part)] if isinstance(parent, list) else parent[part]
            key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
            parent[key] = change.after
        validated = UserResume.model_validate(projected).model_dump(mode='json')
        # Reject aliases, dropped fields or coercion instead of hiding a broader edit.
        if validated != projected:
            raise ValueError('fact_change_must_be_exact')
        return {'before': before, 'after': resolve_pointer(validated, change.target_path),
                'profile_before': source, 'profile_after': validated,
                'old_hash': current.revision, 'proposed_hash': content_hash(validated)}

    def propose(self, body):
        proposal = MemoryProposal.model_validate(body).model_dump(mode='json')
        if proposal['source_run']:
            self.store.row('run', proposal['source_run'])
        projection = self._projection(proposal) if proposal['kind'] == 'candidate_fact' else None
        with self.store.ownership('operation', 'memory-decisions'), self.store.connection(immediate=True) as conn:
            if proposal['supersedes']:
                self._check_supersedes(proposal, conn)
            document = MemoryRecord(**proposal, id=str(uuid4()), status='pending', created_at=utc_now(), projection=projection).model_dump(mode='json')
            conn.execute('INSERT INTO memory_records VALUES (?,?)', (document['id'], canonical_json(document)))
            return _view(document)

    def preview(self, record_id):
        record = self.get(record_id)
        projection = (record.get('projection') or record['promotion'] or self._projection(record)) if record['kind'] == 'candidate_fact' else {'before': None, 'after': record['payload']}
        current = self.profiles.load_snapshot() if record['kind'] == 'candidate_fact' else None
        stale = record['kind'] == 'candidate_fact' and record['status'] == 'pending' and (
            current is None or current.review_required or current.revision != record['base_profile_revision'])
        return {'record': record, **projection, 'stale': stale}

    def _check_supersedes(self, record, conn):
        binding = record['supersedes']
        old = self._read(binding['id'], conn)
        if old['kind'] != record['kind'] or old['status'] != 'accepted' or content_hash(old) != binding['revision']:
            raise Conflict('superseded_record_changed')
        return old

    def _finish(self, record, action_id, conn):
        if record['supersedes']:
            old = self._check_supersedes(record, conn)
            self._write(old | {'status': 'superseded'}, conn)
        record['status'] = 'accepted'
        self._write(record, conn)
        result = _view(record)
        self.store.finish_actions('memory', record['id'], [action_id], result, conn)
        return result

    def _recover_record(self, record, conn):
        promotion = record['promotion']
        try:
            current = self.profiles.load_snapshot()
        except (ValueError, OSError):
            current = None
        if current and not current.review_required and current.revision == promotion['proposed_hash']:
            return self._finish(record, promotion['action_id'], conn)
        if not current or current.review_required or current.revision != promotion['old_hash']:
            self._write(record | {'status': 'conflict'}, conn)
        return None

    def reconcile(self):
        with self.store.ownership('operation', 'memory-decisions'), self.store.connection(immediate=True) as conn:
            for row in conn.execute('SELECT document FROM memory_records').fetchall():
                record = json.loads(row[0])
                if record['status'] == 'applying':
                    self._recover_record(record, conn)

    def decide(self, record_id, decision, *, expected_revision, action_id):
        if decision not in ('accept', 'reject', 'revoke') or not isinstance(action_id, str) or not action_id:
            raise ValueError('invalid_memory_decision')
        request = {'decision': decision, 'expected_revision': expected_revision, 'action_id': action_id}
        request_hash = content_hash(request)
        self.reconcile()
        with self.store.ownership('operation', 'memory-decisions'):
            with self.store.connection(immediate=True) as conn:
                previous = self.store.action('memory', record_id, action_id, conn)
                if previous and previous['request_hash'] != request_hash:
                    raise Conflict('action_payload_conflict')
                if previous and previous['result_json'] is not None:
                    return json.loads(previous['result_json'])
                record = self._read(record_id, conn)
                if previous:
                    if record['status'] != 'applying':
                        raise Conflict('profile_promotion_conflict')
                    recovered = self._recover_record(record, conn)
                    if recovered:
                        return recovered
                    if self._read(record_id, conn)['status'] == 'conflict':
                        raise Conflict('profile_promotion_conflict')
                else:
                    if content_hash(record) != expected_revision:
                        raise Conflict('memory_revision_changed')
                    if decision == 'revoke':
                        if record['kind'] == 'candidate_fact' or record['status'] != 'accepted':
                            raise Conflict('new_reviewed_fact_proposal_required')
                    elif record['status'] != 'pending':
                        raise Conflict('memory_not_pending')
                    if decision == 'accept' and record['supersedes']:
                        self._check_supersedes(record, conn)
                    if decision == 'accept' and record['kind'] == 'candidate_fact':
                        projection = self._projection(record)
                        record.update(status='applying', promotion={**projection, 'action_id': action_id})
                    self.store.accept('memory', record_id, request, request_hash, conn)
                    conn.execute('INSERT INTO memory_decisions VALUES (?,?,?,?,?)',
                                 (record_id, action_id, decision, canonical_json(request), utc_now()))
                    if record['status'] == 'applying':
                        self._write(record, conn)
                    else:
                        if decision == 'accept':
                            return self._finish(record, action_id, conn)
                        record['status'] = 'rejected' if decision == 'reject' else 'revoked'
                        self._write(record, conn)
                        result = _view(record)
                        self.store.finish_actions('memory', record_id, [action_id], result, conn)
                        return result
            # Applying intent and the exact reviewed profile are durable before YAML.
            promotion = record['promotion']
            self._boundary('before_profile_write')
            try:
                self.profiles.save_reviewed(promotion['old_hash'], promotion['profile_after'],
                    {'memory_id': record_id, 'action_id': action_id, 'source_run': record['source_run']})
            except ProfileConflictError:
                with self.store.connection(immediate=True) as conn:
                    result = self._recover_record(record, conn)
                    if result:
                        return result
                raise Conflict('profile_revision_changed') from None
            self._boundary('after_profile_write')
            with self.store.connection(immediate=True) as conn:
                return self._finish(record, action_id, conn)

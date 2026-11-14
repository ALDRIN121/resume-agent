"""Durable manual scans; incomplete or old evidence cannot erase newer postings."""
from __future__ import annotations

import asyncio
import json
import time
import unicodedata
from itertools import islice
from uuid import uuid4

from .. import __version__
from ..contracts import canonical_json, content_hash, utc_now
from ..run_store import Conflict
from .http import BoundedHttpClient
from .journal import RequestJournal
from .providers import fetch_board
from .schemas import DiscoverySource, ScanCancelledError, SourceInput

TERMINAL = {'complete', 'partial', 'failed', 'empty', 'cancelled'}
POLICY = {'boards': 20, 'records_per_board': 1000, 'concurrent_requests': 3, 'request_seconds': 20,
          'decoded_body_bytes': 10 * 1024 * 1024, 'attempts': 3, 'retry_after_seconds': 60, 'redirects': 5}


class DiscoveryService:
    def __init__(self, store, jobs, *, http_factory=BoundedHttpClient, clock=time.time, sleep=asyncio.sleep, crash_hook=None):
        self.store, self.jobs = store, jobs
        self.http_factory, self.clock, self.sleep, self.crash_hook = http_factory, clock, sleep, crash_hook
        with self.store.connection() as conn:
            running = [r[0] for r in conn.execute("SELECT id FROM discovery_syncs WHERE status='running'")]
        for sync_id in running:
            self._reconcile(sync_id)

    def _boundary(self, name):
        if self.crash_hook:
            self.crash_hook(name)

    def _action(self, scope, owner, action_id, digest, conn):
        previous = self.store.action(scope, owner, action_id, conn)
        if previous:
            if previous['request_hash'] != digest:
                raise Conflict('action_payload_conflict')
            if previous['result_json'] is not None:
                return json.loads(previous['result_json'])
        return None

    def _finish(self, scope, owner, action_id, result, conn):
        conn.execute("UPDATE actions SET status='complete',result_json=? WHERE owner_kind=? AND owner_id=? AND action_id=?",
                     (canonical_json(result), scope, owner, action_id))
        return result

    @staticmethod
    def _action_id(action_id):
        if not isinstance(action_id, str) or not action_id:
            raise ValueError('action_id_required')

    def _sources(self, conn):
        row = conn.execute('SELECT document FROM discovery_config WHERE singleton=1').fetchone()
        fixed = json.loads(row[0]) if row else {'schema_version': 1, 'sources': []}
        return fixed | {'revision': content_hash(fixed)}

    def sources(self):
        with self.store.connection() as conn:
            return self._sources(conn)

    def replace_sources(self, sources, *, expected_revision, action_id):
        self._action_id(action_id)
        if not isinstance(sources, list) or len(sources) > 20:
            raise ValueError('discovery_source_limit')
        inputs = [SourceInput.model_validate(s).model_dump(mode='json') for s in sources]
        identities = [content_hash([s['provider'], s['region'], s['board']]) for s in inputs]
        ids = [s['id'] for s in inputs if s['id'] is not None]
        if len(identities) != len(set(identities)) or len(ids) != len(set(ids)):
            raise ValueError('duplicate_discovery_source')
        request = {'action_id': action_id, 'expected_revision': expected_revision, 'sources': inputs}
        digest = content_hash(request)
        with self.store.connection(immediate=True) as conn:
            replay = self._action('discovery_config', 'sources', action_id, digest, conn)
            if replay:
                return replay
            if self._sources(conn)['revision'] != expected_revision:
                raise Conflict('discovery_config_changed')
            normalized = []
            for item, identity in zip(inputs, identities):
                existing = conn.execute('SELECT id,identity FROM discovery_sources WHERE identity=?', (identity,)).fetchone()
                if item['id']:
                    original = conn.execute('SELECT identity FROM discovery_sources WHERE id=?', (item['id'],)).fetchone()
                    if original is None or original[0] != identity:
                        raise Conflict('source_identity_requires_new_source')
                source_id = existing['id'] if existing else str(uuid4())
                if item['id'] and item['id'] != source_id:
                    raise Conflict('source_identity_conflict')
                source = DiscoverySource.model_validate(item | {'id': source_id}).model_dump(mode='json')
                conn.execute('INSERT INTO discovery_sources VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
                             (source_id, identity, canonical_json(source)))
                normalized.append(source)
            fixed = {'schema_version': 1, 'sources': sorted(normalized, key=lambda s: s['id'])}
            self.store.accept('discovery_config', 'sources', request, digest, conn)
            conn.execute('INSERT INTO discovery_config VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET document=excluded.document',
                         (canonical_json(fixed),))
            return self._finish('discovery_config', 'sources', action_id, fixed | {'revision': content_hash(fixed)}, conn)

    def _row(self, sync_id, conn):
        row = conn.execute('SELECT * FROM discovery_syncs WHERE id=?', (sync_id,)).fetchone()
        if row is None:
            raise KeyError(sync_id)
        return dict(row)

    def _view(self, sync_id, conn):
        row = self._row(sync_id, conn)
        fixed = json.loads(row['input_json'])
        stored = {r['source_id']: json.loads(r['result_json']) for r in conn.execute('SELECT * FROM discovery_boards WHERE sync_id=?', (sync_id,))}
        boards = [stored.get(source['id'], {'source_id': source['id'], 'source': source, 'status': 'pending', 'diagnostics': []}) for source in fixed['sources']]
        attempts = conn.execute('SELECT coalesce(sum(attempts),0) FROM discovery_requests WHERE sync_id=?', (sync_id,)).fetchone()[0]
        return {'id': sync_id, 'status': row['status'], 'sources_revision': fixed['sources_revision'], 'source_count': len(boards),
                'boards': boards, 'completed_boards': len(stored), 'request_attempts': attempts, 'policy': fixed['policy'],
                'cancellation_requested': self.store.cancellation('discovery', sync_id, conn),
                'created_at': row['created_at'], 'updated_at': row['updated_at'],
                'diagnostics': ['no_enabled_sources'] if not boards else []}

    def create_sync(self, *, expected_sources_revision, action_id, source_ids=None):
        self._action_id(action_id)
        if source_ids is not None and (not isinstance(source_ids, list) or any(not isinstance(i, str) for i in source_ids)
                                       or len(source_ids) != len(set(source_ids))):
            raise ValueError('invalid_selected_sources')
        request = {'expected_sources_revision': expected_sources_revision, 'action_id': action_id,
                   'source_ids': sorted(source_ids) if source_ids is not None else None}
        digest = content_hash(request)
        with self.store.connection(immediate=True) as conn:
            replay = self._action('discovery_create', 'sync', action_id, digest, conn)
            if replay:
                return replay
            configuration = self._sources(conn)
            if configuration['revision'] != expected_sources_revision:
                raise Conflict('discovery_config_changed')
            enabled = [s for s in configuration['sources'] if s['enabled']]
            if source_ids is not None and set(source_ids) - {s['id'] for s in enabled}:
                raise Conflict('selected_source_not_enabled')
            selected = enabled if source_ids is None else [s for s in enabled if s['id'] in source_ids]
            now, sync_id = utc_now(), str(uuid4())
            fixed = {'schema_version': 1, 'policy_version': 1, 'parser_version': 'public-board-text-v1', 'policy': POLICY,
                     'sources': selected, 'sources_revision': configuration['revision'], 'app_version': __version__}
            self.store.accept('discovery_create', 'sync', request, digest, conn)
            conn.execute('INSERT INTO discovery_syncs VALUES (?,?,?,?,?,?)',
                         (sync_id, canonical_json(fixed), 'queued' if selected else 'empty', None, now, now))
            return self._finish('discovery_create', 'sync', action_id, self._view(sync_id, conn), conn)

    def _reconcile(self, sync_id):
        with self.store.connection() as conn:
            if self._row(sync_id, conn)['status'] != 'running':
                return
        try:
            with self.store.ownership('operation', 'discovery:' + sync_id), self.store.connection(immediate=True) as conn:
                conn.execute("UPDATE discovery_syncs SET status='interrupted',updated_at=? WHERE id=? AND status='running'", (utc_now(), sync_id))
        except Conflict as exc:
            if str(exc) != 'owner_busy':
                raise

    def get_sync(self, sync_id):
        self._reconcile(sync_id)
        with self.store.connection() as conn:
            return self._view(sync_id, conn)

    def list_syncs(self):
        with self.store.connection() as conn:
            ids = [row[0] for row in conn.execute('SELECT id FROM discovery_syncs ORDER BY rowid DESC')]
        return [self.get_sync(sync_id) for sync_id in ids]

    def _check_cancel(self, sync_id):
        if self.store.cancellation('discovery', sync_id):
            raise ScanCancelledError()

    def cancel(self, sync_id, *, action_id):
        self._action_id(action_id)
        request = {'action_id': action_id, 'kind': 'cancel'}
        digest = content_hash(request)
        with self.store.connection(immediate=True) as conn:
            replay = self._action('discovery_cancel', sync_id, action_id, digest, conn)
            if replay:
                return replay
            row = self._row(sync_id, conn)
            self.store.accept('discovery_cancel', sync_id, request, digest, conn)
            if row['status'] not in TERMINAL:
                conn.execute("INSERT OR IGNORE INTO cancellations VALUES ('discovery',?,?,?)", (sync_id, action_id, utc_now()))
                if row['status'] in ('queued', 'interrupted'):
                    conn.execute("UPDATE discovery_syncs SET status='cancelled',updated_at=? WHERE id=?", (utc_now(), sync_id))
            return self._finish('discovery_cancel', sync_id, action_id, self._view(sync_id, conn), conn)

    def _apply_board(self, sync_id, source, result):
        with self.store.connection(immediate=True) as conn:
            if self.store.cancellation('discovery', sync_id, conn):
                raise ScanCancelledError()
            if conn.execute('SELECT 1 FROM discovery_boards WHERE sync_id=? AND source_id=?', (sync_id, source.id)).fetchone():
                return
            previous = conn.execute('SELECT document FROM discovery_source_state WHERE source_id=?', (source.id,)).fetchone()
            state = json.loads(previous[0]) if previous else {}
            last_applied = state.get('last_applied_observation_order', 0)
            stale_page = result.first_observation_order is not None and result.first_observation_order < last_applied
            applied, ignored = 0, 0
            applied_orders = []
            for posting in result.jobs:
                order = posting.observation_order
                if order is None or posting.observed_at is None:
                    raise RuntimeError('posting_observation_proof_required')
                current = conn.execute('SELECT * FROM discovery_postings WHERE source_id=? AND external_id=?',
                                       (source.id, posting.external_id)).fetchone()
                watermark = max(state.get('last_complete_observation_order', 0),
                                current['last_seen_order'] if current else 0, (current['removed_order'] or 0) if current else 0)
                if order < watermark:
                    ignored += 1
                    continue
                job = self.jobs.capture(posting.text, source_kind='discovery', source_key='public-board:' + source.id + ':' + posting.external_id,
                    source_url=posting.source_url, company=source.company, role=posting.title, connection=conn)
                conn.execute('INSERT OR IGNORE INTO discovery_posting_versions VALUES (?,?,?,?,?,?)',
                             (source.id, posting.external_id, posting.raw_hash, job.id, canonical_json(posting.raw), posting.observed_at))
                conn.execute("INSERT INTO discovery_postings VALUES (?,?,?,?,'active',?,?,?,?,NULL,NULL,NULL) "
                    "ON CONFLICT(source_id,external_id) DO UPDATE SET job_id=excluded.job_id,raw_hash=excluded.raw_hash,state='active',"
                    'last_seen_at=excluded.last_seen_at,last_seen_sync=excluded.last_seen_sync,last_seen_order=excluded.last_seen_order,'
                    'removed_at=NULL,removed_sync=NULL,removed_order=NULL',
                    (source.id, posting.external_id, job.id, posting.raw_hash, posting.observed_at, posting.observed_at, sync_id, order))
                applied += 1
                applied_orders.append(order)
            summary = result.model_dump(mode='json', exclude={'jobs'}) | {'source_id': source.id, 'source': source.model_dump(mode='json'),
                'applied_count': applied, 'ignored_stale_count': ignored}
            if stale_page or ignored:
                if summary['status'] == 'complete':
                    summary['status'] = 'partial'
                summary['diagnostics'] = [*summary['diagnostics'], 'stale_cached_observations_ignored']
            if summary['status'] == 'complete':
                if result.last_observation_order is None or result.observed_at is None:
                    raise RuntimeError('complete_board_observation_required')
                conn.execute("UPDATE discovery_postings SET state='removed',removed_at=?,removed_sync=?,removed_order=? "
                    "WHERE source_id=? AND state='active' AND last_seen_sync!=?",
                    (result.observed_at, sync_id, result.last_observation_order, source.id, sync_id))
                state.update(last_complete_sync=sync_id, last_complete_at=result.observed_at,
                             last_complete_observation_order=result.last_observation_order)
                applied_orders.append(result.last_observation_order)
            if applied_orders:
                state['last_applied_observation_order'] = max(last_applied, *applied_orders)
            activity = conn.execute('SELECT seq,recorded_at FROM discovery_activity WHERE sync_id=? AND source_id=? ORDER BY seq DESC LIMIT 1',
                                    (sync_id, source.id)).fetchone()
            if activity and activity['seq'] >= state.get('latest_authority_order', 0):
                state.update(latest_authority_order=activity['seq'], latest_authority_sync=sync_id,
                    latest_authority_status=summary['status'], latest_attempt_at=activity['recorded_at'],
                    latest_observed_at=result.observed_at, diagnostics=summary['diagnostics'])
            state['last_processed_sync'] = sync_id
            conn.execute('INSERT INTO discovery_source_state VALUES (?,?) ON CONFLICT(source_id) DO UPDATE SET document=excluded.document',
                         (source.id, canonical_json(state)))
            conn.execute('INSERT INTO discovery_boards VALUES (?,?,?)', (sync_id, source.id, canonical_json(summary)))
            conn.execute('UPDATE discovery_syncs SET updated_at=? WHERE id=?', (utc_now(), sync_id))
        self._boundary('after_board_commit')

    def _finalize(self, sync_id):
        with self.store.connection(immediate=True) as conn:
            view = self._view(sync_id, conn)
            boards = view['boards']
            if view['cancellation_requested']:
                status = 'cancelled'
            elif any(b['status'] == 'pending' for b in boards):
                raise RuntimeError('board_result_missing')
            elif boards and all(b['status'] == 'failed' for b in boards):
                status = 'failed'
            elif any(b['status'] != 'complete' for b in boards):
                status = 'partial'
            else:
                status = 'complete' if any(b['valid_count'] for b in boards) else 'empty'
            conn.execute('UPDATE discovery_syncs SET status=?,updated_at=? WHERE id=?', (status, utc_now(), sync_id))
            result = self._view(sync_id, conn)
            conn.execute('UPDATE discovery_syncs SET result_json=? WHERE id=?', (canonical_json(result), sync_id))
            for action in self.store.unfinished('discovery_continue', sync_id, conn):
                self._finish('discovery_continue', sync_id, action['action_id'], result, conn)
            return result

    async def drive(self, sync_id, *, continue_action_id=None):
        self.get_sync(sync_id)
        with self.store.ownership('operation', 'discovery-global'), self.store.ownership('operation', 'discovery:' + sync_id):
            with self.store.connection(immediate=True) as conn:
                row = self._row(sync_id, conn)
                fixed = json.loads(row['input_json'])
                if fixed['policy_version'] != 1 or fixed['parser_version'] != 'public-board-text-v1':
                    raise Conflict('unsupported_discovery_sync_version')
                if continue_action_id:
                    self._action_id(continue_action_id)
                    request = {'action_id': continue_action_id, 'kind': 'continue', 'input_hash': content_hash(fixed)}
                    digest = content_hash(request)
                    replay = self._action('discovery_continue', sync_id, continue_action_id, digest, conn)
                    if replay:
                        return replay
                if row['status'] in TERMINAL:
                    return self._view(sync_id, conn)
                if row['status'] == 'interrupted' and not continue_action_id:
                    raise Conflict('explicit_continue_required')
                if continue_action_id and self.store.action('discovery_continue', sync_id, continue_action_id, conn) is None:
                    self.store.accept('discovery_continue', sync_id, request, digest, conn)
                conn.execute("UPDATE discovery_syncs SET status='running',updated_at=? WHERE id=?", (utc_now(), sync_id))
                completed = {r[0] for r in conn.execute('SELECT source_id FROM discovery_boards WHERE sync_id=?', (sync_id,))}
            try:
                self._check_cancel(sync_id)
                async with self.http_factory() as http:
                    slots = asyncio.Semaphore(3)
                    async def board_work(raw_source):
                        source = DiscoverySource.model_validate(raw_source)
                        if source.id in completed:
                            return
                        async with slots:
                            self._check_cancel(sync_id)
                            journal = RequestJournal(self.store, sync_id, source.id, http,
                                check_cancel=lambda: self._check_cancel(sync_id), clock=self.clock, sleep=self.sleep, boundary=self._boundary)
                            result = await fetch_board(source, journal.fetch_json)
                            self._check_cancel(sync_id)
                            self._apply_board(sync_id, source, result)
                    tasks = [asyncio.create_task(board_work(source)) for source in fixed['sources']]
                    try:
                        await asyncio.gather(*tasks)
                    except BaseException:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        raise
            except ScanCancelledError:
                return self._finalize(sync_id)
            return self._finalize(sync_id)

    @staticmethod
    def _posting_filter(source_id, state):
        clauses, params = [], []
        if source_id:
            clauses.append('p.source_id=?')
            params.append(source_id)
        if state is not None:
            if state not in ('active', 'removed'):
                raise ValueError('invalid_posting_state')
            clauses.append('p.state=?')
            params.append(state)
        return ('WHERE ' + ' AND '.join(clauses) + ' ' if clauses else ''), params

    @staticmethod
    def _similarity_key(company, role):
        if not company or not role:
            return None
        return tuple(' '.join(unicodedata.normalize('NFC', value).split()).casefold() for value in (company, role))

    def _similarities(self, conn):
        groups = {}
        rows = conn.execute("SELECT p.source_id,p.external_id,p.job_id,json_extract(s.document,'$.provider') AS provider,"
            "json_extract(s.document,'$.board') AS board,json_extract(j.document,'$.company') AS company,"
            "json_extract(j.document,'$.role') AS role FROM discovery_postings p JOIN discovery_sources s ON s.id=p.source_id "
            "JOIN career_jobs j ON j.id=p.job_id WHERE p.state='active' ORDER BY p.source_id,p.external_id")
        for row in rows:
            key = self._similarity_key(row['company'], row['role'])
            if key:
                groups.setdefault(key, {}).setdefault(row['provider'], []).append({k: row[k] for k in ('source_id', 'external_id', 'job_id', 'provider', 'board')})
        return groups

    def list_postings(self, source_id=None, *, state=None, limit=200, offset=0, include_raw=False):
        if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
            raise ValueError('invalid_posting_page')
        where, params = self._posting_filter(source_id, state)
        with self.store.connection() as conn:
            configured = {s['id']: s for s in self._sources(conn)['sources']}
            similarities = self._similarities(conn)
            rows = conn.execute('SELECT p.*,s.document AS source_document,st.document AS source_state_document, '
                'v.job_id IS NOT NULL AS raw_available' + (',v.raw_json AS raw_record ' if include_raw else ' ') +
                'FROM discovery_postings p JOIN discovery_sources s ON s.id=p.source_id '
                'LEFT JOIN discovery_source_state st ON st.source_id=p.source_id '
                'LEFT JOIN discovery_posting_versions v ON v.source_id=p.source_id AND v.external_id=p.external_id AND v.raw_hash=p.raw_hash AND v.job_id=p.job_id '
                + where + 'ORDER BY p.last_seen_order DESC,p.source_id,p.external_id LIMIT ? OFFSET ?', (*params, limit, offset)).fetchall()
            result = []
            for row in rows:
                source_state = json.loads(row['source_state_document']) if row['source_state_document'] else {}
                authority = source_state.get('latest_authority_sync')
                fresh = ((row['state'] == 'active' and row['last_seen_sync'] == authority and source_state.get('latest_authority_status') in ('complete', 'partial'))
                         or (row['state'] == 'removed' and row['removed_sync'] == authority and source_state.get('latest_authority_status') == 'complete'))
                job = self.jobs.get(row['job_id']).model_dump(mode='json')
                source = json.loads(row['source_document'])
                group = similarities.get(self._similarity_key(job['company'], job['role']), {}) if row['state'] == 'active' else {}
                other_providers = [items for provider, items in group.items() if provider != source['provider']]
                count = sum(len(items) for items in other_providers)
                hints = list(islice((item for items in other_providers for item in items), 10))
                result.append({key: row[key] for key in row.keys() if key not in ('source_document', 'source_state_document', 'raw_record')} | {
                    'job': job, 'raw': json.loads(row['raw_record']) if include_raw and row['raw_record'] else None,
                    'source': source, 'source_state': source_state, 'possible_duplicates': hints, 'raw_available': bool(row['raw_available']),
                    'possible_duplicate_count': count, 'possible_duplicates_truncated': count > len(hints),
                    'source_configured': row['source_id'] in configured,
                    'source_enabled': configured.get(row['source_id'], {}).get('enabled', False), 'freshness': 'fresh' if fresh else 'stale'})
            return result

    def postings_page(self, *, source_id=None, state=None, limit=200, offset=0):
        items = self.list_postings(source_id, state=state, limit=limit, offset=offset)
        where, params = self._posting_filter(source_id, state)
        with self.store.connection() as conn:
            total = conn.execute('SELECT count(*) FROM discovery_postings p ' + where, params).fetchone()[0]
        return {'items': items, 'total': total, 'limit': limit, 'offset': offset, 'has_more': offset + len(items) < total}

    def job_origin(self, job_id):
        """Return exact archived observations, never replace the selected snapshot."""
        self.jobs.get(job_id)
        with self.store.connection() as conn:
            rows = conn.execute('SELECT v.*,s.document AS source_document,p.job_id AS current_job_id,p.state, '
                'p.last_seen_at,p.removed_at,st.document AS source_state_document '
                'FROM discovery_posting_versions v JOIN discovery_sources s ON s.id=v.source_id '
                'JOIN discovery_postings p ON p.source_id=v.source_id AND p.external_id=v.external_id '
                'LEFT JOIN discovery_source_state st ON st.source_id=v.source_id '
                'WHERE v.job_id=? ORDER BY v.observed_at', (job_id,)).fetchall()
            return [{'source': json.loads(row['source_document']), 'external_id': row['external_id'],
                     'job_id': job_id, 'current_job_id': row['current_job_id'],
                     'selected_snapshot_is_current': row['current_job_id'] == job_id,
                     'raw': json.loads(row['raw_json']), 'raw_hash': row['raw_hash'], 'observed_at': row['observed_at'],
                     'posting_state': row['state'], 'last_seen_at': row['last_seen_at'], 'removed_at': row['removed_at'],
                     'source_state': json.loads(row['source_state_document']) if row['source_state_document'] else {}}
                    for row in rows]

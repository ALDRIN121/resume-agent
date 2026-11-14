"""Consumed-before-call GET budgets and immutable response observations."""
import asyncio
import hashlib
import json
import time

from ..contracts import canonical_json, utc_now
from .http import DiscoveryRequestError, decode_json
from .schemas import DiscoveryError, PagePayload


class RequestJournal:
    def __init__(self, store, sync_id, source_id, http, *, check_cancel, clock=time.time, sleep=asyncio.sleep, boundary=lambda _: None):
        self.store, self.sync_id, self.source_id, self.http = store, sync_id, source_id, http
        self.check_cancel, self.clock, self.sleep, self.boundary = check_cancel, clock, sleep, boundary

    def _row(self, url, conn):
        return dict(conn.execute('SELECT * FROM discovery_requests WHERE sync_id=? AND source_id=? AND url=?',
                                 (self.sync_id, self.source_id, url)).fetchone())

    def _activity(self, url, kind, conn):
        cursor = conn.execute('INSERT INTO discovery_activity(sync_id,source_id,url,kind,recorded_at) VALUES (?,?,?,?,?)',
                              (self.sync_id, self.source_id, url, kind, utc_now()))
        return cursor.lastrowid

    def _update(self, url, values, conn):
        assignments = ','.join(key + '=?' for key in values)
        conn.execute(f'UPDATE discovery_requests SET {assignments} WHERE sync_id=? AND source_id=? AND url=?',
                     (*values.values(), self.sync_id, self.source_id, url))

    def _decode(self, row):
        body = row['body']
        if body is None or len(body) > 10 * 1024 * 1024 or hashlib.sha256(body).hexdigest() != row['body_hash']:
            raise DiscoveryError('cached_response_mismatch', partial=True)
        try:
            payload = decode_json(body)
        except (ValueError, RecursionError):
            raise DiscoveryError('invalid_json_response') from None
        metadata = json.loads(row['metadata_json'])
        return PagePayload(payload, metadata['observed_at'], row['response_order'])

    async def fetch_json(self, url):
        while True:
            self.check_cancel()
            with self.store.connection(immediate=True) as conn:
                conn.execute('INSERT OR IGNORE INTO discovery_requests(sync_id,source_id,url) VALUES (?,?,?)',
                             (self.sync_id, self.source_id, url))
                row = self._row(url, conn)
            if row['status'] == 'complete':
                return self._decode(row)
            if row['status'] == 'failed':
                raise DiscoveryError(row['error_code'], partial=bool(row['partial']))
            if row['attempts'] >= 3:
                with self.store.connection(immediate=True) as conn:
                    self._update(url, {'status': 'failed', 'error_code': 'request_budget_exhausted', 'transient': 0}, conn)
                raise DiscoveryError('request_budget_exhausted')
            if row['retry_at'] is not None:
                remaining = max(0, min(60, row['retry_at'] - self.clock()))
                if remaining:
                    await self.sleep(remaining)
                self.check_cancel()
            with self.store.connection(immediate=True) as conn:
                order = self._activity(url, 'attempt', conn)
                attempts = row['attempts'] + 1
                self._update(url, {'attempts': attempts, 'status': 'running', 'retry_at': None, 'attempt_order': order}, conn)
            self.boundary('before_http_attempt')
            self.check_cancel()
            try:
                response = await self.http.fetch_once(url)
            except DiscoveryRequestError as exc:
                delay = exc.retry_after if exc.retry_after is not None else 2 ** (attempts - 1)
                retry = exc.transient and attempts < 3 and 0 <= delay <= 60
                code = 'retry_after_exceeds_limit' if delay > 60 else exc.code
                with self.store.connection(immediate=True) as conn:
                    self._activity(url, 'failure', conn)
                    self._update(url, {'status': 'retry' if retry else 'failed', 'error_code': code,
                        'retry_at': self.clock() + delay if retry else None, 'transient': int(retry), 'partial': int(exc.partial)}, conn)
                if not retry:
                    raise DiscoveryError(code, partial=exc.partial) from None
                self.boundary('after_retry_intent')
                continue
            self.check_cancel()
            with self.store.connection(immediate=True) as conn:
                order = self._activity(url, 'response', conn)
                metadata = {'url': response.url, 'status_code': response.status_code, 'headers': response.headers,
                            'observed_at': response.observed_at, 'physical_requests': response.physical_requests}
                self._update(url, {'status': 'complete', 'body': response.body, 'body_hash': hashlib.sha256(response.body).hexdigest(),
                    'metadata_json': canonical_json(metadata), 'response_order': order, 'retry_at': None, 'error_code': None}, conn)
                row = self._row(url, conn)
            self.boundary('after_response_cached')
            return self._decode(row)

"""Immutable job snapshots with explicit logical identities and current pointers."""
import json
from urllib.parse import urlsplit
from uuid import uuid4

from .career_schemas import CareerJob
from .config import MAX_JD_TEXT_CHARS
from .contracts import canonical_json, content_hash, utc_now


class JobStore:
    def __init__(self, store):
        self.store = store

    def get(self, snapshot_id):
        with self.store.connection() as conn:
            row = conn.execute('SELECT document FROM career_jobs WHERE id=?', (snapshot_id,)).fetchone()
            if row is None:
                raise KeyError(snapshot_id)
            return CareerJob.model_validate(json.loads(row[0]))

    def current(self, logical_id):
        with self.store.connection() as conn:
            row = conn.execute('SELECT snapshot_id FROM job_heads WHERE logical_id=?', (logical_id,)).fetchone()
            if row is None:
                raise KeyError(logical_id)
            return self.get(row[0])

    def list(self):
        with self.store.connection() as conn:
            rows = conn.execute('SELECT j.document FROM job_heads h JOIN career_jobs j ON h.snapshot_id=j.id ORDER BY j.rowid DESC').fetchall()
            return [CareerJob.model_validate(json.loads(row[0])) for row in rows]

    def capture(self, text, *, source_kind='manual', source_key=None, source_url=None, company=None, role=None):
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_JD_TEXT_CHARS:
            raise ValueError('invalid_job_text')
        if source_url:
            parts = urlsplit(source_url)
            if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
                raise ValueError('invalid_job_source_url')
        source_key = source_key or str(uuid4())
        with self.store.connection(immediate=True) as conn:
            head = conn.execute('SELECT j.document FROM job_heads h JOIN career_jobs j ON h.snapshot_id=j.id '
                                'WHERE h.source_kind=? AND h.source_key=?', (source_kind, source_key)).fetchone()
            previous = CareerJob.model_validate(json.loads(head[0])) if head else None
            digest = content_hash(text)
            if previous and previous.content_hash == digest:
                return previous
            if previous:
                for row in conn.execute('SELECT document FROM career_jobs WHERE logical_id=? ORDER BY rowid', (previous.logical_id,)):
                    observed = CareerJob.model_validate(json.loads(row[0]))
                    if observed.content_hash == digest:
                        conn.execute('UPDATE job_heads SET snapshot_id=? WHERE logical_id=?', (observed.id, observed.logical_id))
                        return observed
            job = CareerJob(id=str(uuid4()), logical_id=previous.logical_id if previous else str(uuid4()),
                previous_id=previous.id if previous else None, text=text, content_hash=digest,
                source_kind=source_kind, source_key=source_key, source_url=source_url, company=company, role=role,
                captured_at=utc_now())
            conn.execute('INSERT INTO career_jobs VALUES (?,?,?)', (job.id, job.logical_id, canonical_json(job)))
            if job.company:
                conn.execute("INSERT OR IGNORE INTO company_references VALUES (?,'job',?)", (job.company, job.id))
            conn.execute('INSERT INTO job_heads VALUES (?,?,?,?) ON CONFLICT(logical_id) DO UPDATE SET snapshot_id=excluded.snapshot_id',
                         (job.logical_id, job.source_kind, job.source_key, job.id))
            return job

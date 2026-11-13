"""Ordered library migrations; never writes LangGraph-owned state tables."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path

from filelock import FileLock

CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS migration_meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK (schema_version = 2),
  artifact_id TEXT NOT NULL UNIQUE,
  parent_run_id TEXT,
  status TEXT NOT NULL CHECK (status IN
    ('queued','running','awaiting-input','interrupted','complete','failed','cancelled')),
  input_json TEXT NOT NULL,
  source_revision TEXT NOT NULL,
  pending_json TEXT,
  result_json TEXT,
  error_code TEXT,
  error_stage TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operations (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('profile_import','role_evaluation')),
  status TEXT NOT NULL CHECK (status IN
    ('pending_model','pending_review','running','interrupted','complete','failed','cancelled')),
  input_json TEXT NOT NULL,
  pending_json TEXT,
  result_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
  owner_kind TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  action_id TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  request_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('accepted','complete','failed')),
  result_json TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (owner_kind, owner_id, action_id)
);
CREATE TABLE IF NOT EXISTS cancellations (
  owner_kind TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  action_id TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  PRIMARY KEY (owner_kind, owner_id)
);
CREATE TABLE IF NOT EXISTS release_records (
  run_id TEXT PRIMARY KEY REFERENCES runs(id),
  review_id TEXT NOT NULL,
  action_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  render_hash TEXT NOT NULL,
  pdf_hash TEXT NOT NULL,
  canonical_pdf_path TEXT NOT NULL,
  destination TEXT NOT NULL UNIQUE,
  temporary_path TEXT NOT NULL UNIQUE,
  ownership_token TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (status IN ('approved','exporting','released')),
  approved_at TEXT NOT NULL,
  released_at TEXT
);
"""


class UnsupportedSchemaError(RuntimeError):
    """A newer application owns this database."""


UnsupportedSchema = UnsupportedSchemaError


def _core(conn: sqlite3.Connection) -> None:
    # executescript implicitly commits, which would break migration rollback.
    for statement in CORE_SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)


def _memory(conn: sqlite3.Connection) -> None:
    conn.execute('CREATE TABLE memory_records (id TEXT PRIMARY KEY, document TEXT NOT NULL)')
    conn.execute('CREATE TABLE memory_decisions (record_id TEXT NOT NULL REFERENCES memory_records(id), '
                 'action_id TEXT NOT NULL, decision TEXT NOT NULL, request_json TEXT NOT NULL, '
                 'recorded_at TEXT NOT NULL, PRIMARY KEY(record_id,action_id))')


def _career(conn: sqlite3.Connection) -> None:
    conn.execute('CREATE TABLE career_jobs (id TEXT PRIMARY KEY, logical_id TEXT NOT NULL, document TEXT NOT NULL)')
    conn.execute('CREATE TABLE job_heads (logical_id TEXT PRIMARY KEY, source_kind TEXT NOT NULL, '
                 'source_key TEXT NOT NULL, snapshot_id TEXT NOT NULL REFERENCES career_jobs(id), '
                 'UNIQUE(source_kind,source_key))')
    conn.execute('CREATE TABLE career_evaluations (operation_id TEXT PRIMARY KEY REFERENCES operations(id), '
                 'job_id TEXT NOT NULL REFERENCES career_jobs(id), result_json TEXT NOT NULL)')


def _applications(conn: sqlite3.Connection) -> None:
    conn.execute('CREATE TABLE applications (id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES career_jobs(id), document TEXT NOT NULL)')
    conn.execute('CREATE TABLE application_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, '
                 'application_id TEXT NOT NULL REFERENCES applications(id), payload_json TEXT NOT NULL, '
                 'binding_json TEXT NOT NULL, recorded_at TEXT NOT NULL)')
    conn.execute('CREATE INDEX application_event_owner ON application_events(application_id,seq)')
    conn.execute('CREATE TABLE company_references (company_name TEXT NOT NULL, owner_kind TEXT NOT NULL, '
                 'owner_id TEXT NOT NULL, PRIMARY KEY(company_name,owner_kind,owner_id))')
    for job_id, document in conn.execute('SELECT id,document FROM career_jobs').fetchall():
        company = json.loads(document).get('company')
        if company:
            conn.execute("INSERT INTO company_references VALUES (?,'job',?)", (company, job_id))


def _discovery(conn: sqlite3.Connection) -> None:
    statements = (
        'CREATE TABLE discovery_sources (id TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL, document TEXT NOT NULL)',
        'CREATE TABLE discovery_config (singleton INTEGER PRIMARY KEY CHECK(singleton=1), document TEXT NOT NULL)',
        'CREATE TABLE discovery_syncs (id TEXT PRIMARY KEY, input_json TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)',
        'CREATE TABLE discovery_boards (sync_id TEXT NOT NULL REFERENCES discovery_syncs(id), source_id TEXT NOT NULL REFERENCES discovery_sources(id), result_json TEXT NOT NULL, PRIMARY KEY(sync_id,source_id))',
        'CREATE TABLE discovery_activity (seq INTEGER PRIMARY KEY AUTOINCREMENT, sync_id TEXT NOT NULL REFERENCES discovery_syncs(id), source_id TEXT NOT NULL REFERENCES discovery_sources(id), url TEXT NOT NULL, kind TEXT NOT NULL, recorded_at TEXT NOT NULL)',
        "CREATE TABLE discovery_requests (sync_id TEXT NOT NULL REFERENCES discovery_syncs(id), source_id TEXT NOT NULL REFERENCES discovery_sources(id), url TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3), status TEXT NOT NULL DEFAULT 'pending', body BLOB, body_hash TEXT, metadata_json TEXT, retry_at REAL, error_code TEXT, transient INTEGER NOT NULL DEFAULT 0, partial INTEGER NOT NULL DEFAULT 0, attempt_order INTEGER, response_order INTEGER, PRIMARY KEY(sync_id,source_id,url))",
        'CREATE TABLE discovery_source_state (source_id TEXT PRIMARY KEY REFERENCES discovery_sources(id), document TEXT NOT NULL)',
        "CREATE TABLE discovery_postings (source_id TEXT NOT NULL REFERENCES discovery_sources(id), external_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES career_jobs(id), raw_hash TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('active','removed')), first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, last_seen_sync TEXT NOT NULL REFERENCES discovery_syncs(id), last_seen_order INTEGER NOT NULL, removed_at TEXT, removed_sync TEXT, removed_order INTEGER, PRIMARY KEY(source_id,external_id))",
        'CREATE TABLE discovery_posting_versions (source_id TEXT NOT NULL REFERENCES discovery_sources(id), external_id TEXT NOT NULL, raw_hash TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES career_jobs(id), raw_json TEXT NOT NULL, observed_at TEXT NOT NULL, PRIMARY KEY(source_id,external_id,raw_hash,job_id))',
    )
    for statement in statements:
        conn.execute(statement)


MIGRATIONS = (_core, _memory, _career, _applications, _discovery)


def migrate(path: Path, *, migrations: Sequence[Callable[[sqlite3.Connection], None]] = MIGRATIONS) -> None:
    """Back up an existing database, then apply each version atomically under a lock."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".migration.lock", timeout=30):
        existed = path.exists() and path.stat().st_size > 0
        with sqlite3.connect(path) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > len(migrations):
                raise UnsupportedSchema("unsupported_database_version")
            if version == len(migrations):
                return
            if existed:
                backup = path.with_suffix(path.suffix + f".pre-v{version + 1}.bak")
                if not backup.exists():
                    with sqlite3.connect(backup) as target:
                        conn.backup(target)
            for next_version in range(version + 1, len(migrations) + 1):
                conn.execute("BEGIN IMMEDIATE")
                try:
                    migrations[next_version - 1](conn)
                    conn.execute(f"PRAGMA user_version={next_version}")
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    raise

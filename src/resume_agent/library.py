"""SQLite-backed résumé library — persists generated resumes grouped by company.

Separate from the LangGraph checkpointer DB (``state.sqlite``). This is the durable
record behind the web UI's "Résumé library": every finished run is filed here under
the company it targeted, so the frontend can browse and download tailored resumes per
company. Existing ``run_history.jsonl`` rows are imported once on startup so no history
is lost when upgrading.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .config import CONFIG_DIR

LIBRARY_DB = CONFIG_DIR / "library.sqlite"
_HISTORY_FILE = CONFIG_DIR / "run_history.jsonl"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS resumes (
    thread_id  TEXT PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    role       TEXT,
    status     TEXT,
    pdf_path   TEXT,
    error      TEXT,
    duration_s REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resumes_company ON resumes(company_id);
"""


def _connect() -> sqlite3.Connection:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(LIBRARY_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call repeatedly."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def _company_id(conn: sqlite3.Connection, name: str) -> int:
    name = (name or "Unknown").strip() or "Unknown"
    row = conn.execute("SELECT id FROM companies WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO companies (name, created_at) VALUES (?, ?)", (name, time.time())
    )
    return int(cur.lastrowid)


def upsert_resume(
    *,
    thread_id: str,
    company: str,
    role: str | None = None,
    status: str | None = None,
    pdf_path: str | None = None,
    error: str | None = None,
    duration_s: float | None = None,
    created_at: float | None = None,
) -> None:
    """Insert or update a résumé record, creating its company on demand."""
    if not thread_id:
        return
    now = time.time()
    with _connect() as conn:
        cid = _company_id(conn, company)
        conn.execute(
            """
            INSERT INTO resumes
                (thread_id, company_id, role, status, pdf_path, error, duration_s, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                company_id = excluded.company_id,
                role       = excluded.role,
                status     = excluded.status,
                pdf_path   = excluded.pdf_path,
                error      = excluded.error,
                duration_s = excluded.duration_s,
                updated_at = excluded.updated_at
            """,
            (
                thread_id,
                cid,
                role,
                status,
                pdf_path,
                error,
                duration_s,
                created_at if created_at is not None else now,
                now,
            ),
        )


def list_companies() -> list[dict[str, Any]]:
    """Companies with résumé counts and a per-status breakdown, newest activity first."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT c.name AS name,
                   COUNT(r.thread_id) AS total,
                   SUM(CASE WHEN r.status = 'complete' THEN 1 ELSE 0 END)       AS final,
                   SUM(CASE WHEN r.status = 'awaiting-input' THEN 1 ELSE 0 END) AS needs,
                   SUM(CASE WHEN r.status = 'failed' THEN 1 ELSE 0 END)         AS failed,
                   MAX(r.updated_at) AS last_updated
            FROM companies c
            LEFT JOIN resumes r ON r.company_id = c.id
            GROUP BY c.id
            ORDER BY last_updated IS NULL, last_updated DESC, c.name ASC
            """
        ).fetchall()
    return [
        {
            "name": row["name"],
            "total": row["total"] or 0,
            "final": row["final"] or 0,
            "needs": row["needs"] or 0,
            "failed": row["failed"] or 0,
            "last_updated": row["last_updated"],
        }
        for row in rows
    ]


def list_resumes(company: str | None = None) -> list[dict[str, Any]]:
    """Résumé records, optionally filtered to one company, newest first."""
    query = (
        "SELECT r.thread_id, c.name AS company, r.role, r.status, r.pdf_path, "
        "r.error, r.duration_s, r.created_at, r.updated_at "
        "FROM resumes r JOIN companies c ON c.id = r.company_id"
    )
    params: tuple[Any, ...] = ()
    if company:
        query += " WHERE c.name = ?"
        params = (company,)
    query += " ORDER BY r.created_at DESC"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_resume_dict(row) for row in rows]


def get_resume(thread_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT r.thread_id, c.name AS company, r.role, r.status, r.pdf_path, "
            "r.error, r.duration_s, r.created_at, r.updated_at "
            "FROM resumes r JOIN companies c ON c.id = r.company_id "
            "WHERE r.thread_id = ?",
            (thread_id,),
        ).fetchone()
    return _resume_dict(row) if row else None


def delete_resume(thread_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM resumes WHERE thread_id = ?", (thread_id,))
        # Drop any company left with no resumes so the tree stays clean.
        conn.execute(
            "DELETE FROM companies WHERE id NOT IN (SELECT DISTINCT company_id FROM resumes)"
        )
        return cur.rowcount > 0


def migrate_from_jsonl(path: Path | None = None) -> int:
    """Import existing run_history.jsonl rows into the DB. Idempotent (upsert by id)."""
    history = path or _HISTORY_FILE
    if not history.exists():
        return 0
    count = 0
    try:
        for line in history.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            tid = rec.get("thread_id")
            if not tid:
                continue
            upsert_resume(
                thread_id=tid,
                company=rec.get("company", "Unknown"),
                role=rec.get("role"),
                status=rec.get("status"),
                pdf_path=rec.get("pdf_path"),
                error=rec.get("error"),
                duration_s=rec.get("duration_s"),
                created_at=rec.get("started_wall_ts"),
            )
            count += 1
    except Exception:
        pass  # a corrupt history file must never block startup
    return count


def _resume_dict(row: sqlite3.Row) -> dict[str, Any]:
    pdf_path = row["pdf_path"]
    has_pdf = bool(pdf_path) and row["status"] == "complete"
    return {
        "thread_id": row["thread_id"],
        "id": row["thread_id"],
        "company": row["company"],
        "role": row["role"] or "Unknown",
        "status": row["status"] or "queued",
        "pdf": Path(pdf_path).name if pdf_path else None,
        "pdf_url": f"/api/runs/{row['thread_id']}/pdf" if has_pdf else None,
        "error": row["error"],
        "duration_s": row["duration_s"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

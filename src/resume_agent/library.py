"""SQLite-backed résumé library — persists generated resumes grouped by company.

Separate from the LangGraph checkpointer DB (``state.sqlite``). This is the durable
record behind the web UI's "Résumé library": every finished run is filed here under
the company it targeted, so the frontend can browse and download tailored resumes per
company. Existing ``run_history.jsonl`` rows are imported once on startup so no history
is lost when upgrading.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import sqlite3
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from filelock import FileLock

from .config import CONFIG_DIR
from .contracts import canonical_json, content_hash, utc_now
from .migrations import migrate

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
    location   TEXT,
    work_mode  TEXT,
    remote_policy TEXT,
    status     TEXT,
    pdf_path   TEXT,
    error      TEXT,
    duration_s REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resumes_company ON resumes(company_id);
"""


def _connect(library_path: Path | None = None) -> sqlite3.Connection:
    database = Path(library_path) if library_path is not None else LIBRARY_DB
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(*, library_path: Path | None = None, history_file: Path | None = None) -> None:
    """Initialize/import before constructing RunStore: existing libraries win."""
    database = Path(library_path) if library_path is not None else LIBRARY_DB
    history = history_file if history_file is not None else (database.parent / "run_history.jsonl" if library_path is not None else _HISTORY_FILE)
    database.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(database) + ".library-init.lock", timeout=30):
        existed = database.exists()
        # Reject future versions before recording any eligibility metadata.
        if existed:
            migrate(database)
        with _connect(database) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS migration_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("INSERT OR IGNORE INTO migration_meta VALUES ('legacy_jsonl_eligible', ?)",
                         ("false" if existed else "true",))
        migrate(database)
        with _connect(database) as conn:
            conn.executescript(_SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(resumes)")}
            for column in ("location", "work_mode", "remote_policy"):
                if column not in columns:
                    conn.execute(f"ALTER TABLE resumes ADD COLUMN {column} TEXT")
        migrate_from_jsonl(history, library_path=database)


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
    location: str | None = None,
    work_mode: str | None = None,
    remote_policy: str | None = None,
    status: str | None = None,
    pdf_path: str | None = None,
    error: str | None = None,
    duration_s: float | None = None,
    created_at: float | None = None,
    library_path: Path | None = None,
) -> None:
    """Insert or update a résumé record, creating its company on demand."""
    if not thread_id:
        return
    now = time.time()
    with _connect(library_path) as conn:
        cid = _company_id(conn, company)
        conn.execute(
            """
            INSERT INTO resumes
                (thread_id, company_id, role, status, pdf_path, error, duration_s, created_at, updated_at, location, work_mode, remote_policy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                company_id = excluded.company_id,
                role       = excluded.role,
                location   = excluded.location,
                work_mode  = excluded.work_mode,
                remote_policy = excluded.remote_policy,
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
                location,
                work_mode,
                remote_policy,
            ),
        )


def list_companies(*, library_path: Path | None = None) -> list[dict[str, Any]]:
    """Companies with résumé counts and a per-status breakdown, newest activity first."""
    with _connect(library_path) as conn:
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


def list_resumes(company: str | None = None, *, library_path: Path | None = None) -> list[dict[str, Any]]:
    """Résumé records, optionally filtered to one company, newest first."""
    query = (
        "SELECT r.thread_id, c.name AS company, r.role, r.status, r.pdf_path, "
        "r.error, r.duration_s, r.created_at, r.updated_at, r.location, r.work_mode, r.remote_policy "
        "FROM resumes r JOIN companies c ON c.id = r.company_id"
    )
    params: tuple[Any, ...] = ()
    if company:
        query += " WHERE c.name = ?"
        params = (company,)
    query += " ORDER BY r.created_at DESC"
    with _connect(library_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [_resume_dict(row, conn) for row in rows]


def get_resume(thread_id: str, *, library_path: Path | None = None) -> dict[str, Any] | None:
    with _connect(library_path) as conn:
        row = conn.execute(
            "SELECT r.thread_id, c.name AS company, r.role, r.status, r.pdf_path, "
            "r.error, r.duration_s, r.created_at, r.updated_at, r.location, r.work_mode, r.remote_policy "
            "FROM resumes r JOIN companies c ON c.id = r.company_id "
            "WHERE r.thread_id = ?",
            (thread_id,),
        ).fetchone()
        return _resume_dict(row, conn) if row else None


def delete_resume(thread_id: str, *, library_path: Path | None = None) -> bool:
    with _connect(library_path) as conn:
        cur = conn.execute("DELETE FROM resumes WHERE thread_id = ?", (thread_id,))
        # Drop any company left with no resumes so the tree stays clean.
        conn.execute(
            "DELETE FROM companies WHERE id NOT IN (SELECT DISTINCT company_id FROM resumes)"
        )
        return cur.rowcount > 0


def migrate_from_jsonl(path: Path | None = None, *, library_path: Path | None = None) -> int:
    """Insert legacy history once, only for a library born eligible for import."""
    history = path or (Path(library_path).parent / "run_history.jsonl" if library_path is not None else _HISTORY_FILE)
    with _connect(library_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        eligible = conn.execute("SELECT value FROM migration_meta WHERE key='legacy_jsonl_eligible'").fetchone()
        imported = conn.execute("SELECT 1 FROM migration_meta WHERE key='legacy_jsonl_imported'").fetchone()
        if not eligible or eligible[0] != "true" or imported:
            return 0
        count, diagnostics = 0, []
        lines = history.read_text(encoding="utf-8").splitlines() if history.exists() else []
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                if not isinstance(rec, dict) or not isinstance(rec.get("thread_id"), str) or not rec["thread_id"]:
                    raise ValueError("missing thread_id")
                for key in ("company", "role", "location", "work_mode", "remote_policy", "status", "pdf_path", "error"):
                    if rec.get(key) is not None and not isinstance(rec[key], str):
                        raise ValueError("invalid text field")
                for key in ("duration_s", "started_wall_ts"):
                    if rec.get(key) is not None and (type(rec[key]) not in (int, float) or not math.isfinite(rec[key])):
                        raise ValueError("invalid numeric field")
            except (ValueError, TypeError):
                diagnostic = f"legacy history line {number}: invalid row skipped"
                logging.getLogger(__name__).warning(diagnostic)
                diagnostics.append(diagnostic)
                continue
            cid, now = _company_id(conn, rec.get("company") or "Unknown"), time.time()
            cursor = conn.execute(
                "INSERT OR IGNORE INTO resumes (thread_id,company_id,role,status,pdf_path,error,duration_s,"
                "created_at,updated_at,location,work_mode,remote_policy) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["thread_id"], cid, rec.get("role"), rec.get("status"), rec.get("pdf_path"), rec.get("error"),
                 rec.get("duration_s"), rec.get("started_wall_ts", now), now, rec.get("location"),
                 rec.get("work_mode"), rec.get("remote_policy")))
            count += cursor.rowcount
        conn.execute("INSERT INTO migration_meta VALUES ('legacy_jsonl_imported', ?)", (utc_now(),))
        conn.execute("INSERT OR REPLACE INTO migration_meta VALUES ('legacy_jsonl_diagnostics', ?)",
                     (canonical_json(diagnostics),))
        return count


def _legacy_only(conn: sqlite3.Connection, thread_id: str) -> None:
    if conn.execute("SELECT 1 FROM runs WHERE id=?", (thread_id,)).fetchone():
        raise ValueError("canonical_release_required")
    row = conn.execute("SELECT status FROM resumes WHERE thread_id=?", (thread_id,)).fetchone()
    if row is None:
        raise KeyError(thread_id)
    if row[0] != "complete":
        raise ValueError("legacy_completed_required")


def _inspect_pdf(path: Path) -> str:
    from pypdf import PdfReader

    try:
        data = path.read_bytes()
        if not data or not data.startswith(b"%PDF-") or not PdfReader(io.BytesIO(data), strict=True).pages:
            raise ValueError("invalid_pdf")
    except Exception as exc:
        raise ValueError("invalid_pdf") from exc
    return hashlib.sha256(data).hexdigest()


def inspect_legacy_artifact(thread_id: str, path: Path, *, library_path: Path | None = None) -> dict[str, Any]:
    """Inspect explicit local bytes; inspection never silently attaches a file."""
    path = Path(path).resolve(strict=True)
    with _connect(library_path) as conn:
        _legacy_only(conn, thread_id)
        inspected = {"review_id": str(uuid4()), "path": str(path), "observed_hash": _inspect_pdf(path)}
        conn.execute("INSERT OR REPLACE INTO migration_meta VALUES (?,?)",
                     ("legacy_artifact_review:" + thread_id, canonical_json(inspected)))
    return inspected


def relink_legacy_artifact(thread_id: str, *, review_id: str, observed_hash: str,
                           action_id: str, confirmed: bool, library_path: Path | None = None) -> dict[str, Any]:
    """Attach inspected bytes after explicit confirmation; retain unverified identity."""
    if not confirmed:
        raise ValueError("confirmation_required")
    if not action_id:
        raise ValueError("action_id_required")
    payload = {"review_id": review_id, "observed_hash": observed_hash, "confirmed": confirmed}
    with _connect(library_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _legacy_only(conn, thread_id)
        previous = conn.execute("SELECT request_hash,result_json FROM actions WHERE owner_kind='legacy_relink' "
                                "AND owner_id=? AND action_id=?", (thread_id, action_id)).fetchone()
        if previous:
            if previous[0] != content_hash(payload):
                raise ValueError("action_payload_conflict")
            return json.loads(previous[1])
        review = conn.execute("SELECT value FROM migration_meta WHERE key=?",
                              ("legacy_artifact_review:" + thread_id,)).fetchone()
        inspected = json.loads(review[0]) if review else {}
        if inspected.get("review_id") != review_id or inspected.get("observed_hash") != observed_hash:
            raise ValueError("stale_review")
        try:
            actual = _inspect_pdf(Path(inspected["path"]))
        except ValueError as exc:
            raise ValueError("artifact_changed") from exc
        if actual != observed_hash:
            raise ValueError("artifact_changed")
        conn.execute("UPDATE resumes SET pdf_path=?,updated_at=? WHERE thread_id=?",
                     (inspected["path"], time.time(), thread_id))
        conn.execute("INSERT OR REPLACE INTO migration_meta VALUES (?,?)",
                     ("legacy_artifact:" + thread_id, canonical_json(inspected)))
        # Compute the returned row in this transaction, including its inspection metadata.
        row = conn.execute("SELECT r.*,c.name AS company FROM resumes r JOIN companies c ON c.id=r.company_id "
                           "WHERE thread_id=?", (thread_id,)).fetchone()
        result = _resume_dict(row, conn)
        conn.execute("INSERT INTO actions VALUES ('legacy_relink',?,?,?,?, 'complete',?,?)",
                     (thread_id, action_id, content_hash(payload), canonical_json(payload), canonical_json(result), utc_now()))
        return result


def _artifact_available(path: str, expected_hash: str) -> bool:
    from .artifacts import hash_file
    try:
        candidate = Path(path)
        return candidate.is_absolute() and candidate.resolve() == candidate and hash_file(candidate) == expected_hash
    except (OSError, ValueError):
        return False


def _availability(conn: sqlite3.Connection, thread_id: str) -> dict[str, Any]:
    released = conn.execute("SELECT * FROM release_records WHERE run_id=? AND status='released'",
                            (thread_id,)).fetchone()
    if released:
        canonical = _artifact_available(released["canonical_pdf_path"], released["pdf_hash"])
        exported = _artifact_available(released["destination"], released["pdf_hash"])
        return {"artifact_status": "available" if canonical else "missing",
                "canonical_available": canonical, "export_available": exported}
    if conn.execute("SELECT 1 FROM runs WHERE id=?", (thread_id,)).fetchone():
        return {"artifact_status": "pending", "canonical_available": False, "export_available": False}
    historical = conn.execute("SELECT pdf_path,status FROM resumes WHERE thread_id=?", (thread_id,)).fetchone()
    if not historical:
        raise KeyError(thread_id)
    available = bool(historical["pdf_path"] and Path(historical["pdf_path"]).is_file() and historical["status"] == "complete")
    return {"artifact_status": "legacy_unverified" if available else "missing" if historical["status"] == "complete" else "pending",
            "canonical_available": False, "export_available": available}


def artifact_availability(thread_id: str, *, library_path: Path | None = None) -> dict[str, Any]:
    """Keep friendly-export availability separate from canonical approved bytes."""
    with _connect(library_path) as conn:
        return _availability(conn, thread_id)


def _resume_dict(row: sqlite3.Row, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    if conn is None:
        with _connect() as connection:
            return _resume_dict(row, connection)
    pdf_path = row["pdf_path"]
    released = conn.execute("SELECT 1 FROM release_records WHERE run_id=? AND status='released'",
                            (row["thread_id"],)).fetchone()
    availability = _availability(conn, row["thread_id"])
    has_pdf = availability["artifact_status"] in {"available", "legacy_unverified"}
    inspection = conn.execute("SELECT value FROM migration_meta WHERE key=?",
                              ("legacy_artifact:" + row["thread_id"],)).fetchone()
    observed = json.loads(inspection[0]) if inspection else {}
    return {
        "thread_id": row["thread_id"],
        "id": row["thread_id"],
        "company": row["company"],
        "role": row["role"] or "Unknown",
        "location": row["location"],
        "work_mode": row["work_mode"],
        "remote_policy": row["remote_policy"],
        "status": row["status"] or "queued",
        "pdf": Path(pdf_path).name if pdf_path else None,
        "pdf_url": f"/api/runs/{row['thread_id']}/pdf" if has_pdf else None,
        **availability,
        "identity_verified": bool(released),
        "inspection_hash": observed.get("observed_hash"),
        "error": row["error"],
        "duration_s": row["duration_s"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

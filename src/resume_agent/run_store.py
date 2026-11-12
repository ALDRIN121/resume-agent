"""Shared SQLite commands and process ownership for v2 runs and operations."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from filelock import FileLock, Timeout

from .contracts import canonical_json, utc_now
from .migrations import migrate

TABLES = {"run": "runs", "operation": "operations"}
TERMINAL = {"complete", "failed", "cancelled"}


class ConflictError(RuntimeError):
    """Stable domain conflict, suitable for a future HTTP 409 adapter."""


Conflict = ConflictError


class RunStore:
    def __init__(self, library_path: Path, checkpoint_path: Path):
        self.library_path = Path(library_path)
        self.checkpoint_path = Path(checkpoint_path)
        migrate(self.library_path)

    @contextmanager
    def connection(self, *, immediate: bool = False) -> Generator[sqlite3.Connection]:
        conn = sqlite3.connect(self.library_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def lock_path(self, kind: str, owner_id: str) -> Path:
        TABLES[kind]
        root = self.library_path.parent / "operation-locks"
        root.mkdir(parents=True, exist_ok=True)
        return root / f"{kind}-{hashlib.sha256(owner_id.encode()).hexdigest()}.lock"

    @contextmanager
    def ownership(self, kind: str, owner_id: str) -> Generator[None]:
        lock = FileLock(self.lock_path(kind, owner_id), timeout=0)
        try:
            lock.acquire()
        except Timeout:
            raise Conflict("owner_busy") from None
        try:
            yield
        finally:
            lock.release()

    def row(self, kind: str, owner_id: str, conn: sqlite3.Connection | None = None) -> dict:
        if conn is None:
            with self.connection() as connection:
                return self.row(kind, owner_id, connection)
        row = conn.execute(f"SELECT * FROM {TABLES[kind]} WHERE id=?", (owner_id,)).fetchone()
        if row is None:
            raise KeyError(owner_id)
        return dict(row)

    def input(self, kind: str, owner_id: str) -> dict:
        # Always deserialize a fresh copy: driver mutations cannot alter fixed input.
        return json.loads(self.row(kind, owner_id)["input_json"])

    def _create_run(self, fixed: dict, conn: sqlite3.Connection) -> str:
        owner_id, artifact_id, now = str(uuid4()), str(uuid4()), utc_now()
        conn.execute(
            "INSERT INTO runs(id,schema_version,artifact_id,parent_run_id,status,input_json,"
            "source_revision,created_at,updated_at) VALUES(?,2,?,?,'queued',?,?,?,?)",
            (owner_id, artifact_id, fixed["request"]["parent_run_id"], canonical_json(fixed),
             fixed["profile_revision"], now, now),
        )
        return owner_id

    def create_run(self, fixed: dict) -> str:
        with self.connection(immediate=True) as conn:
            return self._create_run(fixed, conn)

    def legacy_child(self, legacy_id: str) -> str | None:
        with self.connection() as conn:
            row = conn.execute("SELECT value FROM migration_meta WHERE key=?",
                               ("legacy_recovery:" + legacy_id,)).fetchone()
            return row[0] if row else None

    def create_legacy_child(self, legacy_id: str, fixed: dict, evidence: dict) -> str:
        """Publish one child and link atomically; never constrain other revisions."""
        from .checkpoint import write_v2_checkpoint

        with self.connection(immediate=True) as conn:
            key = "legacy_recovery:" + legacy_id
            existing = conn.execute("SELECT value FROM migration_meta WHERE key=?", (key,)).fetchone()
            if existing:
                return existing[0]
            owner_id = self._create_run(fixed, conn)
            # The child remains invisible until its evidence checkpoint exists.
            # A failed cross-database write rolls back both child and link.
            write_v2_checkpoint(self.checkpoint_path, "run", owner_id, {
                "schema_version": 2, "values": {"legacy_parent": legacy_id, "legacy_evidence_answers": evidence},
                "index": None, "inflight_action_ids": [],
            })
            conn.execute("INSERT INTO migration_meta VALUES (?,?)", (key, owner_id))
            return owner_id

    def run_ids(self) -> list[str]:
        with self.connection() as conn:
            return [row[0] for row in conn.execute("SELECT id FROM runs ORDER BY created_at,id")]

    def create_operation(self, kind: str, values: dict) -> str:
        owner_id, now = str(uuid4()), utc_now()
        with self.connection(immediate=True) as conn:
            conn.execute(
                "INSERT INTO operations(id,kind,status,input_json,created_at,updated_at) "
                "VALUES(?,?,'pending_model',?,?,?)",
                (owner_id, kind, canonical_json(values), now, now),
            )
        return owner_id

    def cancellation(self, kind: str, owner_id: str, conn: sqlite3.Connection | None = None) -> bool:
        if conn is None:
            with self.connection() as connection:
                return self.cancellation(kind, owner_id, connection)
        return conn.execute("SELECT 1 FROM cancellations WHERE owner_kind=? AND owner_id=?",
                            (kind, owner_id)).fetchone() is not None

    def cancel(self, kind: str, owner_id: str) -> None:
        with self.connection(immediate=True) as conn:
            row = self.row(kind, owner_id, conn)
            if row["status"] == "complete":
                return
            conn.execute(
                "INSERT OR IGNORE INTO cancellations(owner_kind,owner_id,action_id,requested_at) VALUES(?,?,?,?)",
                (kind, owner_id, str(uuid4()), utc_now()),
            )
            if row["status"] != "running":
                self.update(kind, owner_id, status="cancelled", pending=None,
                            result=json.loads(row["result_json"]) if row["result_json"] else None,
                            code=row.get("error_code"), stage=row.get("error_stage"), conn=conn)

    def update(self, kind: str, owner_id: str, *, status: str, pending: dict | None,
               result: dict | None = None, code: str | None = None, stage: str | None = None,
               conn: sqlite3.Connection) -> None:
        assignments = "status=?,pending_json=?,result_json=?,updated_at=?"
        values = [status, canonical_json(pending) if pending is not None else None,
                  canonical_json(result) if result is not None else None, utc_now()]
        if kind == "run":
            assignments += ",error_code=?,error_stage=?"
            values += [code, stage]
        conn.execute(f"UPDATE {TABLES[kind]} SET {assignments} WHERE id=?", (*values, owner_id))

    def action(self, kind: str, owner_id: str, action_id: str,
               conn: sqlite3.Connection) -> dict | None:
        row = conn.execute("SELECT * FROM actions WHERE owner_kind=? AND owner_id=? AND action_id=?",
                           (kind, owner_id, action_id)).fetchone()
        return dict(row) if row else None

    def accept(self, kind: str, owner_id: str, action: dict, request_hash: str,
               conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO actions(owner_kind,owner_id,action_id,request_hash,request_json,status,created_at) "
            "VALUES(?,?,?,?,?,'accepted',?)",
            (kind, owner_id, action["action_id"], request_hash, canonical_json(action), utc_now()),
        )

    def unfinished(self, kind: str, owner_id: str, conn: sqlite3.Connection) -> list[dict]:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM actions WHERE owner_kind=? AND owner_id=? AND status='accepted' ORDER BY created_at",
            (kind, owner_id))]

    def finish_actions(self, kind: str, owner_id: str, action_ids: list[str], view: dict,
                       conn: sqlite3.Connection) -> None:
        for action_id in action_ids:
            conn.execute("UPDATE actions SET status=?,result_json=? WHERE owner_kind=? AND owner_id=? AND action_id=? AND status='accepted'",
                         ("failed" if view["status"] == "failed" else "complete", canonical_json(view),
                          kind, owner_id, action_id))

    def release(self, owner_id: str, conn: sqlite3.Connection | None = None) -> dict | None:
        if conn is None:
            with self.connection() as connection:
                return self.release(owner_id, connection)
        row = conn.execute("SELECT * FROM release_records WHERE run_id=?", (owner_id,)).fetchone()
        return dict(row) if row else None

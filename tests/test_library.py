"""Résumé library persistence: upsert, grouping, delete, and JSONL migration."""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    """Reload the library module pointed at a temp CONFIG_DIR so tests are isolated."""
    from resume_agent import config

    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path, raising=True)
    import resume_agent.library as library

    library = importlib.reload(library)
    monkeypatch.setattr(library, "CONFIG_DIR", tmp_path, raising=True)
    monkeypatch.setattr(library, "LIBRARY_DB", tmp_path / "library.sqlite", raising=True)
    monkeypatch.setattr(library, "_HISTORY_FILE", tmp_path / "run_history.jsonl", raising=True)
    library.init_db()
    yield library


def test_upsert_creates_company_and_resume(lib):
    lib.upsert_resume(thread_id="t1", company="TechCorp", role="Senior SWE", status="complete", pdf_path="/out/a.pdf")

    companies = lib.list_companies()
    assert [c["name"] for c in companies] == ["TechCorp"]
    assert companies[0]["total"] == 1 and companies[0]["final"] == 1

    resumes = lib.list_resumes()
    assert len(resumes) == 1
    assert resumes[0]["company"] == "TechCorp"
    assert resumes[0]["pdf_url"] == "/api/runs/t1/pdf"  # complete + pdf → downloadable


def test_job_location_and_work_mode_survive_library_updates(lib):
    lib.upsert_resume(thread_id="context", company="Example", location="Pune, India", work_mode="Hybrid")
    lib.upsert_resume(thread_id="context", company="Example", status="complete", location="Pune, India", work_mode="Remote", remote_policy="Remote within India")
    assert lib.get_resume("context")["location"] == "Pune, India"
    assert lib.list_resumes()[0]["work_mode"] == "Remote"
    assert lib.list_resumes()[0]["remote_policy"] == "Remote within India"


def test_existing_library_is_migrated_without_losing_rows(lib):
    with lib._connect() as conn:
        conn.execute("DROP TABLE resumes")
        conn.execute("CREATE TABLE resumes (thread_id TEXT PRIMARY KEY, company_id INTEGER, role TEXT, status TEXT, pdf_path TEXT, error TEXT, duration_s REAL, created_at REAL, updated_at REAL)")
        conn.execute("INSERT INTO companies (id, name, created_at) VALUES (10, 'Legacy', 1)")
        conn.execute("INSERT INTO resumes VALUES ('old', 10, 'Engineer', 'complete', NULL, NULL, 1, 1, 1)")
    lib.init_db()
    lib.init_db()
    assert lib.get_resume("old")["company"] == "Legacy"
    assert lib.get_resume("old")["location"] is None
    lib.upsert_resume(thread_id="new", company="Example", location="Berlin, Germany", work_mode="On-site")
    assert lib.get_resume("new")["work_mode"] == "On-site"


def test_upsert_is_idempotent_and_updates_status(lib):
    lib.upsert_resume(thread_id="t1", company="TechCorp", role="SWE", status="running")
    lib.upsert_resume(thread_id="t1", company="TechCorp", role="SWE", status="complete", pdf_path="/out/a.pdf")

    resumes = lib.list_resumes()
    assert len(resumes) == 1  # same thread_id → updated, not duplicated
    assert resumes[0]["status"] == "complete"


def test_grouping_and_filter_by_company(lib):
    lib.upsert_resume(thread_id="t1", company="TechCorp", status="complete", pdf_path="/o/a.pdf")
    lib.upsert_resume(thread_id="t2", company="TechCorp", status="failed")
    lib.upsert_resume(thread_id="t3", company="Lattice", status="awaiting-input")

    names = {c["name"]: c for c in lib.list_companies()}
    assert names["TechCorp"]["total"] == 2 and names["TechCorp"]["failed"] == 1
    assert names["Lattice"]["needs"] == 1

    assert {r["thread_id"] for r in lib.list_resumes(company="TechCorp")} == {"t1", "t2"}


def test_delete_removes_resume_and_empty_company(lib):
    lib.upsert_resume(thread_id="t1", company="Solo", status="complete", pdf_path="/o/a.pdf")
    assert lib.delete_resume("t1") is True
    assert lib.list_resumes() == []
    assert lib.list_companies() == []  # company with no resumes is cleaned up
    assert lib.delete_resume("missing") is False


def test_migrate_from_jsonl(lib, tmp_path):
    history = tmp_path / "run_history.jsonl"
    history.write_text(
        "\n".join(
            json.dumps(rec)
            for rec in [
                {"thread_id": "h1", "company": "Northwind", "role": "Platform", "status": "complete", "pdf_path": "/o/n.pdf", "started_wall_ts": 100.0},
                {"thread_id": "h2", "company": "Boltline", "status": "failed", "started_wall_ts": 200.0},
                {"not_a_row": True},
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    imported = lib.migrate_from_jsonl(history)
    assert imported == 2
    assert {r["thread_id"] for r in lib.list_resumes()} == {"h1", "h2"}
    # Re-running must not duplicate (idempotent upsert by thread_id).
    lib.migrate_from_jsonl(history)
    assert len(lib.list_resumes()) == 2

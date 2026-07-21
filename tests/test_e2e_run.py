"""End-to-end pipeline test with no external services (no LLM, no Tectonic, no Poppler).

The graph binds its node functions as ``resume_agent.graph`` module globals, so we
replace just the LLM- and binary-dependent nodes with deterministic fakes and let the
REAL orchestration run: routing, the checkpointer, suggestion application, output_saver
(a real file copy), run_manager persistence, the SQLite library, and the API endpoints.

This proves the whole chain works — create → generate → filed in the library →
downloadable — without needing an API key or a LaTeX toolchain installed.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from resume_agent.config import OutputConfig, ResumeAgentSettings
from resume_agent.schemas import GapAnalysis, JobDescription, PersonalInfo, Role, UserResume

RESUME = UserResume(
    personal=PersonalInfo(full_name="Aldrin Carlos", email="aldrin@example.com"),
    summary="Backend engineer with 6 years building distributed systems in Python.",
    experience=[
        Role(company="Acme Corp", title="Software Engineer II", start="Jan 2022", end="Present",
             bullets=["Built a Python microservices platform", "Cut p99 latency 80%"],
             tech=["Python", "FastAPI", "Docker"]),
    ],
    skills={"Languages": ["Python", "SQL"], "Infrastructure": ["Docker", "Kubernetes"]},
)
JD = JobDescription(
    company="TechCorp", role_title="Senior Software Engineer", seniority="Senior",
    must_have_skills=["Python", "Kubernetes"], nice_to_have_skills=["Go"],
    keywords=["distributed", "microservices"],
)

_MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


@pytest.fixture()
def fake_pipeline(tmp_path, monkeypatch):
    """Patch the graph's LLM/binary nodes with deterministic fakes; return output dir."""
    import resume_agent.graph as g

    compiled_pdf = tmp_path / "compiled.pdf"
    compiled_pdf.write_bytes(_MINIMAL_PDF)

    fakes = {
        "load_base_resume_node":    lambda state, **_: {"base_resume": RESUME},
        "jd_extractor_node":        lambda state, **_: {"jd": JD},
        "gap_analyzer_node":        lambda state, **_: {"gap_analysis": GapAnalysis(open_questions=[], tailoring_ideas=[])},
        "suggestion_presenter_node": lambda state, **_: {"tailored_resume": RESUME, "approved_suggestion_ids": []},
        "resume_generator_node":    lambda state, **_: {"latex_source": "\\documentclass{article}\\begin{document}CV\\end{document}", "generator_retries": 0},
        "resume_lint_node":         lambda state, **_: {"lint_feedback": None},
        "latex_validator_node":     lambda state, **_: {"latex_errors": []},
        "pdf_compiler_node":        lambda state, **_: {"pdf_path": str(compiled_pdf), "pdf_errors": []},
        "render_pages_node":        lambda state, **_: {"page_images": []},
        "pdf_validator_node":       lambda state, **_: {"validation_passed": True, "validation_feedback": None},
        "hr_review_node":           lambda state, **_: {"validation_passed": True},
    }
    for name, fn in fakes.items():
        monkeypatch.setattr(g, name, fn, raising=True)

    return tmp_path / "output"


def _initial_state():
    from resume_agent.state import STATE_SCHEMA_VERSION
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "input_type": "text",
        "raw_input": "Senior Software Engineer at TechCorp — Python, Kubernetes, distributed systems.",
        "latex_errors": [], "pdf_errors": [], "page_images": [], "suggestions": [],
        "generator_retries": 0, "validation_passed": False, "messages": [],
    }


def test_full_pipeline_produces_a_saved_pdf(fake_pipeline):
    """The real graph runs end-to-end and output_saver writes a filed PDF."""
    from langgraph.checkpoint.memory import InMemorySaver

    from resume_agent.graph import build_graph

    settings = ResumeAgentSettings(output=OutputConfig(base_dir=str(fake_pipeline)))
    graph = build_graph(checkpointer=InMemorySaver(), settings=settings)

    result = graph.invoke(_initial_state(), {"configurable": {"thread_id": "e2e-1"}})

    final = result.get("final_pdf_path")
    assert final, "pipeline did not produce a final_pdf_path"
    from pathlib import Path
    saved = Path(final)
    assert saved.exists() and saved.read_bytes().startswith(b"%PDF")
    # Filed under the company slug, as the library expects.
    assert "techcorp" in str(saved).lower()


@pytest.fixture()
def library_at(tmp_path, monkeypatch):
    from resume_agent import config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path, raising=True)
    import resume_agent.library as library
    library = importlib.reload(library)
    monkeypatch.setattr(library, "LIBRARY_DB", tmp_path / "library.sqlite", raising=True)
    monkeypatch.setattr(library, "_HISTORY_FILE", tmp_path / "run_history.jsonl", raising=True)
    library.init_db()
    return library


def test_run_manager_files_completed_run_into_library(tmp_path, monkeypatch, library_at):
    """run_manager._save_run must persist a finished run into the SQLite library."""
    import resume_agent.api.run_manager as rmmod
    monkeypatch.setattr(rmmod, "library", library_at, raising=True)
    monkeypatch.setattr(rmmod, "_HISTORY_FILE", tmp_path / "history.jsonl", raising=True)

    pdf = tmp_path / "aldrin_techcorp.pdf"
    pdf.write_bytes(_MINIMAL_PDF)

    session = rmmod.RunSession(thread_id="run-1", status="complete", company="TechCorp",
                               role="Senior Software Engineer", pdf_path=str(pdf), stored_duration_s=42.0)
    rmmod.run_manager._save_run(session)

    filed = library_at.list_resumes()
    assert [r["thread_id"] for r in filed] == ["run-1"]
    assert filed[0]["company"] == "TechCorp"
    assert filed[0]["pdf_url"] == "/api/runs/run-1/pdf"  # complete + pdf → downloadable
    assert [c["name"] for c in library_at.list_companies()] == ["TechCorp"]


def test_library_api_serves_filed_resumes(library_at):
    """The /api/library endpoints return what was filed (real FastAPI app)."""
    library_at.upsert_resume(thread_id="run-2", company="Lattice Robotics",
                             role="Staff Backend Engineer", status="complete", pdf_path="/o/x.pdf")

    from resume_agent.api.app import create_app
    client = TestClient(create_app())

    companies = client.get("/api/library/companies")
    assert companies.status_code == 200
    assert any(c["name"] == "Lattice Robotics" for c in companies.json())

    resumes = client.get("/api/library/resumes?company=Lattice Robotics")
    assert resumes.status_code == 200
    body = resumes.json()
    assert len(body) == 1 and body[0]["thread_id"] == "run-2"
    assert body[0]["pdf_url"] == "/api/runs/run-2/pdf"


def test_run_manager_drives_a_run_to_completion(tmp_path, monkeypatch, fake_pipeline, library_at):
    """Drive the REAL server code path (run_manager._drive) to a filed, downloadable run."""
    import asyncio
    from pathlib import Path

    import resume_agent.api.run_manager as rmmod
    import resume_agent.checkpoint as ckpt

    settings = ResumeAgentSettings(output=OutputConfig(base_dir=str(fake_pipeline)))
    monkeypatch.setattr(rmmod.ResumeAgentSettings, "load", staticmethod(lambda: settings), raising=True)
    monkeypatch.setattr(rmmod, "library", library_at, raising=True)
    monkeypatch.setattr(rmmod, "_HISTORY_FILE", tmp_path / "history.jsonl", raising=True)
    monkeypatch.setattr(ckpt, "STATE_DB", tmp_path / "state.sqlite", raising=True)
    monkeypatch.setattr(ckpt, "CONFIG_DIR", tmp_path, raising=True)

    async def go():
        rm = rmmod.RunManager()
        session = await rm.start_run({"jd_text": "Senior Software Engineer at TechCorp — Python, Kubernetes."})
        await session.task
        return session

    session = asyncio.run(go())

    assert session.status == "complete"
    assert session.company == "TechCorp" and session.role == "Senior Software Engineer"
    assert session.pdf_path and Path(session.pdf_path).exists()

    filed = library_at.list_resumes()
    assert session.thread_id in {r["thread_id"] for r in filed}
    assert next(r for r in filed if r["thread_id"] == session.thread_id)["pdf_url"] == f"/api/runs/{session.thread_id}/pdf"

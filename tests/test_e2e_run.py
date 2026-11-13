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
    from resume_agent.state import LEGACY_STATE_SCHEMA_VERSION
    return {
        "schema_version": LEGACY_STATE_SCHEMA_VERSION,
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


async def test_run_manager_persists_queued_and_pending_before_release(tmp_path):
    from resume_agent.api.run_manager import RunManager
    from tests.test_v2_api import services
    runtime, _ = services(tmp_path)
    manager = RunManager(runtime)
    queued = await manager.start_run({'jd_text': 'Full engineering posting'})
    assert runtime.store.row('run', queued['id'])['status'] == 'queued'
    await manager.wait(queued['id'])
    reopened = RunManager(runtime).get_run(queued['id'])
    assert reopened['status'] == 'awaiting-input'
    assert reopened['pending']['kind'] == 'present_suggestions'
    assert reopened['pdf_url'] is None
    assert runtime.store.release(queued['id']) is None


def test_library_api_serves_existing_legacy_and_marks_missing_bytes(tmp_path, library_at):
    from resume_agent.api.app import create_app
    from resume_agent.runtime import Runtime
    library_at.upsert_resume(thread_id='run-2', company='Lattice Robotics', role='Staff Backend Engineer',
                             status='complete', pdf_path='/o/x.pdf')
    runtime = Runtime(root=tmp_path, settings=ResumeAgentSettings())
    with TestClient(create_app(services=runtime), base_url='http://localhost') as client:
        companies = client.get('/api/library/companies').json()
        assert any(c['name'] == 'Lattice Robotics' for c in companies)
        body = client.get('/api/library/resumes?company=Lattice Robotics').json()
        assert len(body) == 1 and body[0]['thread_id'] == 'run-2'
        assert body[0]['artifact_status'] == 'missing'
        assert body[0]['pdf_url'] is None
        assert body[0]['legacy'] is True


def test_real_api_requires_both_reviews_then_serves_identical_released_bytes(tmp_path):
    from resume_agent.api.app import create_app
    from resume_agent.checkpoint import read_v2_checkpoint
    from resume_agent.content_review import expected_display_text
    from resume_agent.schemas import RenderManifest
    from resume_agent.tools.tectonic_compile import CompileResult
    from tests.test_approved_render import images
    from tests.test_pdf_content_check import make_pdf
    from tests.test_v2_api import services
    runtime, calls = services(tmp_path)
    runtime.workflow.output_dir = tmp_path / 'output'
    def compiler(source, *, output_dir):
        run_id = runtime.store.run_ids()[-1]
        manifest = read_v2_checkpoint(runtime.store.checkpoint_path, 'run', run_id)['values']['manifest']
        pdf = make_pdf(output_dir / 'resume.pdf', expected_display_text(RenderManifest.model_validate(manifest)))
        return CompileResult(True, str(pdf), [], '')
    runtime.workflow.compile_adapter, runtime.workflow.image_adapter = compiler, images
    with TestClient(create_app(services=runtime), base_url='http://localhost') as client:
        created = client.post('/api/runs', json={'jd_text': 'Complete JD'}).json()
        run_id = created['id']
        for _ in range(50):
            paused = client.get('/api/runs/' + run_id).json()
            if paused['pending']:
                break
        assert paused['pending']['kind'] == 'present_suggestions'
        assert client.get(f'/api/runs/{run_id}/pdf').status_code == 409
        pending = paused['pending']
        preview = client.post(f'/api/runs/{run_id}/content-preview', json={
            'review_id': pending['review_id'], 'source_revision': pending['source_revision'], 'approved_ids': []}).json()
        action = {'kind': 'present_suggestions', 'action_id': 'content', 'review_id': pending['review_id'],
                  'source_revision': pending['source_revision'], 'approved_ids': [], 'content_hash': preview['manifest']['content_hash']}
        stale = client.post(f'/api/runs/{run_id}/resume', json=action | {'content_hash': '0' * 64})
        assert stale.status_code == 409
        pdf_pending = client.post(f'/api/runs/{run_id}/resume', json=action).json()
        assert pdf_pending['pending']['kind'] == 'review_pdf'
        draft = client.get(f'/api/runs/{run_id}/preview')
        assert draft.status_code == 200 and draft.headers['content-type'] == 'application/pdf'
        review = pdf_pending['pending']['review']
        approved = client.post(f'/api/runs/{run_id}/resume', json={'kind': 'review_pdf', 'payload': {
            'action_id': 'pdf', 'decision': 'approve', **{key: review[key] for key in
                ('review_id', 'content_hash', 'render_hash', 'pdf_hash')}}})
        assert approved.status_code == 200 and approved.json()['status'] == 'complete'
        assert client.get(f'/api/runs/{run_id}/pdf').content == draft.content
        assert client.get(f'/api/runs/{run_id}/preview').status_code == 409
        assert client.get('/api/library/resumes').json()[0]['id'] == run_id
        assert client.get('/api/library/companies').json()[0]['final'] == 1
        assert client.delete('/api/library/resumes/' + run_id).status_code == 409
        with client.websocket_connect('/ws/runs/' + run_id, headers={'host': 'localhost'}) as socket:
            assert socket.receive_json()['type'] == 'run_state'
            assert socket.receive_json()['type'] == 'run_state'
            complete = socket.receive_json()
            assert complete['type'] == 'complete' and complete['pdf_hash'] == review['pdf_hash']
    assert calls == ['extract_jd', 'questions', 'proposals']


async def test_real_graph_stream_emits_one_lifecycle_per_node(fake_pipeline):
    """Model/parser child traces must not inflate displayed time or progress."""
    from collections import Counter

    from langgraph.checkpoint.memory import InMemorySaver

    from resume_agent.api.streaming import StreamTranslator
    from resume_agent.graph import build_graph

    settings = ResumeAgentSettings(output=OutputConfig(base_dir=str(fake_pipeline)))
    graph = build_graph(checkpointer=InMemorySaver(), settings=settings)
    translator = StreamTranslator()
    events = []
    async for raw in graph.astream_events(_initial_state(), {"configurable": {"thread_id": "stream-e2e"}}, version="v2"):
        events.extend(translator.translate(raw))
    starts = Counter(event.node_id for event in events if event.type == "node_start")
    ends = Counter(event.node_id for event in events if event.type == "node_end")
    assert starts == ends
    assert starts['extract_jd'] == 1
    assert starts['compile_pdf'] == 1
    assert all(count == 1 for count in starts.values())

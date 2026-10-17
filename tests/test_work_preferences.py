"""Job context and candidate preferences survive extraction, editing and history."""
import json
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from resume_agent.agents import gap_analyzer, hitl, jd_extractor
from resume_agent.config import ResumeAgentSettings
from resume_agent.schemas import GapAnalysis, JobDescription, UserResume


def candidate():
    return UserResume.model_validate({
        "personal": {"full_name": "Test User", "email": "test@example.com", "location": "Kochi, India"},
        "work_preferences": {"preferred_locations": ["Bengaluru, India", "London, UK"], "work_modes": ["Remote", "Hybrid"]},
    })


def test_candidate_preferences_are_distinct_from_current_location():
    resume = candidate()
    assert resume.model_dump()["work_preferences"] == {
        "preferred_locations": ["Bengaluru, India", "London, UK"], "work_modes": ["Remote", "Hybrid"],
    }
    assert resume.personal.location == "Kochi, India"
    assert UserResume(personal=resume.personal).model_dump()["work_preferences"] == {
        "preferred_locations": [], "work_modes": [],
    }


def test_invalid_preference_mode_is_rejected():
    data = candidate().model_dump()
    data["work_preferences"] = {"work_modes": ["Occasionally"]}
    with pytest.raises(ValidationError):
        UserResume.model_validate(data)


def test_resume_api_roundtrips_saved_work_preferences(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from resume_agent.api.app import create_app
    from resume_agent.api.routers import resume as router

    monkeypatch.setattr(router, "BASE_RESUME_FILE", tmp_path / "resume.yaml")
    client = TestClient(create_app(), base_url="http://localhost")
    data = candidate().model_dump()
    assert client.put("/api/resume", json=data).status_code == 200
    assert client.get("/api/resume").json() == data


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("overrides,want", [
    ({"job_location": "Chennai, India", "work_mode": "On-site"}, ("Chennai, India", "On-site")),
    ({}, ("London, UK", None)),
])
def test_job_context_overrides_extraction_without_inventing_missing_values(monkeypatch, fallback, overrides, want):
    parsed = JobDescription(company="Example", role_title="Engineer", location="London, UK", remote_policy="Hybrid: 2 days per week")
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = parsed
    if fallback:
        llm.with_structured_output.return_value.invoke.side_effect = ValueError("bad JSON")
        llm.invoke.return_value.content = parsed.model_dump_json()
    monkeypatch.setattr(jd_extractor, "get_chat_model", lambda *a, **k: llm)
    result = jd_extractor.jd_extractor_node({"raw_input": "Job posting. " * 20, **overrides}, settings=ResumeAgentSettings(_env_file=None))
    assert (result["jd"].location, getattr(result["jd"], "work_mode", None)) == want
    assert result["jd"].remote_policy == "Hybrid: 2 days per week"


def test_gap_analysis_receives_both_sides_of_location_and_work_mode(monkeypatch):
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = GapAnalysis()
    monkeypatch.setattr(gap_analyzer, "get_chat_model", lambda *a, **k: llm)
    gap_analyzer.gap_analyzer_node({"base_resume": candidate(), "jd": JobDescription(
        company="Example", role_title="Engineer", location="London, UK", work_mode="On-site", remote_policy="UK only; three office days per week",
    )}, settings=ResumeAgentSettings(_env_file=None))
    prompt = llm.with_structured_output.return_value.invoke.call_args.args[0][1].content
    assert "Kochi, India" in prompt
    assert "Bengaluru, India" in prompt
    assert "London, UK" in prompt
    assert "Remote" in prompt and "Hybrid" in prompt and "On-site" in prompt
    assert "UK only; three office days per week" in prompt


def test_review_answers_do_not_rewrite_current_location_or_preferences(monkeypatch):
    base = candidate()
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = UserResume(
        personal={"full_name": "Test User", "email": "test@example.com", "location": "London, UK"},
    )
    monkeypatch.setattr(hitl, "get_chat_model", lambda *a, **k: llm)
    monkeypatch.setattr(hitl, "interrupt", lambda _: {"answers": {"q1": "I can discuss the hybrid schedule."}})
    result = hitl.hitl_node({"base_resume": base, "gap_analysis": GapAnalysis(open_questions=[
        {"id": "q1", "prompt": "Does hybrid work for you?", "why_asking": "Work mode"},
    ])}, settings=ResumeAgentSettings(_env_file=None))["tailored_resume"]
    assert result.personal.location == "Kochi, India"
    assert result.model_dump()["work_preferences"] == base.model_dump()["work_preferences"]


def test_run_metadata_keeps_job_context_and_candidate_snapshot(tmp_path, monkeypatch):
    import resume_agent.api.run_manager as module

    monkeypatch.setattr(module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(module, "_HISTORY_FILE", tmp_path / "history.jsonl")
    monkeypatch.setattr(module.library, "upsert_resume", lambda **kwargs: None)
    manager = object.__new__(module.RunManager)
    manager._sessions = {}
    session = module.RunSession(thread_id="context", status="failed")
    manager._refresh_meta(session, {"jd": JobDescription(company="Example", role_title="Engineer",
        location="London, UK", work_mode="Hybrid", remote_policy="UK only; two office days"), "base_resume": candidate()})
    manager._save_run(session)
    manager._load_history()
    data = module.run_detail(manager.get_run("context"))
    assert data["location"] == "London, UK" and data["work_mode"] == "Hybrid"
    assert data["remote_policy"] == "UK only; two office days"
    assert data["work_preferences"] == {
        "preferred_locations": ["Bengaluru, India", "London, UK"], "work_modes": ["Remote", "Hybrid"],
    }
    assert json.loads((tmp_path / "history.jsonl").read_text())["location"] == "London, UK"


async def test_start_run_passes_manual_job_context_to_graph(tmp_path, monkeypatch):
    import resume_agent.api.run_manager as module
    from resume_agent.api.routers.runs import CreateRunRequest

    monkeypatch.setattr(module, "_HISTORY_FILE", tmp_path / "absent.jsonl")
    manager = object.__new__(module.RunManager)
    manager._sessions = {}
    manager._jd_files = {}
    import asyncio
    manager._lock = asyncio.Lock()
    captured = []
    async def drive(session, state):
        captured.append(state)
    monkeypatch.setattr(manager, "_drive", drive)
    request = CreateRunRequest(jd_text="Posting", job_location="Pune, India", work_mode="Remote")
    session = await manager.start_run(request.model_dump())
    await session.task
    assert captured[0]["job_location"] == "Pune, India"
    assert captured[0]["work_mode"] == "Remote"

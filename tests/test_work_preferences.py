"""Job context and candidate preferences survive extraction, editing and history."""
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
    from resume_agent.runtime import Runtime
    services = Runtime(root=tmp_path, settings=ResumeAgentSettings())
    client = TestClient(create_app(services=services), base_url="http://localhost")
    data = candidate().model_dump()
    assert client.put("/api/resume", json=data).status_code == 200
    assert client.get("/api/resume").json() == data


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("overrides,want", [
    ({"job_location": "Chennai, India", "work_mode": "On-site"}, ("Chennai, India", "On-site")),
    ({}, ("London, UK", None)),
])
def test_job_context_overrides_extraction_without_inventing_missing_values(monkeypatch, retry, overrides, want):
    parsed = JobDescription(company="Example", role_title="Engineer", location="London, UK", remote_policy="Hybrid: 2 days per week")
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = parsed
    if retry:
        llm.with_structured_output.return_value.invoke.side_effect = [ValidationError.from_exception_data("JobDescription", [{"type": "missing", "loc": ("company",), "input": {}}]), parsed]
    monkeypatch.setattr(jd_extractor, "get_chat_model", lambda *a, **k: llm)
    result = jd_extractor.jd_extractor_node({"raw_input": "Job posting. " * 20, **overrides}, settings=ResumeAgentSettings(_env_file=None))
    assert (result["jd"].location, getattr(result["jd"], "work_mode", None)) == want
    assert result["jd"].remote_policy == "Hybrid: 2 days per week"
    llm.invoke.assert_not_called()


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


async def test_run_metadata_keeps_job_context_and_candidate_snapshot(tmp_path):
    from resume_agent.api.v2_manager import V2RunManager
    from resume_agent.runtime import Runtime
    async def model(stage, schema, messages):
        if stage == 'extract_jd':
            return JobDescription(company='Example', role_title='Engineer', location='London, UK',
                                  work_mode='Hybrid', remote_policy='UK only; two office days')
        return {'questions': []} if stage == 'questions' else {'proposals': []}
    runtime = Runtime(root=tmp_path, settings=ResumeAgentSettings(), model=model, tool_finder=lambda _: '/local')
    runtime.profiles.save_reviewed(None, candidate(), {})
    manager = V2RunManager(runtime)
    created = await manager.start_run({'jd_text': 'Full posting'})
    await manager.wait(created['id'])
    data = V2RunManager(Runtime(root=tmp_path, settings=ResumeAgentSettings(), model=model)).get_run(created['id'])
    assert data['location'] == 'London, UK' and data['work_mode'] == 'Hybrid'
    assert data['remote_policy'] == 'UK only; two office days'
    assert data['work_preferences'] == candidate().work_preferences.model_dump()


async def test_start_run_freezes_manual_job_context_before_background_work(tmp_path):
    from resume_agent.api.v2_manager import V2RunManager
    from tests.test_v2_api import services
    runtime, calls = services(tmp_path)
    manager = V2RunManager(runtime)
    created = await manager.start_run({'jd_text': 'Posting', 'job_location': 'Pune, India', 'work_mode': 'Remote'})
    fixed = runtime.store.input('run', created['id'])
    assert fixed['request']['job_location'] == 'Pune, India'
    assert fixed['request']['work_mode'] == 'Remote'
    await manager.wait(created['id'])
    final = manager.get_run(created['id'])
    assert final['location'] == 'Pune, India' and final['work_mode'] == 'Remote'

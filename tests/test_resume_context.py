"""Multi-page profiles must reach analysis and enrichment without chopped JSON."""
import json
from unittest.mock import MagicMock

import pytest

from resume_agent.config import ResumeAgentSettings
from resume_agent.schemas import (
    GapAnalysis,
    JobDescription,
    PersonalInfo,
    Project,
    Question,
    Role,
    UserResume,
)


@pytest.fixture
def long_resume():
    return UserResume(
        personal=PersonalInfo(full_name="Test Candidate", email="test@example.com"),
        summary="Engineer with experience in production AI systems.",
        experience=[Role(company="Example", title="Engineer", start="2022", bullets=[
            f"Built service {i} with production monitoring and regression coverage. " * 4
            for i in range(30)
        ])],
        projects=[Project(name="Final contribution", description="Final project details", bullets=["PRESERVE_LAST_PROJECT"])],
        education=[], skills={"Languages": ["Python"]},
    )


def test_gap_analysis_receives_complete_long_profile(long_resume, monkeypatch):
    from resume_agent.agents import gap_analyzer
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = GapAnalysis()
    monkeypatch.setattr(gap_analyzer, "get_chat_model", lambda *a, **k: llm)
    gap_analyzer.gap_analyzer_node({"base_resume": long_resume, "jd": JobDescription(
        company="Example", role_title="AI Engineer",
    )}, settings=ResumeAgentSettings())
    message = llm.with_structured_output.return_value.invoke.call_args.args[0][1].content
    context = message.split("USER RESUME:\n", 1)[1].split("\n\nJOB DESCRIPTION:", 1)[0]
    assert json.loads(context)["projects"][-1]["bullets"] == ["PRESERVE_LAST_PROJECT"]


def test_enrichment_receives_complete_long_profile(long_resume, monkeypatch):
    from resume_agent.agents import hitl
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = long_resume
    monkeypatch.setattr(hitl, "get_chat_model", lambda *a, **k: llm)
    monkeypatch.setattr(hitl, "interrupt", lambda _: {"answers": {"q1": "No additional experience."}})
    hitl.hitl_node({"base_resume": long_resume, "gap_analysis": GapAnalysis(
        open_questions=[Question(id="q1", prompt="Any additional experience?", why_asking="Clarify scope")],
    )}, settings=ResumeAgentSettings())
    message = llm.with_structured_output.return_value.invoke.call_args.args[0][1].content
    context = message.split("ORIGINAL RESUME:\n", 1)[1].split("\n\nUSER ANSWERS", 1)[0]
    assert json.loads(context)["projects"][-1]["bullets"] == ["PRESERVE_LAST_PROJECT"]


def test_hr_review_receives_end_of_multi_page_resume(monkeypatch):
    from resume_agent.agents import hr_review
    source = "\\begin{document}\n" + "Resume content. " * 800 + "LAST_RESUME_SECTION\n\\end{document}"
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = hr_review.HRReviewResult()
    monkeypatch.setattr(hr_review, "get_chat_model", lambda *a, **k: llm)
    hr_review.hr_review_node({"latex_source": source}, settings=ResumeAgentSettings())
    message = llm.with_structured_output.return_value.invoke.call_args.args[0][1].content
    assert "LAST_RESUME_SECTION" in message


def test_hr_review_is_grounded_in_current_date(monkeypatch):
    from datetime import date

    from resume_agent.agents import hr_review

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 17)

    monkeypatch.setattr(hr_review, "date", FixedDate, raising=False)
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = hr_review.HRReviewResult()
    monkeypatch.setattr(hr_review, "get_chat_model", lambda *a, **k: llm)
    hr_review.hr_review_node({"latex_source": "Pine Labs: Jul 2026 -- Present"}, settings=ResumeAgentSettings())
    message = llm.with_structured_output.return_value.invoke.call_args.args[0][1].content
    assert "Current date: 2026-10-17" in message


def test_hr_metric_density_does_not_trigger_rewrite(monkeypatch):
    from resume_agent.agents import hr_review
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = hr_review.HRReviewResult(
        overall_pass=False, scores=[
            hr_review.HRReviewScore(name="metric_density", score=0.2),
            hr_review.HRReviewScore(name="title_plausibility", score=0.4),
        ], feedback="Add more metrics and review the title.",
    )
    monkeypatch.setattr(hr_review, "get_chat_model", lambda *a, **k: llm)
    result = hr_review.hr_review_node({"latex_source": "Source resume"}, settings=ResumeAgentSettings())
    assert result == {}


def test_hr_two_substantive_issues_still_trigger_rewrite(monkeypatch):
    from resume_agent.agents import hr_review
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = hr_review.HRReviewResult(
        overall_pass=False, scores=[
            hr_review.HRReviewScore(name="action_verb_coverage", score=0.2),
            hr_review.HRReviewScore(name="buzzword_density", score=0.3),
        ], feedback="Remove buzzwords and improve action verbs.",
    )
    monkeypatch.setattr(hr_review, "get_chat_model", lambda *a, **k: llm)
    result = hr_review.hr_review_node({"latex_source": "Source resume"}, settings=ResumeAgentSettings())
    assert result["validation_passed"] is False
    assert "Remove buzzwords" in result["validation_feedback"]

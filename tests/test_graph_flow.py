"""
Integration test for the full graph flow using stubbed LLM responses.

Tests that the graph routes correctly and state propagates as expected
without making actual LLM API calls.
"""

import pytest

from resume_agent.schemas import (
    GapAnalysis,
    JobDescription,
    PersonalInfo,
    Role,
    UserResume,
)


@pytest.fixture
def sample_resume() -> UserResume:
    return UserResume(
        personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com"),
        summary="Experienced backend engineer with 5 years in Python.",
        experience=[
            Role(
                company="Acme Corp",
                title="Software Engineer",
                start="Jan 2020",
                end="Dec 2023",
                bullets=["Built REST APIs", "Reduced latency by 30%"],
                tech=["Python", "Docker"],
            )
        ],
        skills={"Languages": ["Python", "SQL"], "Tools": ["Docker", "Git"]},
    )


@pytest.fixture
def sample_jd() -> JobDescription:
    return JobDescription(
        company="TechCorp",
        role_title="Senior Software Engineer",
        seniority="Senior",
        must_have_skills=["Python", "Kubernetes"],
        nice_to_have_skills=["Rust"],
        keywords=["distributed", "microservices", "Python"],
    )


@pytest.fixture
def sample_gap_analysis() -> GapAnalysis:
    return GapAnalysis(
        matched_skills=["Python", "Docker"],
        missing_skills=["Kubernetes"],
        open_questions=[],
        tailoring_ideas=[],
    )


class TestGraphRouting:
    """Test routing logic without running the full graph."""

    def test_route_input_text(self):
        from resume_agent.graph import _route_input

        state = {"input_type": "text", "raw_input": "Engineer role..."}
        assert _route_input(state) == "extract_jd"

    def test_route_input_url(self):
        from resume_agent.graph import _route_input

        state = {"input_type": "url", "raw_input": "https://example.com/job"}
        assert _route_input(state) == "scrape_url"

    def test_route_after_scrape_error(self):
        from langgraph.graph import END

        from resume_agent.graph import _route_after_scrape

        state = {"scrape_error": "HTTP 404: Not Found"}
        assert _route_after_scrape(state) == END

    def test_route_after_scrape_success(self):
        from resume_agent.graph import _route_after_scrape

        state = {"scraped_text": "Job description content..."}
        assert _route_after_scrape(state) == "extract_jd"

    def test_route_after_gaps_with_questions(self, sample_gap_analysis):
        from resume_agent.graph import _route_after_gaps
        from resume_agent.schemas import Question

        gap = sample_gap_analysis.model_copy(
            update={"open_questions": [Question(id="q1", prompt="Do you have K8s experience?", why_asking="JD requires it")]}
        )
        state = {"gap_analysis": gap}
        assert _route_after_gaps(state) == "hitl_ask_missing"

    def test_route_after_gaps_no_questions(self, sample_gap_analysis):
        from resume_agent.graph import _route_after_gaps

        state = {"gap_analysis": sample_gap_analysis}
        assert _route_after_gaps(state) == "present_suggestions"

    def test_route_after_latex_validation_ok(self):
        from resume_agent.graph import _route_after_latex_validation

        state = {"latex_errors": [], "generator_retries": 0}
        assert _route_after_latex_validation(state) == "compile_pdf"

    def test_route_after_latex_validation_fail_with_budget(self):
        from resume_agent.graph import _route_after_latex_validation

        state = {"latex_errors": ["Unmatched brace"], "generator_retries": 1}
        assert _route_after_latex_validation(state) == "generate_latex"

    def test_route_after_latex_validation_fail_budget_exhausted(self):
        from resume_agent.graph import _route_after_latex_validation

        # Default max is 3; retries=3 means budget exhausted
        state = {"latex_errors": ["Unmatched brace"], "generator_retries": 3}
        assert _route_after_latex_validation(state) == "terminal_failure"

    def test_route_after_validation_passed(self):
        from resume_agent.graph import _route_after_validation

        state = {"validation_passed": True, "generator_retries": 1}
        assert _route_after_validation(state) == "save_output"

    def test_route_after_validation_failed_with_budget(self):
        from resume_agent.graph import _route_after_validation

        state = {"validation_passed": False, "generator_retries": 1}
        assert _route_after_validation(state) == "generate_latex"

    def test_route_after_render_error_with_budget(self):
        from resume_agent.graph import _route_after_render

        state = {"pdf_errors": ["render failed"], "generator_retries": 1}
        assert _route_after_render(state) == "generate_latex"

    def test_route_after_render_error_budget_exhausted(self):
        from resume_agent.graph import _route_after_render

        state = {"pdf_errors": ["render failed"], "generator_retries": 3}
        assert _route_after_render(state) == "terminal_failure"


class TestSuggestionApplier:
    """Test that approved suggestions correctly modify the resume."""

    def test_applies_experience_suggestion(self, sample_resume):
        from resume_agent.agents.suggestion_presenter import _apply_suggestions
        from resume_agent.schemas import Suggestion

        suggestion = Suggestion(
            id="s1",
            section="experience",
            role_company="Acme Corp",
            before="Built REST APIs",
            after="Designed and deployed REST APIs serving 10K+ requests/day",
            rationale="Adds impact metric",
        )
        updated = _apply_suggestions(sample_resume, [suggestion])
        bullets = updated.experience[0].bullets
        assert "Designed and deployed REST APIs serving 10K+ requests/day" in bullets
        assert "Built REST APIs" not in bullets

    def test_applies_summary_suggestion(self, sample_resume):
        from resume_agent.agents.suggestion_presenter import _apply_suggestions
        from resume_agent.schemas import Suggestion

        suggestion = Suggestion(
            id="s2",
            section="summary",
            before="Experienced backend engineer with 5 years in Python.",
            after="Senior backend engineer with 5 years building distributed systems in Python.",
            rationale="Mirrors JD keywords",
        )
        updated = _apply_suggestions(sample_resume, [suggestion])
        assert "distributed systems" in updated.summary

    def test_skips_unapproved(self, sample_resume):
        from resume_agent.agents.suggestion_presenter import _apply_suggestions

        # No suggestions approved
        updated = _apply_suggestions(sample_resume, [])
        assert updated.experience[0].bullets == sample_resume.experience[0].bullets

    def test_node_reads_suggestions_from_gap_analysis_fallback(self, sample_resume):
        from resume_agent.agents.suggestion_presenter import suggestion_presenter_node
        from resume_agent.schemas import GapAnalysis, Suggestion

        suggestion = Suggestion(
            id="s1",
            section="experience",
            role_company="Acme Corp",
            before="Built REST APIs",
            after="Designed REST APIs for distributed services",
            rationale="Mirrors JD keywords",
        )
        state = {
            "base_resume": sample_resume,
            "gap_analysis": GapAnalysis(tailoring_ideas=[suggestion]),
            "approved_suggestion_ids": ["s1"],
        }

        result = suggestion_presenter_node(state)

        assert result["approved_suggestion_ids"] == ["s1"]
        assert "Designed REST APIs for distributed services" in result["tailored_resume"].experience[0].bullets

    def test_suggestion_node_interrupts_and_resumes(self, sample_resume):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import Command

        from resume_agent.agents.suggestion_presenter import suggestion_presenter_node
        from resume_agent.schemas import Suggestion
        from resume_agent.state import ResumeGenState

        suggestion = Suggestion(
            id="s1",
            section="experience",
            role_company="Acme Corp",
            before="Built REST APIs",
            after="Designed REST APIs for distributed services",
            rationale="Mirrors JD keywords",
        )
        builder = StateGraph(ResumeGenState)
        builder.add_node("present_suggestions", suggestion_presenter_node)
        builder.add_edge(START, "present_suggestions")
        builder.add_edge("present_suggestions", END)
        graph = builder.compile(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "suggestion-test"}}

        first = graph.invoke(
            {"base_resume": sample_resume, "suggestions": [suggestion]},
            config,
        )
        payload = first["__interrupt__"][0].value
        assert payload["kind"] == "tailoring_suggestions"

        final = graph.invoke(Command(resume={"approved_ids": ["s1"]}), config)
        assert final["approved_suggestion_ids"] == ["s1"]
        assert "Designed REST APIs for distributed services" in final["tailored_resume"].experience[0].bullets


class TestBuildGraph:
    """Smoke test: graph compiles without errors."""

    def test_build_graph_no_checkpointer(self):
        from resume_agent.graph import build_graph

        graph = build_graph(checkpointer=None)
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        from resume_agent.graph import build_graph

        graph = build_graph(checkpointer=None)
        node_names = set(graph.nodes.keys())
        expected = {
            "scrape_url", "extract_jd", "load_base_resume", "analyze_gaps",
            "hitl_ask_missing", "present_suggestions", "generate_latex",
            "validate_latex", "compile_pdf", "render_pages",
            "validate_alignment", "save_output", "terminal_failure",
        }
        assert expected.issubset(node_names)


class TestCLIImport:
    """Regression: cli.py must import cleanly (no NameError on missing imports)."""

    def test_cli_app_importable(self):
        from resume_agent.cli import app  # noqa: F401

        assert app is not None

    def test_cli_has_expected_commands(self):
        from resume_agent.cli import app

        # Typer stores commands in registered_commands (names are inferred at
        # runtime so some may be None); just verify ≥4 are wired up.
        assert len(app.registered_commands) >= 4

    def test_graph_config_sets_thread_and_recursion_limit(self):
        from resume_agent.cli import _graph_config
        from resume_agent.config import ResumeAgentSettings, RetriesConfig

        settings = ResumeAgentSettings(retries=RetriesConfig(generator_max=5))
        config = _graph_config("thread-123", settings)

        assert config["configurable"]["thread_id"] == "thread-123"
        assert config["recursion_limit"] >= 50


class TestPDFValidatorNode:
    """Vision validator must distinguish PASS from API-error (not silently PASS)."""

    def test_fails_when_no_rendered_images(self):
        from resume_agent.agents.pdf_validator import pdf_validator_node

        result = pdf_validator_node({"page_images": []})

        assert result["validation_passed"] is False
        assert "unverified" in result["validation_feedback"]

    def test_pass_on_clean_page(self, tmp_path):
        from unittest.mock import MagicMock, patch

        fake_llm = MagicMock()
        fake_llm.invoke.return_value = MagicMock(content="PASS")

        # Create a dummy PNG so open() succeeds
        img = tmp_path / "page1.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

        with patch("resume_agent.agents.pdf_validator.ResumeAgentSettings") as mock_cfg, \
             patch("resume_agent.agents.pdf_validator.get_chat_model", return_value=fake_llm):
            mock_cfg.load.return_value = MagicMock()
            result = __import__(
                "resume_agent.agents.pdf_validator", fromlist=["pdf_validator_node"]
            ).pdf_validator_node({"page_images": [str(img)]})

        assert result["validation_passed"] is True
        assert result["validation_feedback"] is None

    def test_fails_on_vision_api_error(self, tmp_path):
        """An API exception must NOT silently become a PASS."""
        from unittest.mock import MagicMock, patch

        fake_llm = MagicMock()
        fake_llm.invoke.side_effect = RuntimeError("API timeout")

        img = tmp_path / "page1.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

        with patch("resume_agent.agents.pdf_validator.ResumeAgentSettings") as mock_cfg, \
             patch("resume_agent.agents.pdf_validator.get_chat_model", return_value=fake_llm):
            mock_cfg.load.return_value = MagicMock()
            result = __import__(
                "resume_agent.agents.pdf_validator", fromlist=["pdf_validator_node"]
            ).pdf_validator_node({"page_images": [str(img)]})

        assert result["validation_passed"] is False
        assert "unavailable" in result["validation_feedback"].lower()

    def test_fails_on_real_layout_issue(self, tmp_path):
        """Feedback from the model must propagate as validation_passed=False."""
        from unittest.mock import MagicMock, patch

        fake_llm = MagicMock()
        fake_llm.invoke.return_value = MagicMock(
            content='Page 1 | Section "Experience" | Issue: text overflow | Fix: reduce font size'
        )

        img = tmp_path / "page1.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

        with patch("resume_agent.agents.pdf_validator.ResumeAgentSettings") as mock_cfg, \
             patch("resume_agent.agents.pdf_validator.get_chat_model", return_value=fake_llm):
            mock_cfg.load.return_value = MagicMock()
            result = __import__(
                "resume_agent.agents.pdf_validator", fromlist=["pdf_validator_node"]
            ).pdf_validator_node({"page_images": [str(img)]})

        assert result["validation_passed"] is False
        assert "overflow" in result["validation_feedback"]


class TestRenderPagesNode:
    """PDF rendering must not silently pass when page images cannot be produced."""

    def test_render_failure_marks_validation_failed(self):
        from unittest.mock import patch

        from resume_agent.agents.render_pages import render_pages_node

        with patch("resume_agent.agents.render_pages.pdf_to_images", side_effect=RuntimeError("Poppler missing")):
            result = render_pages_node({"pdf_path": "/tmp/resume.pdf"})

        assert result["validation_passed"] is False
        assert result["page_images"] == []
        assert "PDF render failed" in result["pdf_errors"][0]


class TestHITLInterruptNode:
    """Missing-info HITL should use LangGraph's dynamic interrupt contract."""

    def test_hitl_node_interrupts_and_resumes_empty_answers(self, sample_resume):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import Command

        from resume_agent.agents.hitl import hitl_node
        from resume_agent.schemas import GapAnalysis, Question
        from resume_agent.state import ResumeGenState

        gap = GapAnalysis(
            open_questions=[
                Question(id="q1", prompt="Have you used Kubernetes?", why_asking="JD requires it")
            ]
        )
        builder = StateGraph(ResumeGenState)
        builder.add_node("hitl_ask_missing", hitl_node)
        builder.add_edge(START, "hitl_ask_missing")
        builder.add_edge("hitl_ask_missing", END)
        graph = builder.compile(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "hitl-test"}}

        first = graph.invoke({"base_resume": sample_resume, "gap_analysis": gap}, config)
        payload = first["__interrupt__"][0].value
        assert payload["kind"] == "missing_questions"

        final = graph.invoke(Command(resume={"answers": {"q1": ""}}), config)
        assert final["tailored_resume"] == sample_resume

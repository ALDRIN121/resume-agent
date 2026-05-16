"""
LangGraph StateGraph assembly for the resume generation pipeline.

Graph topology:
  START → route_input
    → scrape_url (url path) → extract_jd
    → extract_jd (text path)
    → load_base_resume
    → analyze_gaps
    → hitl_ask_missing (interrupt_before, skipped if no questions)
    → present_suggestions (interrupt_before)
    → generate_latex ←──────────────────────────────────────────────────┐
    → resume_lint    ──hard-fail──► generate_latex (retry, capped)      │
    → validate_latex ──fail──► generate_latex (retry)                   │
    → compile_pdf    ──fail──► generate_latex (retry)                   │
    → render_pages                                                       │
    → validate_alignment ──fail──► generate_latex (retry)               │
    → hr_review (optional, flag-gated) ──fail──► generate_latex (retry) │
    → save_output (on pass) / terminal_failure (budget gone) ───────────┘
    → END
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from .agents.base_resume_loader import load_base_resume_node
from .agents.gap_analyzer import gap_analyzer_node
from .agents.hitl import hitl_node
from .agents.hr_review import hr_review_node
from .agents.jd_extractor import jd_extractor_node
from .agents.jd_scraper import jd_scraper_node
from .agents.latex_validator import latex_validator_node
from .agents.output_saver import output_saver_node
from .agents.pdf_compiler import pdf_compiler_node
from .agents.pdf_validator import pdf_validator_node
from .agents.render_pages import render_pages_node
from .agents.resume_generator import resume_generator_node
from .agents.suggestion_presenter import suggestion_presenter_node
from .agents.terminal_failure import terminal_failure_node
from .state import ResumeGenState
from .tools.resume_lint import lint_resume, normalize_resume_text

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from .config import ResumeAgentSettings

# ── HITL node name constants (used by CLI to detect interrupt points) ──────────
HITL_MISSING_NODE = "hitl_ask_missing"
HITL_SUGGESTIONS_NODE = "present_suggestions"
HITL_NODES: frozenset[str] = frozenset([HITL_MISSING_NODE, HITL_SUGGESTIONS_NODE])


# ── Inline node: resume lint ──────────────────────────────────────────────────

def resume_lint_node(state: ResumeGenState) -> dict:
    """
    Run deterministic lint checks on the tailored/base resume.

    Results are stored in lint_feedback. Hard failures cause the router to send
    the graph back to generate_latex (up to the retry budget).
    """
    from .ui.panels import print_agent_step, print_info, print_warning

    resume = state.get("tailored_resume") or state.get("base_resume")
    if resume is None:
        return {"lint_feedback": None}

    print_agent_step("Resume Lint", "Running deterministic quality checks…")
    result = lint_resume(normalize_resume_text(resume))

    if not result.issues:
        print_info("Lint: all checks passed.")
        return {"lint_feedback": None}

    for issue in result.issues:
        (print_warning if issue.severity == "fail" else print_info)(
            f"  [{issue.severity.upper()}] {issue.code}: {issue.message}"
        )

    feedback = result.fail_feedback_text() if result.has_failures else None
    if feedback:
        return {
            "lint_feedback": feedback,
            "lint_retries": state.get("lint_retries", 0) + 1,
        }
    return {"lint_feedback": None}


# ── Static routing functions (no settings dependency) ─────────────────────────

def _route_input(state: ResumeGenState) -> str:
    """Decide whether to scrape a URL or go straight to extraction."""
    return "scrape_url" if state.get("input_type") == "url" else "extract_jd"


def _route_after_scrape(state: ResumeGenState) -> str:
    """Stop on scrape error; otherwise continue to extraction."""
    return END if state.get("scrape_error") else "extract_jd"


def _route_after_gaps(state: ResumeGenState) -> str:
    """Route to HITL if there are open questions, otherwise skip to suggestions."""
    gap = state.get("gap_analysis")
    if gap and gap.open_questions:
        return HITL_MISSING_NODE
    return HITL_SUGGESTIONS_NODE


def _route_after_latex_validation(state: ResumeGenState, *, max_retries: int = 3) -> str:
    """Retry generation on syntax errors (if budget allows), else compile."""
    if state.get("latex_errors"):
        if state.get("generator_retries", 0) >= max_retries:
            return "terminal_failure"
        return "generate_latex"
    return "compile_pdf"


def _route_after_compile(state: ResumeGenState, *, max_retries: int = 3) -> str:
    """Retry generation on compile errors (if budget allows), else render pages."""
    if state.get("pdf_errors"):
        if state.get("generator_retries", 0) >= max_retries:
            return "terminal_failure"
        return "generate_latex"
    return "render_pages"


def _route_after_render(state: ResumeGenState, *, max_retries: int = 3) -> str:
    """Retry generation on render errors (if budget allows), else validate images."""
    if state.get("pdf_errors"):
        if state.get("generator_retries", 0) >= max_retries:
            return "terminal_failure"
        return "generate_latex"
    return "validate_alignment"


_LINT_MAX_RETRIES = 2  # lint retries are capped independently of generator_retries


def _route_after_lint(state: ResumeGenState) -> str:
    """Retry generation on hard lint failures (cap: 2), then fall through to validate_latex."""
    if state.get("lint_feedback"):
        if state.get("lint_retries", 0) >= _LINT_MAX_RETRIES:
            return "validate_latex"  # budget exhausted; proceed anyway
        return "generate_latex"
    return "validate_latex"


def _route_after_validation(state: ResumeGenState, *, max_retries: int = 3) -> str:
    """Retry generation on alignment issues (if budget allows), else hr_review or save."""
    if not state.get("validation_passed", False):
        if state.get("generator_retries", 0) >= max_retries:
            return "terminal_failure"
        return "generate_latex"
    return "hr_review"


def _route_after_hr_review(state: ResumeGenState, *, max_retries: int = 3) -> str:
    """Retry generation if HR review set validation_passed=False, else save."""
    if not state.get("validation_passed", True):
        if state.get("generator_retries", 0) >= max_retries:
            return "save_output"  # HR review failure is advisory, not terminal
        return "generate_latex"
    return "save_output"


# ── Graph builder ──────────────────────────────────────────────────────────────

def build_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    settings: ResumeAgentSettings | None = None,
):
    """
    Assemble and compile the resume generation StateGraph.

    Pass a checkpointer (SqliteSaver) to enable HITL interrupt/resume.
    Pass settings to avoid repeated disk reads during routing — if omitted,
    settings are loaded once here rather than on every edge evaluation.

    HITL nodes use LangGraph dynamic interrupts; the CLI resumes with
    Command(resume=...) after collecting user input.
    """
    if settings is None:
        from .config import ResumeAgentSettings
        settings = ResumeAgentSettings.load()

    max_retries = settings.retries.generator_max

    enable_hr_review = settings.features.enable_hr_review

    # Routing closures capture max_retries once — no disk reads during execution
    def _retry_after_latex(state: ResumeGenState) -> str:
        return _route_after_latex_validation(state, max_retries=max_retries)

    def _retry_after_lint(state: ResumeGenState) -> str:
        return _route_after_lint(state)

    def _retry_after_compile(state: ResumeGenState) -> str:
        return _route_after_compile(state, max_retries=max_retries)

    def _retry_after_render(state: ResumeGenState) -> str:
        return _route_after_render(state, max_retries=max_retries)

    def _retry_after_validation(state: ResumeGenState) -> str:
        # When HR review is disabled, go directly to save_output
        result = _route_after_validation(state, max_retries=max_retries)
        if result == "hr_review" and not enable_hr_review:
            return "save_output"
        return result

    def _retry_after_hr_review(state: ResumeGenState) -> str:
        return _route_after_hr_review(state, max_retries=max_retries)

    builder = StateGraph(ResumeGenState)
    llm_retry_policy = RetryPolicy(max_attempts=2)

    # ── Nodes ──────────────────────────────────────────────────────────────────
    builder.add_node("scrape_url", partial(jd_scraper_node, settings=settings))
    builder.add_node(
        "extract_jd",
        partial(jd_extractor_node, settings=settings),
        retry_policy=llm_retry_policy,
    )
    builder.add_node("load_base_resume", load_base_resume_node)
    builder.add_node(
        "analyze_gaps",
        partial(gap_analyzer_node, settings=settings),
        retry_policy=llm_retry_policy,
    )
    builder.add_node(
        HITL_MISSING_NODE,
        partial(hitl_node, settings=settings),
        retry_policy=llm_retry_policy,
    )
    builder.add_node(HITL_SUGGESTIONS_NODE, suggestion_presenter_node)
    builder.add_node(
        "generate_latex",
        partial(resume_generator_node, settings=settings),
        retry_policy=llm_retry_policy,
    )
    builder.add_node("resume_lint", resume_lint_node)
    builder.add_node("validate_latex", latex_validator_node)
    builder.add_node("compile_pdf", partial(pdf_compiler_node, settings=settings))
    builder.add_node("render_pages", render_pages_node)
    builder.add_node(
        "validate_alignment",
        partial(pdf_validator_node, settings=settings),
        retry_policy=llm_retry_policy,
    )
    builder.add_node(
        "hr_review",
        partial(hr_review_node, settings=settings),
        retry_policy=llm_retry_policy,
    )
    builder.add_node("save_output", partial(output_saver_node, settings=settings))
    builder.add_node("terminal_failure", partial(terminal_failure_node, settings=settings))

    # ── Edges ──────────────────────────────────────────────────────────────────
    builder.add_conditional_edges(START, _route_input, ["scrape_url", "extract_jd"])
    builder.add_conditional_edges("scrape_url", _route_after_scrape, ["extract_jd", END])

    builder.add_edge("extract_jd", "load_base_resume")
    builder.add_edge("load_base_resume", "analyze_gaps")

    builder.add_conditional_edges(
        "analyze_gaps", _route_after_gaps, [HITL_MISSING_NODE, HITL_SUGGESTIONS_NODE]
    )
    builder.add_edge(HITL_MISSING_NODE, HITL_SUGGESTIONS_NODE)
    builder.add_edge(HITL_SUGGESTIONS_NODE, "generate_latex")
    builder.add_edge("generate_latex", "resume_lint")

    builder.add_conditional_edges(
        "resume_lint",
        _retry_after_lint,
        ["generate_latex", "validate_latex"],
    )
    builder.add_conditional_edges(
        "validate_latex",
        _retry_after_latex,
        ["generate_latex", "compile_pdf", "terminal_failure"],
    )
    builder.add_conditional_edges(
        "compile_pdf",
        _retry_after_compile,
        ["generate_latex", "render_pages", "terminal_failure"],
    )
    builder.add_conditional_edges(
        "render_pages",
        _retry_after_render,
        ["generate_latex", "validate_alignment", "terminal_failure"],
    )
    builder.add_conditional_edges(
        "validate_alignment",
        _retry_after_validation,
        ["generate_latex", "hr_review", "save_output", "terminal_failure"],
    )
    builder.add_conditional_edges(
        "hr_review",
        _retry_after_hr_review,
        ["generate_latex", "save_output"],
    )

    builder.add_edge("save_output", END)
    builder.add_edge("terminal_failure", END)

    # ── Compile ────────────────────────────────────────────────────────────────
    return builder.compile(checkpointer=checkpointer)

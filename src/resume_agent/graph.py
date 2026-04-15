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
    → generate_latex ←─────────────────────────────────────────┐
    → validate_latex  ──fail──► (above, retry)                 │
    → compile_pdf     ──fail──► (above, retry)                 │
    → render_pages                                             │
    → validate_alignment ──fail──► (above, retry)             │
    → save_output (on pass) / terminal_failure (budget gone) ──┘
    → END
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from .agents.base_resume_loader import load_base_resume_node
from .agents.gap_analyzer import gap_analyzer_node
from .agents.hitl import hitl_node
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

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from .config import ResumeAgentSettings

# ── HITL node name constants (used by CLI to detect interrupt points) ──────────
HITL_MISSING_NODE = "hitl_ask_missing"
HITL_SUGGESTIONS_NODE = "present_suggestions"
HITL_NODES: frozenset[str] = frozenset([HITL_MISSING_NODE, HITL_SUGGESTIONS_NODE])


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


def _route_after_validation(state: ResumeGenState, *, max_retries: int = 3) -> str:
    """Retry generation on alignment issues (if budget allows), else save output."""
    if not state.get("validation_passed", False):
        if state.get("generator_retries", 0) >= max_retries:
            return "terminal_failure"
        return "generate_latex"
    return "save_output"


# ── Graph builder ──────────────────────────────────────────────────────────────

def build_graph(
    checkpointer: "BaseCheckpointSaver | None" = None,
    settings: "ResumeAgentSettings | None" = None,
):
    """
    Assemble and compile the resume generation StateGraph.

    Pass a checkpointer (SqliteSaver) to enable HITL interrupt/resume.
    Pass settings to avoid repeated disk reads during routing — if omitted,
    settings are loaded once here rather than on every edge evaluation.

    The graph uses interrupt_before on HITL nodes so the CLI can inject
    user responses via graph.update_state() before those nodes run.
    """
    if settings is None:
        from .config import ResumeAgentSettings
        settings = ResumeAgentSettings.load()

    max_retries = settings.retries.generator_max

    # Routing closures capture max_retries once — no disk reads during execution
    def _retry_after_latex(state: ResumeGenState) -> str:
        return _route_after_latex_validation(state, max_retries=max_retries)

    def _retry_after_compile(state: ResumeGenState) -> str:
        return _route_after_compile(state, max_retries=max_retries)

    def _retry_after_validation(state: ResumeGenState) -> str:
        return _route_after_validation(state, max_retries=max_retries)

    builder = StateGraph(ResumeGenState)

    # ── Nodes ──────────────────────────────────────────────────────────────────
    builder.add_node("scrape_url", jd_scraper_node)
    builder.add_node("extract_jd", jd_extractor_node)
    builder.add_node("load_base_resume", load_base_resume_node)
    builder.add_node("analyze_gaps", gap_analyzer_node)
    builder.add_node(HITL_MISSING_NODE, hitl_node)
    builder.add_node(HITL_SUGGESTIONS_NODE, suggestion_presenter_node)
    builder.add_node("generate_latex", resume_generator_node)
    builder.add_node("validate_latex", latex_validator_node)
    builder.add_node("compile_pdf", pdf_compiler_node)
    builder.add_node("render_pages", render_pages_node)
    builder.add_node("validate_alignment", pdf_validator_node)
    builder.add_node("save_output", output_saver_node)
    builder.add_node("terminal_failure", terminal_failure_node)

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
    builder.add_edge("generate_latex", "validate_latex")

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
    builder.add_edge("render_pages", "validate_alignment")
    builder.add_conditional_edges(
        "validate_alignment",
        _retry_after_validation,
        ["generate_latex", "save_output", "terminal_failure"],
    )

    builder.add_edge("save_output", END)
    builder.add_edge("terminal_failure", END)

    # ── Compile ────────────────────────────────────────────────────────────────
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=list(HITL_NODES),
    )

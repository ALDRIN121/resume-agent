"""LangGraph state definition for the resume generation pipeline."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from .schemas import GapAnalysis, JobDescription, Suggestion, UserResume

# Increment when ResumeGenState adds/removes required fields.
# cli.py `resume` command rejects checkpoints with a different version.
STATE_SCHEMA_VERSION = 1


class ResumeGenState(TypedDict, total=False):
    # ── Schema guard ───────────────────────────────────────────────────────────
    schema_version: int  # always set to STATE_SCHEMA_VERSION at graph entry
    # ── Input ──────────────────────────────────────────────────────────────────
    input_type: Literal["text", "url"]
    raw_input: str

    # ── Scraping ───────────────────────────────────────────────────────────────
    scraped_text: str | None
    scrape_error: str | None

    # ── Structured Job Description ─────────────────────────────────────────────
    jd: JobDescription | None

    # ── Base resume (source of truth) ──────────────────────────────────────────
    base_resume: UserResume | None

    # ── Cross-check / gap analysis ─────────────────────────────────────────────
    gap_analysis: GapAnalysis | None

    # HITL: question_id -> user answer
    hitl_answers: dict[str, str]

    # Suggestions from gap analyzer
    suggestions: list[Suggestion]

    # IDs of suggestions the user approved
    approved_suggestion_ids: list[str]

    # Resume after applying approved tailoring
    tailored_resume: UserResume | None

    # ── LaTeX / PDF generation ─────────────────────────────────────────────────
    latex_source: str | None
    latex_errors: list[str]
    pdf_path: str | None
    pdf_errors: list[str]

    # Filesystem paths to rendered page PNGs
    page_images: list[str]

    # ── Validation ─────────────────────────────────────────────────────────────
    validation_feedback: str | None
    validation_passed: bool

    # Feedback from the deterministic resume lint pass (Phase 4)
    lint_feedback: str | None

    # ── Retry budgets ──────────────────────────────────────────────────────────
    generator_retries: int  # shared across latex→compile→validate loops
    lint_retries: int       # dedicated counter for lint-driven regenerations (cap: 2)

    # ── Final output ───────────────────────────────────────────────────────────
    final_pdf_path: str | None

    # ── Message history (for LLM context) ─────────────────────────────────────
    messages: Annotated[list[BaseMessage], add_messages]

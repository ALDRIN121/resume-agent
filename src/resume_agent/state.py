"""LangGraph state definition for the resume generation pipeline."""

from __future__ import annotations

from typing import Annotated, Literal, Optional, TypedDict

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
    scraped_text: Optional[str]
    scrape_error: Optional[str]

    # ── Structured Job Description ─────────────────────────────────────────────
    jd: Optional[JobDescription]

    # ── Base resume (source of truth) ──────────────────────────────────────────
    base_resume: Optional[UserResume]

    # ── Cross-check / gap analysis ─────────────────────────────────────────────
    gap_analysis: Optional[GapAnalysis]

    # HITL: question_id -> user answer
    hitl_answers: dict[str, str]

    # Suggestions from gap analyzer
    suggestions: list[Suggestion]

    # IDs of suggestions the user approved
    approved_suggestion_ids: list[str]

    # Resume after applying approved tailoring
    tailored_resume: Optional[UserResume]

    # ── LaTeX / PDF generation ─────────────────────────────────────────────────
    latex_source: Optional[str]
    latex_errors: list[str]
    pdf_path: Optional[str]
    pdf_errors: list[str]

    # Filesystem paths to rendered page PNGs
    page_images: list[str]

    # ── Validation ─────────────────────────────────────────────────────────────
    validation_feedback: Optional[str]
    validation_passed: bool

    # ── Retry budget (shared across latex→compile→validate loops) ─────────────
    generator_retries: int

    # ── Final output ───────────────────────────────────────────────────────────
    final_pdf_path: Optional[str]

    # ── Message history (for LLM context) ─────────────────────────────────────
    messages: Annotated[list[BaseMessage], add_messages]

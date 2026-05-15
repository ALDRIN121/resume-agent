"""
Human-in-the-Loop node — processes user answers about missing experience.

Flow (using interrupt_before in graph compilation):
  1. Graph pauses BEFORE this node runs
  2. CLI reads state, prompts user, calls graph.update_state(hitl_answers=...)
  3. Graph resumes; this node enriches tailored_resume with answers
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from ..config import MAX_RESUME_JSON_CHARS, ResumeAgentSettings
from ..llm import get_chat_model
from ..schemas import GapAnalysis, UserResume
from ..state import ResumeGenState
from ..ui.panels import print_info

_SYSTEM = """\
You are a resume editor. The user has answered questions about experience not documented in their resume.
Incorporate their answers into an enriched version of the resume.

Rules:
- Add ONLY what the user explicitly confirmed they have done
- Do not embellish or add detail beyond what the user stated
- If the user said "no" or left an answer blank, do NOT add that item
- Weave new details into the appropriate experience bullets or summary
- Return the complete updated resume JSON
"""

_HUMAN_TEMPLATE = """\
ORIGINAL RESUME:
{resume_json}

USER ANSWERS TO QUESTIONS:
{qa_pairs}

Return the updated UserResume JSON incorporating confirmed answers.
"""


def hitl_node(
    state: ResumeGenState, *, settings: ResumeAgentSettings | None = None
) -> dict:
    """
    Process HITL answers and enrich the base resume.
    The node owns the LangGraph interrupt/resume contract: it surfaces the
    questions to the caller and receives the answers via Command(resume=...).
    """
    base_resume = state.get("base_resume")
    gap_analysis = _coerce_gap_analysis(state.get("gap_analysis"))

    if not gap_analysis or not gap_analysis.open_questions:
        return {"tailored_resume": base_resume}

    raw_answers = interrupt(
        {
            "kind": "missing_questions",
            "questions": [q.model_dump() for q in gap_analysis.open_questions],
        }
    )
    hitl_answers = _coerce_answers(raw_answers)

    if not hitl_answers or not any(v.strip() for v in hitl_answers.values()):
        return {"tailored_resume": base_resume}

    settings = settings or ResumeAgentSettings.load()
    llm = get_chat_model(settings, task="structured")
    structured_llm = llm.with_structured_output(UserResume)

    # Build Q&A context
    qa_pairs = []
    for q in gap_analysis.open_questions:
        answer = hitl_answers.get(q.id, "").strip()
        if answer:
            qa_pairs.append(f"Q: {q.prompt}\nA: {answer}")

    if not qa_pairs:
        return {"tailored_resume": base_resume}

    print_info("Incorporating your answers into the resume…")

    messages = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(
            content=_HUMAN_TEMPLATE.format(
                resume_json=json.dumps(base_resume.model_dump(), indent=2)[:MAX_RESUME_JSON_CHARS],
                qa_pairs="\n\n".join(qa_pairs),
            )
        ),
    ]

    enriched: UserResume = structured_llm.invoke(messages)
    return {"hitl_answers": hitl_answers, "tailored_resume": enriched}


def _coerce_gap_analysis(raw) -> GapAnalysis | None:
    """Handle checkpoint round-trips that may turn Pydantic models into dicts."""
    if raw is None:
        return None
    if isinstance(raw, GapAnalysis):
        return raw
    if isinstance(raw, dict):
        try:
            return GapAnalysis.model_validate(raw)
        except Exception:
            return None
    return raw if hasattr(raw, "open_questions") else None


def _coerce_answers(raw) -> dict[str, str]:
    """Normalize a resume payload into question_id -> answer."""
    if not isinstance(raw, dict):
        return {}
    answers = raw.get("answers", raw)
    if not isinstance(answers, dict):
        return {}
    return {str(k): str(v).strip() for k, v in answers.items()}

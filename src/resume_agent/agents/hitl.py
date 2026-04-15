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

from ..config import MAX_RESUME_JSON_CHARS, ResumeAgentSettings
from ..llm import get_chat_model
from ..schemas import UserResume
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


def hitl_node(state: ResumeGenState) -> dict:
    """
    Process HITL answers and enrich the base resume.
    The interrupt_before pause happens BEFORE this node runs;
    by the time it runs, hitl_answers is already populated in state.
    """
    hitl_answers = state.get("hitl_answers", {})
    base_resume = state.get("base_resume")

    if not hitl_answers or not any(v.strip() for v in hitl_answers.values()):
        # No answers provided — pass base resume through unchanged
        return {"tailored_resume": base_resume}

    gap_analysis = state.get("gap_analysis")
    if not gap_analysis:
        return {"tailored_resume": base_resume}

    settings = ResumeAgentSettings.load()
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
    return {"tailored_resume": enriched}

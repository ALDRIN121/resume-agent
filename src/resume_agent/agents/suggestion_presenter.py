"""
Suggestion Presenter node — applies user-approved tailoring suggestions.

Flow (using interrupt_before):
  1. Graph pauses BEFORE this node runs
  2. CLI reads state.gap_analysis.tailoring_ideas, presents UI, collects approved IDs
  3. CLI calls graph.update_state(approved_suggestion_ids=[...])
  4. Graph resumes; this node applies approved suggestions to produce tailored_resume
"""

from __future__ import annotations

import copy

from langgraph.types import interrupt

from ..schemas import GapAnalysis, Suggestion, UserResume
from ..state import ResumeGenState
from ..ui.panels import print_info


def _coerce_suggestions(raw) -> list[Suggestion]:
    """Convert a mix of Suggestion objects and checkpoint-deserialized dicts."""
    if not raw:
        return []
    out = []
    for s in raw:
        if isinstance(s, Suggestion):
            out.append(s)
        elif isinstance(s, dict):
            try:
                out.append(Suggestion.model_validate(s))
            except Exception:
                pass
    return out


def read_suggestions_from_state(state: dict) -> list[Suggestion]:
    """
    Extract suggestions from the canonical state shape, tolerating checkpoint
    deserialization of Pydantic models into dicts.
    """
    result = _coerce_suggestions(state.get("suggestions"))
    if result:
        return result

    gap = state.get("gap_analysis")
    if gap is None:
        return []
    if isinstance(gap, GapAnalysis):
        return _coerce_suggestions(gap.tailoring_ideas)
    if isinstance(gap, dict):
        try:
            parsed = GapAnalysis.model_validate(gap)
            return _coerce_suggestions(parsed.tailoring_ideas)
        except Exception:
            return _coerce_suggestions(gap.get("tailoring_ideas", []))
    if hasattr(gap, "tailoring_ideas"):
        return _coerce_suggestions(gap.tailoring_ideas)
    return []


def suggestion_presenter_node(state: ResumeGenState) -> dict:
    """
    Apply approved suggestions to the resume.
    The node owns the LangGraph interrupt/resume contract for review.
    """
    approved_ids = state.get("approved_suggestion_ids")
    suggestions = read_suggestions_from_state(state)

    # Use tailored_resume if HITL already enriched it, else base_resume
    source_resume: UserResume = state.get("tailored_resume") or state.get("base_resume")

    if not suggestions:
        print_info("No suggestions available to apply.")
        return {"tailored_resume": source_resume}

    if approved_ids is None:
        approved_ids = _coerce_approved_ids(
            interrupt(
                {
                    "kind": "tailoring_suggestions",
                    "suggestions": [s.model_dump() for s in suggestions],
                }
            )
        )

    if not approved_ids:
        print_info(f"No suggestions approved — skipping {len(suggestions)} available suggestion(s).")
        return {"approved_suggestion_ids": [], "tailored_resume": source_resume}

    approved_set = set(approved_ids)
    approved = [s for s in suggestions if s.id in approved_set]

    if not approved:
        return {"approved_suggestion_ids": approved_ids, "tailored_resume": source_resume}

    print_info(f"Applying {len(approved)} approved suggestion(s)…")
    updated = _apply_suggestions(source_resume, approved)
    return {"approved_suggestion_ids": approved_ids, "tailored_resume": updated}


def _coerce_approved_ids(raw) -> list[str]:
    """Normalize a resume payload into a list of approved suggestion IDs."""
    if isinstance(raw, dict):
        raw = raw.get("approved_ids", raw.get("approved_suggestion_ids", []))
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _apply_suggestions(resume: UserResume, suggestions: list[Suggestion]) -> UserResume:
    """
    Apply text-replacement suggestions to the resume.
    Replaces 'before' text with 'after' in the relevant section.
    """
    # Deep copy to avoid mutating the original
    data = copy.deepcopy(resume.model_dump())

    for sug in suggestions:
        section = sug.section

        if section == "summary":
            if data.get("summary") and sug.before in (data["summary"] or ""):
                data["summary"] = data["summary"].replace(sug.before, sug.after, 1)

        elif section == "experience":
            for role in data.get("experience", []):
                # Match to specific role if role_company is set
                if sug.role_company and sug.role_company not in role.get("company", ""):
                    continue
                bullets = role.get("bullets", [])
                role["bullets"] = [
                    b.replace(sug.before, sug.after, 1) if b == sug.before else b
                    for b in bullets
                ]

        elif section == "projects":
            for project in data.get("projects", []):
                bullets = project.get("bullets", [])
                project["bullets"] = [
                    b.replace(sug.before, sug.after, 1) if b == sug.before else b
                    for b in bullets
                ]

        elif section == "skills":
            # Replace skill names in the skills dict
            for category, items in data.get("skills", {}).items():
                data["skills"][category] = [
                    sug.after if item == sug.before else item for item in items
                ]

    return UserResume.model_validate(data)

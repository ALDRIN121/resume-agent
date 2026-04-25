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

from ..schemas import Suggestion, UserResume
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


def suggestion_presenter_node(state: ResumeGenState) -> dict:
    """
    Apply approved suggestions to the resume.
    The interrupt_before pause happens BEFORE this node runs.
    """
    approved_ids = state.get("approved_suggestion_ids", [])
    suggestions: list[Suggestion] = _coerce_suggestions(state.get("suggestions", []))

    # Use tailored_resume if HITL already enriched it, else base_resume
    source_resume: UserResume = state.get("tailored_resume") or state.get("base_resume")

    if not suggestions:
        print_info("No suggestions available to apply.")
        return {"tailored_resume": source_resume}

    if not approved_ids:
        print_info(f"No suggestions approved — skipping {len(suggestions)} available suggestion(s).")
        return {"tailored_resume": source_resume}

    approved_set = set(approved_ids)
    approved = [s for s in suggestions if s.id in approved_set]

    if not approved:
        return {"tailored_resume": source_resume}

    print_info(f"Applying {len(approved)} approved suggestion(s)…")
    updated = _apply_suggestions(source_resume, approved)
    return {"tailored_resume": updated}


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

"""
Gap Analyzer agent node — compares the user's resume with the job description.

Produces:
- matched_skills: skills present in both resume and JD
- missing_skills: JD must-haves not found in resume
- open_questions: things that MIGHT be in user's background but aren't documented
- tailoring_ideas: bullet-point rewrite suggestions (no fabrication)
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import MAX_RESUME_JSON_CHARS, ResumeAgentSettings
from ..llm import get_chat_model
from ..schemas import GapAnalysis
from ..state import ResumeGenState
from ..ui.panels import print_agent_step, print_info

_SYSTEM = """\
You are a senior technical recruiter and resume coach.

Given a user's resume and a target job description, perform a gap analysis.

STRICT RULES:
1. matched_skills: list skills present in BOTH the resume AND the JD (exact or very close match)
2. missing_skills: JD "must-have" skills NOT found in the resume (be honest)
3. open_questions: Ask the user about JD requirements that MIGHT be in their experience
   but aren't explicitly documented. Examples: leadership, on-call, certain project types.
   Include a "why_asking" explanation for each question. Max 5 questions.
   Assign IDs like "q1", "q2", etc.
4. tailoring_ideas: Suggest REWRITES of existing bullets to better mirror JD keywords.
   NEVER suggest adding new experience that isn't already in the resume.
   Keep "before" as the exact original text, "after" as a polished version.
   Assign IDs like "s1", "s2", etc. Max 8 suggestions.
   "rationale" should be 1 short sentence (max 10 words).
   "section" must be one of: experience | summary | skills | projects
"""

_HUMAN_TEMPLATE = """\
USER RESUME:
{resume_json}

JOB DESCRIPTION:
Company: {company}
Role: {role_title} ({seniority})
Must-have skills: {must_have}
Nice-to-have skills: {nice_to_have}
Responsibilities:
{responsibilities}
Keywords: {keywords}
"""


def gap_analyzer_node(state: ResumeGenState) -> dict:
    """Analyze gaps between base resume and target JD."""
    settings = ResumeAgentSettings.load()
    llm = get_chat_model(settings, task="structured")
    structured_llm = llm.with_structured_output(GapAnalysis)

    resume = state["base_resume"]
    jd = state["jd"]

    print_agent_step("Gap Analyzer", f"Thinking: comparing your profile to {jd.role_title} at {jd.company}…")

    # Build a concise JSON representation of the resume for the prompt
    resume_summary = {
        "summary": resume.summary,
        "skills": resume.skills,
        "experience": [
            {
                "company": r.company,
                "title": r.title,
                "bullets": r.bullets,
                "tech": r.tech,
            }
            for r in resume.experience
        ],
        "projects": [
            {"name": p.name, "bullets": p.bullets, "tech": p.tech}
            for p in resume.projects
        ],
    }

    human_content = _HUMAN_TEMPLATE.format(
        resume_json=json.dumps(resume_summary, indent=2)[:MAX_RESUME_JSON_CHARS],
        company=jd.company,
        role_title=jd.role_title,
        seniority=jd.seniority or "Not specified",
        must_have=", ".join(jd.must_have_skills) or "Not specified",
        nice_to_have=", ".join(jd.nice_to_have_skills) or "None",
        responsibilities="\n".join(f"- {r}" for r in jd.responsibilities[:15]),
        keywords=", ".join(jd.keywords[:20]),
    )

    messages = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=human_content),
    ]

    gap: GapAnalysis = structured_llm.invoke(messages)

    print_info(
        f"Gap analysis: {len(gap.matched_skills)} matched, "
        f"{len(gap.missing_skills)} missing, "
        f"{len(gap.open_questions)} questions, "
        f"{len(gap.tailoring_ideas)} suggestions"
    )

    return {
        "gap_analysis": gap,
        "suggestions": gap.tailoring_ideas,
    }

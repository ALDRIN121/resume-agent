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
from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import ResumeAgentSettings
from ..llm import get_chat_model
from ..schemas import ContentSnapshot, GapAnalysis, JobDescription
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
5. CREDIBILITY GUARD:
   For each existing bullet, if the role's seniority level and the claimed outcome
   are mismatched (e.g. a junior/associate title claiming sole ownership of a
   business-revenue outcome like "drove $5M revenue"), surface a suggestion to
   soften attribution — for example:
     "drove $5M in revenue" → "contributed to $5M in revenue growth"
   Mark such suggestions with section="experience" and include "soften attribution"
   in the rationale. This preserves honesty without deleting accomplishments.
6. LOCATION AND WORK MODE:
   Compare the job's location, work mode, and stated geographic restrictions with
   the candidate's explicit work_preferences. Raise an open question for a stated
   conflict or an important unclear restriction; do not count this as a missing skill.
   Empty preferences mean unspecified, not willingness to work anywhere.
   Never infer relocation, commuting ability, work authorization, or worldwide remote
   eligibility. Never suggest changing the candidate's current location to the job's.
"""

_HUMAN_TEMPLATE = """\
USER RESUME:
{resume_json}

JOB DESCRIPTION:
Company: {company}
Role: {role_title} ({seniority})
Job location: {location}
Work mode: {work_mode}
Posting's full work policy: {remote_policy}
Must-have skills: {must_have}
Nice-to-have skills: {nice_to_have}
Responsibilities:
{responsibilities}
Keywords: {keywords}
"""


def gap_analyzer_node(
    state: ResumeGenState, *, settings: ResumeAgentSettings | None = None
) -> dict:
    """Analyze gaps between base resume and target JD."""
    settings = settings or ResumeAgentSettings.load()
    llm = get_chat_model(settings, task="structured")
    structured_llm = llm.with_structured_output(GapAnalysis)

    resume = state["base_resume"]
    jd = state["jd"]

    print_agent_step("Gap Analyzer", f"Thinking: comparing your profile to {jd.role_title} at {jd.company}…")

    # Build a concise JSON representation of the resume for the prompt
    resume_summary = {
        "current_location": resume.personal.location,
        "work_preferences": resume.work_preferences.model_dump(),
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
        resume_json=json.dumps(resume_summary, indent=2),
        company=jd.company,
        role_title=jd.role_title,
        seniority=jd.seniority or "Not specified",
        location=jd.location or "Not specified",
        work_mode=jd.work_mode or jd.remote_policy or "Not specified",
        remote_policy=jd.remote_policy or "Not specified",
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


def generate_proposals_v2(
    snapshot: ContentSnapshot, jd: JobDescription | dict, model: Callable[[str], object],
) -> ContentSnapshot:
    """Call an injected boundary once with full fixed inputs, then validate output.

    ``model(prompt: str)`` returns a list of EditProposal dictionaries/models or
    exactly ``{'proposals': [...]}``. This helper owns no retries or settings.
    """
    from ..content_review import validate_proposals
    from ..contracts import canonical_json, content_hash
    from ..schemas import EditProposal

    snapshot = ContentSnapshot.model_validate(snapshot.model_dump())
    jd_data = jd.model_dump(mode='json') if hasattr(jd, 'model_dump') else jd
    source_index = {}

    def index_values(value, path=''):
        if path:
            source_index[path] = content_hash(value)
        if isinstance(value, dict):
            for key, child in value.items():
                index_values(child, path + '/' + key.replace('~', '~0').replace('/', '~1'))
        elif isinstance(value, list):
            for i, child in enumerate(value):
                index_values(child, f'{path}/{i}')

    index_values(snapshot.profile)
    prompt = (
        'Propose explicit resume edits AFTER considering the complete fixed profile, JD, '
        'and user evidence below. Return only EditProposal objects; never return a rewritten '
        'profile. Use source-index JSON pointers and exact before_hash values. Only summary, '
        'experience/projects bullets, project descriptions and existing individual skills may '
        'be replaced/omitted; append targets must be existing bullet/skill lists. Identity, '
        'employer, title, dates, education and certifications are immutable. New facts require '
        'explicit answer/user_text references; the JD is never candidate evidence. Preserve '
        'source wording for anything not proposed. Profile references use source_revision as '
        'input_hash; answer/user_text references use canonical JSON SHA-256 of their exact '
        'string, with answer_id naming the fixed input. Quotes use Unicode character offsets.\n'
        'EDIT_PROPOSAL_SCHEMA:\n' + canonical_json(EditProposal.model_json_schema()) +
        '\nFIXED_INPUTS:\n' + canonical_json({
            'profile': snapshot.profile, 'source_revision': snapshot.source_revision,
            'jd': jd_data, 'answers': snapshot.answers, 'user_text': snapshot.user_text,
            'before_hash_by_pointer': source_index,
            'answer_hashes': {key: content_hash(value) for key, value in snapshot.answers.items()},
            'user_text_hashes': {key: content_hash(value) for key, value in snapshot.user_text.items()},
        })
    )
    raw = model(prompt)
    if isinstance(raw, dict):
        if set(raw) != {'proposals'}:
            raise ValueError('model response must contain only proposals')
        raw = raw['proposals']
    if not isinstance(raw, list):
        raise ValueError('model proposals must be a list')
    proposals = [EditProposal.model_validate(p.model_dump() if isinstance(p, EditProposal) else p) for p in raw]
    result = ContentSnapshot.model_validate({**snapshot.model_dump(), 'proposals': proposals})
    validate_proposals(result)
    return result.model_copy(deep=True)

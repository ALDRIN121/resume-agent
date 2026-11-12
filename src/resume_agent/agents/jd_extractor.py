"""JD Extractor agent node — converts raw text into a structured JobDescription."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import MAX_JD_TEXT_CHARS, ResumeAgentSettings
from ..llm import get_chat_model
from ..model_tasks import invoke_bounded
from ..schemas import JobDescription
from ..state import ResumeGenState
from ..ui.panels import print_agent_step, print_info, print_warning

_SYSTEM = """\
You are a precise job description parser. Extract structured information from the provided job posting text.

Rules:
- Extract ONLY information explicitly stated in the text — do NOT invent or infer
- Preserve exact skill names and technologies as written (e.g., "React.js" not "React")
- Split responsibilities into individual bullet items
- If a field is not mentioned, omit it or use an empty list
- Separate "must have" from "nice to have" / "preferred" skills based on the language used
- Capture the job location and remote_policy explicitly, including country restrictions, hybrid attendance, or time-zone requirements. Remote does not imply worldwide eligibility.

You MUST respond with a single valid JSON object and nothing else — no markdown, no prose, no code fences.
Required fields: "company" (string), "role_title" (string).
Optional fields: "seniority", "location", "work_mode" (Remote, Hybrid, or On-site), "remote_policy" (full stated location/time-zone/attendance restrictions), "must_have_skills" (list), \
"nice_to_have_skills" (list), "responsibilities" (list), "keywords" (list).
"""

_HUMAN_TEMPLATE = """\
Parse the following job posting and extract structured information.

Job Posting:
{text}
"""


def jd_extractor_node(
    state: ResumeGenState, *, settings: ResumeAgentSettings | None = None
) -> dict:
    """Extract structured JobDescription from scraped or user-provided text."""
    # Reject unsupported source before settings/model setup or any external call.
    text = state.get("scraped_text") or state.get("raw_input", "")
    if len(text) > MAX_JD_TEXT_CHARS:
        raise ValueError("JD text exceeds the supported limit of 48,000 characters")
    settings = settings or ResumeAgentSettings.load()
    llm = get_chat_model(settings, task="structured")
    structured_llm = llm.with_structured_output(JobDescription)

    if len(text) < 100:
        print_warning(f"JD text is very short ({len(text)} chars) — extraction may be incomplete.")

    print_agent_step("JD Extractor", "Analyzing job requirements & extracting key skills…")

    messages = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=_HUMAN_TEMPLATE.format(text=text)),
    ]
    jd = invoke_bounded(structured_llm.invoke, messages, JobDescription)
    jd = _with_job_context(jd, state, text)
    print_info(f"Extracted JD: {jd.company} — {jd.role_title}")
    return {"jd": jd}


def _with_job_context(jd: JobDescription, state: ResumeGenState, text: str) -> JobDescription:
    updates = {"raw_text": text}
    if location := (state.get("job_location") or "").strip():
        updates["location"] = location
    if work_mode := state.get("work_mode"):
        updates["work_mode"] = work_mode
    return jd.model_copy(update=updates)

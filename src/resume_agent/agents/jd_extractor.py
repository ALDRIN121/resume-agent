"""JD Extractor agent node — converts raw text into a structured JobDescription."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import MAX_JD_STORAGE_CHARS, MAX_JD_TEXT_CHARS, ResumeAgentSettings
from ..llm import get_chat_model
from ..schemas import JobDescription
from ..state import ResumeGenState
from ..ui.panels import print_info, print_warning

_SYSTEM = """\
You are a precise job description parser. Extract structured information from the provided job posting text.

Rules:
- Extract ONLY information explicitly stated in the text — do NOT invent or infer
- Preserve exact skill names and technologies as written (e.g., "React.js" not "React")
- Split responsibilities into individual bullet items
- If a field is not mentioned, omit it or use an empty list
- Separate "must have" from "nice to have" / "preferred" skills based on the language used

You MUST respond with a single valid JSON object and nothing else — no markdown, no prose, no code fences.
Required fields: "company" (string), "role_title" (string).
Optional fields: "seniority", "location", "remote_policy", "must_have_skills" (list), \
"nice_to_have_skills" (list), "responsibilities" (list), "keywords" (list).
"""

_HUMAN_TEMPLATE = """\
Parse the following job posting and extract structured information.

Job Posting:
{text}
"""


def jd_extractor_node(state: ResumeGenState) -> dict:
    """Extract structured JobDescription from scraped or user-provided text."""
    settings = ResumeAgentSettings.load()
    llm = get_chat_model(settings, task="structured")
    structured_llm = llm.with_structured_output(JobDescription)

    # Use scraped text if available, otherwise the raw text input
    text = state.get("scraped_text") or state.get("raw_input", "")

    if len(text) < 100:
        print_warning(f"JD text is very short ({len(text)} chars) — extraction may be incomplete.")

    print_info("Extracting job description structure…")

    messages = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=_HUMAN_TEMPLATE.format(text=text[:MAX_JD_TEXT_CHARS])),
    ]

    jd: JobDescription = structured_llm.invoke(messages)

    # Attach raw text for later reference
    jd = jd.model_copy(update={"raw_text": text[:MAX_JD_STORAGE_CHARS]})

    print_info(f"Extracted JD: {jd.company} — {jd.role_title}")
    return {"jd": jd}

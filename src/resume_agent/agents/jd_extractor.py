"""JD Extractor agent node — converts raw text into a structured JobDescription."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.utils.json import parse_json_markdown

from ..config import MAX_JD_STORAGE_CHARS, MAX_JD_TEXT_CHARS, ResumeAgentSettings
from ..llm import get_chat_model
from ..schemas import JobDescription
from ..state import ResumeGenState
from ..ui.panels import print_info, print_warning

_MAX_RETRIES = 3

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

_RETRY_SUFFIX = """

IMPORTANT: Your previous response could not be parsed as valid JSON.
Respond with ONLY a raw JSON object. Do not include any text before or after it.
Example format:
{{"company": "Acme Corp", "role_title": "Software Engineer", "responsibilities": [], "must_have_skills": [], "nice_to_have_skills": []}}
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

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        if attempt > 1:
            print_warning(f"JD extraction attempt {attempt}/{_MAX_RETRIES} (retrying after parse error)…")

        system_content = _SYSTEM + (_RETRY_SUFFIX if attempt > 1 else "")
        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=_HUMAN_TEMPLATE.format(text=text[:MAX_JD_TEXT_CHARS])),
        ]

        try:
            jd: JobDescription = structured_llm.invoke(messages)
            jd = jd.model_copy(update={"raw_text": text[:MAX_JD_STORAGE_CHARS]})
            print_info(f"Extracted JD: {jd.company} — {jd.role_title}")
            return {"jd": jd}
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            # Try a plain LLM call as fallback — the model may have returned
            # markdown or prose that we can still salvage with a JSON extractor.
            try:
                plain_llm = get_chat_model(settings, task="structured")
                raw_msg = plain_llm.invoke(messages)
                content = raw_msg.content if hasattr(raw_msg, "content") else str(raw_msg)
                raw_text = content if isinstance(content, str) else str(content)
                data = parse_json_markdown(raw_text)
                jd = JobDescription.model_validate(data)
                jd = jd.model_copy(update={"raw_text": text[:MAX_JD_STORAGE_CHARS]})
                print_info(f"Extracted JD (fallback): {jd.company} — {jd.role_title}")
                return {"jd": jd}
            except Exception:  # noqa: BLE001
                pass  # will retry or raise below

    raise RuntimeError(
        f"Failed to extract job description after {_MAX_RETRIES} attempts. "
        f"Last error: {last_exc}\n\n"
        "Tip: Try switching to a stronger model (e.g. anthropic or openai) with:\n"
        "  resume-agent config set provider anthropic"
    ) from last_exc

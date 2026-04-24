"""
Base Resume Loader — loads the user's source-of-truth resume.

On first run (via `resume-generator init`), parses .tex or .pdf into a YAML cache.
On subsequent `generate` runs, loads the YAML directly (no LLM cost).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from langchain_core.messages import HumanMessage, SystemMessage

from ..config import BASE_RESUME_FILE, MAX_RESUME_PARSE_CHARS, ResumeAgentSettings
from ..llm import get_chat_model
from ..schemas import UserResume
from ..state import ResumeGenState
from ..ui.panels import print_info

_SYSTEM = """\
You are a resume parser. Extract structured information from the provided resume text.

Rules:
- Extract ALL information present — do not discard anything
- Preserve exact wording of bullet points and skills
- If a section is absent, use an empty list
- For skills, group them into logical categories (e.g., Languages, Frameworks, Tools, Cloud)

Required output field names (use these exactly):
- Top level: personal, summary, experience, projects, education, skills, certifications, publications
- personal fields: full_name, email, phone, location, linkedin (handle only), github (handle only), website
- experience items: company, title, start (e.g. "Jan 2022"), end (e.g. "Dec 2023"; omit or null if current), location, bullets (list of strings), tech (list of strings)
- projects items: name, description, tech (list), bullets (list), url
- education items: institution, degree, field, graduation (e.g. "May 2020"), gpa, notes (list)
- skills: object mapping category name to list of skill strings
"""

_HUMAN_TEMPLATE = """\
Parse the following resume and extract all structured information.

Resume Text:
{text}
"""


def load_base_resume_node(_state: ResumeGenState) -> dict:
    """Load base resume from YAML cache (fast path used during `generate`)."""
    if not BASE_RESUME_FILE.exists():
        # This should have been caught at CLI startup, but handle gracefully
        return {
            "scrape_error": (
                f"Base resume not found at {BASE_RESUME_FILE}. "
                "Run: resume-generator init --source <your_resume.tex|.pdf>"
            )
        }

    print_info("Loading base resume…")
    raw = BASE_RESUME_FILE.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    resume = UserResume.model_validate(data)
    print_info(f"Loaded resume for: {resume.personal.full_name}")
    return {"base_resume": resume}


def parse_and_save_resume(source_path: Path) -> UserResume:
    """
    One-time parsing: read .tex or .pdf → LLM → UserResume → save YAML.
    Called by `resume-generator init`, not from the graph.

    Shows three distinct progress phases so the user can see what's happening
    during the (potentially long) LLM call.
    """
    from ..ui.progress import phase_spinner

    settings = ResumeAgentSettings.load()
    suffix = source_path.suffix.lower()

    # ── Step 1: Extract text ───────────────────────────────────────────────────
    with phase_spinner(f"Extracting text from {source_path.name}"):
        if suffix == ".tex":
            text = source_path.read_text(encoding="utf-8")
        elif suffix == ".pdf":
            text = _extract_pdf_text(source_path)
        else:
            raise ValueError(f"Unsupported format: {suffix}. Use .tex or .pdf")

        if not text.strip():
            raise ValueError("Could not extract any text from the provided file.")

    print_info(f"Extracted {len(text):,} characters from resume.")

    # ── Step 2: LLM parsing (slow — can take 1–2 min) ─────────────────────────
    llm = get_chat_model(settings, task="structured")
    structured_llm = llm.with_structured_output(UserResume)

    messages = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=_HUMAN_TEMPLATE.format(text=text[:MAX_RESUME_PARSE_CHARS])),
    ]

    with phase_spinner("Parsing with AI  (may take 1–2 min)"):
        resume: UserResume = structured_llm.invoke(messages)

    # ── Step 3: Save YAML ─────────────────────────────────────────────────────
    with phase_spinner("Saving parsed resume"):
        BASE_RESUME_FILE.parent.mkdir(parents=True, exist_ok=True)
        BASE_RESUME_FILE.write_text(
            yaml.dump(resume.model_dump(), default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    return resume


def _extract_pdf_text(path: Path) -> str:
    """Extract plain text from a PDF using pypdf."""
    try:
        from pypdf import PdfReader  # lazy import
    except ImportError as e:
        raise RuntimeError("pypdf not installed. Run: uv sync") from e

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)

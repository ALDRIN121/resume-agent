"""
Resume Generator agent node — produces LaTeX source from tailored resume data.

On first run: renders Jinja2 template + LLM polishing pass.
On retry:     sends previous LaTeX + error context to LLM for self-correction.
"""

from __future__ import annotations

import re

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from langchain_core.messages import HumanMessage, SystemMessage

from ..config import TEMPLATES_DIR, ResumeAgentSettings
from ..llm import get_chat_model
from ..state import ResumeGenState
from ..ui.panels import print_agent_step, print_info, print_warning

# Commands that must never appear in LLM-generated LaTeX.
# \write18 / \immediate\write18 enable shell execution.
# \input / \include can read arbitrary local files.
# \openout writes to the filesystem.
# \catcode changes allow constructing any of the above indirectly.
# NOTE: no \b word-boundary — \openout15 has no boundary between 't' and '1'.
_DANGEROUS_LATEX = re.compile(
    r"\\(write18|immediate\\write|openout|catcode)",
    re.IGNORECASE,
)
# \input and \include are legitimate in authored docs but dangerous in LLM output.
# Strip only when followed by a brace group pointing outside the document root.
_INPUT_INCLUDE = re.compile(r"\\(input|include)\s*\{", re.IGNORECASE)

_POLISH_SYSTEM = """\
You are a professional resume writer and LaTeX expert.

You will receive a LaTeX resume draft. Your job is to:
1. Polish ALL bullet points in the experience and projects sections:
   - Start with strong action verbs (Led, Built, Reduced, Shipped, Optimized, etc.)
   - Add quantification where it naturally fits the existing text (do NOT fabricate numbers)
   - Mirror key terms from the "Job Keywords" list
2. Keep bullets concise — 1-2 lines maximum
3. Ensure the LaTeX compiles cleanly — fix any obvious syntax issues

CRITICAL: Do NOT add any experience, skills, or accomplishments not already present.
Return ONLY the complete, valid LaTeX source. No explanation text before or after.
"""

_POLISH_HUMAN = """\
Job Keywords to mirror: {keywords}

LaTeX Draft:
```latex
{latex_draft}
```
"""

_FIX_SYSTEM = """\
You are a LaTeX expert and resume formatter.
Fix the provided LaTeX source to resolve the listed errors.
Return ONLY the corrected LaTeX source. No explanation.
"""

_FIX_HUMAN = """\
The LaTeX source has the following errors that must be fixed:

ERRORS:
{errors}

ADDITIONAL FEEDBACK:
{feedback}

LATEX SOURCE:
```latex
{latex_source}
```
"""


def resume_generator_node(state: ResumeGenState) -> dict:
    """Generate (or regenerate/fix) LaTeX source from tailored resume."""
    settings = ResumeAgentSettings.load()
    retries = state.get("generator_retries", 0)

    # Use tailored_resume if available, else fall back to base_resume
    resume = state.get("tailored_resume") or state.get("base_resume")
    jd = state.get("jd")

    # ── Retry path: self-correct existing LaTeX ────────────────────────────────
    existing_latex = state.get("latex_source", "")
    latex_errors = state.get("latex_errors", [])
    pdf_errors = state.get("pdf_errors", [])
    validation_feedback = state.get("validation_feedback", "")

    if retries > 0 and existing_latex:
        print_agent_step("Resume Writer", f"Self-correcting LaTeX (attempt {retries + 1})…")
        all_errors = latex_errors + pdf_errors
        latex_source = _fix_latex(
            existing_latex,
            errors=all_errors,
            feedback=validation_feedback or "",
            settings=settings,
        )
    else:
        print_agent_step("Resume Writer", "Writing your tailored LaTeX resume…")
        # ── First run: render template then polish ─────────────────────────────
        draft = _render_template(resume)
        keywords = ", ".join(jd.keywords[:20]) if jd else ""
        latex_source = _polish_latex(draft, keywords=keywords, settings=settings)

    # Increment retry counter; clear previous errors so the validator runs fresh
    return {
        "latex_source": latex_source,
        "latex_errors": [],
        "pdf_errors": [],
        "validation_feedback": None,
        "generator_retries": retries + 1,
    }


def _render_template(resume) -> str:
    """Render the Jinja2 LaTeX template with resume data."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        # Use (( )) delimiters to avoid conflicts with LaTeX braces
        variable_start_string="((",
        variable_end_string="))",
        block_start_string="(%",
        block_end_string="%)",
        comment_start_string="(#",
        comment_end_string="#)",
        undefined=StrictUndefined,
        autoescape=False,
    )
    env.filters["le"] = _latex_escape    # (( value | le )) — for LaTeX text content
    env.filters["href"] = _latex_href_escape  # (( url | href )) — for \href{...} URL argument

    template = env.get_template("default.tex.jinja")
    data = resume.model_dump() if resume else {}
    return template.render(**data)


def _polish_latex(draft: str, *, keywords: str, settings: ResumeAgentSettings) -> str:
    """Run an LLM pass to polish bullet points and fix minor syntax issues."""
    llm = get_chat_model(settings, task="default", temperature=0.2)
    messages = [
        SystemMessage(content=_POLISH_SYSTEM),
        HumanMessage(content=_POLISH_HUMAN.format(keywords=keywords, latex_draft=draft)),
    ]
    result = llm.invoke(messages)
    return _sanitize_llm_latex(_strip_code_fences(str(result.content)))


def _fix_latex(
    source: str, *, errors: list[str], feedback: str, settings: ResumeAgentSettings
) -> str:
    """Ask the LLM to fix specific errors in the LaTeX source."""
    llm = get_chat_model(settings, task="default", temperature=0.1)
    errors_text = "\n".join(f"- {e}" for e in errors) if errors else "No specific error messages."
    messages = [
        SystemMessage(content=_FIX_SYSTEM),
        HumanMessage(
            content=_FIX_HUMAN.format(
                errors=errors_text,
                feedback=feedback or "None",
                latex_source=source,
            )
        ),
    ]
    result = llm.invoke(messages)
    return _sanitize_llm_latex(_strip_code_fences(str(result.content)))


def _sanitize_llm_latex(latex: str) -> str:
    """
    Remove dangerous LaTeX commands from LLM-generated output.

    Called after every LLM polish/fix pass. Strips commands that could execute
    shell code or read arbitrary files, which a prompt-injected JD could induce
    the LLM to emit.

    This is defence-in-depth: Tectonic disables shell-escape by default, but
    \\input{} of local files still leaks filesystem content into the PDF.
    """
    no_comments = re.sub(r"%.*$", "", latex, flags=re.MULTILINE)

    if _DANGEROUS_LATEX.search(no_comments):
        print_warning("LLM output contained dangerous LaTeX commands — stripped.")
        latex = _DANGEROUS_LATEX.sub("", latex)

    if _INPUT_INCLUDE.search(no_comments):
        print_warning("LLM output contained \\input/\\include — stripped.")
        # Remove entire \input{...} and \include{...} invocations
        latex = re.sub(r"\\(input|include)\s*\{[^}]*\}", "", latex, flags=re.IGNORECASE)

    return latex


def _strip_code_fences(text: str) -> str:
    """Remove ```latex ... ``` or ``` ... ``` wrappers if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first and last fence lines
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _latex_href_escape(value: str) -> str:
    """
    Escape characters that break LaTeX \\href{URL}{text} URL argument.

    In the URL argument of \\href, `{` closes a group prematurely, `}` ends the
    argument, and `\\` starts a command. Percent-signs are handled by hyperref
    and must NOT be escaped. Strip the three dangerous chars.
    """
    return re.sub(r"[{}\\]", "", str(value))


# Character-by-character map ensures replacement strings (e.g. \textbackslash{})
# are never themselves re-processed by a later substitution pass.
_LATEX_ESCAPE_MAP: dict[str, str] = {
    "\\": r"\textbackslash{}",
    "&":  r"\&",
    "%":  r"\%",
    "$":  r"\$",
    "#":  r"\#",
    "_":  r"\_",
    "{":  r"\{",
    "}":  r"\}",
    "~":  r"\textasciitilde{}",
    "^":  r"\^{}",
    "<":  r"\textless{}",
    ">":  r"\textgreater{}",
}


def _latex_escape(value: str) -> str:
    """Escape special LaTeX characters in user data."""
    return "".join(_LATEX_ESCAPE_MAP.get(c, c) for c in str(value))

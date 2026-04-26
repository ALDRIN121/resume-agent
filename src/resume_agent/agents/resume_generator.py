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

_TEMPLATE_RULES = """\
TEMPLATE STRUCTURE — these rules are NON-NEGOTIABLE:
- The preamble defines custom macros: \\resumeItem, \\resumeSubheading,
  \\resumeProjectHeading, \\resumeSubItem, \\resumeSubHeadingListStart,
  \\resumeSubHeadingListEnd, \\resumeItemListStart, \\resumeItemListEnd.
  Keep ALL of them defined exactly as written; do NOT inline-expand them.
- Every \\resumeItemListStart MUST be paired with a \\resumeItemListEnd.
  Every \\resumeSubHeadingListStart MUST be paired with a \\resumeSubHeadingListEnd.
  Never leave one of a pair unmatched.
- Bullets inside an experience/project block use \\resumeItem{...}; do NOT
  replace them with raw \\item — \\resumeItem already supplies the \\item.
- A \\resumeSubheading takes EXACTLY 4 brace-groups: {company}{location}{title}{dates}.
  A \\resumeProjectHeading takes EXACTLY 2 brace-groups.
  Never reduce or expand the argument count.
- Do NOT add \\usepackage{fontawesome5} or any fontawesome package — this
  template intentionally avoids icons for cross-platform font compatibility.
- Do NOT change \\documentclass, \\geometry, \\addtolength margin commands,
  \\titleformat, or the section ruling. Layout density is part of the design.
- Keep $|$ as the header separator (math-mode pipe). Do not replace with \\textbar
  or fontawesome icons.
- Escape user text properly: &, %, #, _, $ must be backslash-escaped when they
  appear in narrative text. Never escape them inside \\href{URL}{...}'s URL part.
"""

_POLISH_SYSTEM_HEAD = """\
You are a professional resume writer and LaTeX expert working with a custom
resume template that uses macros for alignment.

Your job, on the LaTeX draft you receive:
1. Polish ALL bullet points (the bodies of \\resumeItem{...}) in experience and projects:
   - Start with strong action verbs (Led, Built, Reduced, Shipped, Optimized, etc.)
   - Add quantification where it naturally fits the existing text (do NOT fabricate numbers)
   - Mirror key terms from the "Job Keywords" list when truthful
   - Keep each bullet to 1-2 lines maximum
2. Tighten the Professional Summary similarly — concise, keyword-aware, no invented facts.
3. Fix any obvious LaTeX syntax issues you encounter while polishing.

"""

_POLISH_SYSTEM_TAIL = """

CRITICAL: Do NOT add any experience, skills, dates, or accomplishments not
already present. Do NOT delete bullets or roles. Do NOT reorder sections.

Return ONLY the complete, valid LaTeX source. No explanation text before or after.
No markdown fences.
"""

_POLISH_SYSTEM = _POLISH_SYSTEM_HEAD + _TEMPLATE_RULES + _POLISH_SYSTEM_TAIL

_POLISH_HUMAN = """\
Job Keywords to mirror (only when truthful): {keywords}

LaTeX Draft:
```latex
{latex_draft}
```
"""

_FIX_SYSTEM_HEAD = """\
You are a LaTeX expert repairing a resume that failed validation.

Fix ONLY the listed errors. Preserve everything else byte-for-byte where possible.

"""

_FIX_SYSTEM_TAIL = """

Common pitfalls to avoid while fixing:
- Do NOT "simplify" by deleting \\resumeItemListStart / \\resumeItemListEnd
  pairs to silence balance warnings — instead, find the missing partner and add it.
- Do NOT collapse \\resumeSubheading into plain text to dodge alignment errors —
  fix the brace count instead.
- If a bullet contains an unescaped &, %, #, _, or $, escape it with a backslash;
  do NOT delete the bullet.
- If layout feedback says "text overflow" or "page break orphan", trim verbose
  bullets, never silently drop content blocks.

Return ONLY the corrected LaTeX source. No explanation. No markdown fences.
"""

_FIX_SYSTEM = _FIX_SYSTEM_HEAD + _TEMPLATE_RULES + _FIX_SYSTEM_TAIL

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
        if all_errors or validation_feedback:
            print_warning("Issues to address:")
            for err in all_errors:
                print_info(f"  • {err}")
            if validation_feedback:
                for line in validation_feedback.split("\n"):
                    if line.strip():
                        print_info(f"  • {line}")
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
    polished = _sanitize_llm_latex(_strip_code_fences(str(result.content)))
    # If the LLM degraded the structure (e.g. dropped macro defs), fall back to the draft.
    return _guard_structure(polished, fallback=draft)


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
    fixed = _sanitize_llm_latex(_strip_code_fences(str(result.content)))
    # If the LLM degraded structure while "fixing", keep the prior source instead.
    return _guard_structure(fixed, fallback=source)


# Sentinel substrings that the resume template MUST contain. If the LLM removes
# any of these, its output is unsafe to use — we fall back to the prior version.
_REQUIRED_TOKENS: tuple[str, ...] = (
    r"\documentclass",
    r"\begin{document}",
    r"\end{document}",
)


def _guard_structure(candidate: str, *, fallback: str) -> str:
    """
    If `candidate` is missing required structural tokens or has badly unbalanced
    custom-command list pairs, return `fallback` instead.

    This is defence-in-depth against the LLM "simplifying" away the template.
    The LaTeX validator will still flag issues in `fallback` and trigger the
    fix loop — but at least we don't ship gutted output.
    """
    if not candidate.strip():
        print_warning("LLM returned empty output — keeping previous LaTeX.")
        return fallback

    missing = [t for t in _REQUIRED_TOKENS if t not in candidate]
    if missing:
        print_warning(
            f"LLM output missing required tokens ({', '.join(missing)}) — "
            "keeping previous LaTeX."
        )
        return fallback

    item_start = candidate.count(r"\resumeItemListStart")
    item_end = candidate.count(r"\resumeItemListEnd")
    head_start = candidate.count(r"\resumeSubHeadingListStart")
    head_end = candidate.count(r"\resumeSubHeadingListEnd")
    if item_start != item_end or head_start != head_end:
        print_warning(
            "LLM output has unbalanced resume list macros "
            f"(item {item_start}/{item_end}, heading {head_start}/{head_end}) — "
            "keeping previous LaTeX."
        )
        return fallback

    return candidate


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

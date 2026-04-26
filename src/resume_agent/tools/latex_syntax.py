"""
LaTeX syntax validation — multi-pass check:
  1. Required-document structure (\\documentclass, \\begin{document}, \\end{document})
  2. In-process brace/environment balance
  3. Custom resume-macro list-pair balance
  4. Macro-definition presence for any \\resume* macros used in the body
  5. chktex external tool (optional, only if installed)
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class LatexCheckResult:
    ok: bool
    errors: list[str]


# Custom commands defined by the resume template. If the body uses one of these
# but the preamble doesn't define it, the LaTeX compile will explode with
# "Undefined control sequence". Catching it here lets the fix loop see a precise
# error message instead of a Tectonic stack trace.
_RESUME_MACROS: tuple[str, ...] = (
    "resumeItem",
    "resumeSubItem",
    "resumeSubheading",
    "resumeProjectHeading",
    "resumeItemListStart",
    "resumeItemListEnd",
    "resumeSubHeadingListStart",
    "resumeSubHeadingListEnd",
)


def check_latex(source: str) -> LatexCheckResult:
    """
    Check LaTeX source for syntax errors.

    Returns LatexCheckResult with ok=True if no errors found.
    """
    errors: list[str] = []

    errors.extend(_check_required_structure(source))
    errors.extend(_check_balance(source))
    errors.extend(_check_resume_macro_pairs(source))
    errors.extend(_check_resume_macro_defs(source))
    errors.extend(_run_chktex(source))

    return LatexCheckResult(ok=len(errors) == 0, errors=errors)


def _check_required_structure(source: str) -> list[str]:
    """Document must have \\documentclass and a \\begin{document}/\\end{document} pair."""
    errors: list[str] = []
    if r"\documentclass" not in source:
        errors.append("Missing \\documentclass declaration")
    if r"\begin{document}" not in source:
        errors.append("Missing \\begin{document}")
    if r"\end{document}" not in source:
        errors.append("Missing \\end{document}")
    return errors


def _check_resume_macro_pairs(source: str) -> list[str]:
    """
    Verify the custom \\resume*ListStart / \\resume*ListEnd pairs balance.

    These are macros in the preamble, so the generic \\begin/\\end check does
    not see them — they expand into itemize at compile time. If unbalanced,
    Tectonic will fail with a confusing "extra \\end{itemize}" later.
    """
    errors: list[str] = []
    pairs = (
        ("resumeItemListStart", "resumeItemListEnd"),
        ("resumeSubHeadingListStart", "resumeSubHeadingListEnd"),
    )
    for start, end in pairs:
        n_start = len(re.findall(rf"\\{start}\b", source))
        n_end = len(re.findall(rf"\\{end}\b", source))
        if n_start != n_end:
            errors.append(
                f"Unbalanced \\{start}/\\{end}: {n_start} start vs {n_end} end"
            )
    return errors


def _check_resume_macro_defs(source: str) -> list[str]:
    """
    If the body uses a \\resume* macro, the preamble must define it.

    LLM "fixes" sometimes delete macro definitions while keeping their
    invocations — that compiles to "Undefined control sequence" at every use.
    Catching it here turns a flood of compile errors into one actionable line.
    """
    errors: list[str] = []
    for macro in _RESUME_MACROS:
        used = re.search(rf"\\{macro}\b", source) is not None
        if not used:
            continue
        defined = re.search(
            rf"\\(?:newcommand|renewcommand|providecommand)\s*\*?\s*\{{?\\{macro}\b",
            source,
        ) is not None
        if not defined:
            errors.append(f"\\{macro} is used but not defined in the preamble")
    return errors


def _check_balance(source: str) -> list[str]:
    """
    Check that:
    - Curly braces { } are balanced
    - \\begin{env} / \\end{env} pairs match and are properly nested
    """
    errors: list[str] = []

    # ── Brace balance ─────────────────────────────────────────────────────────
    depth = 0
    for i, ch in enumerate(source):
        if ch == "{" and (i == 0 or source[i - 1] != "\\"):
            depth += 1
        elif ch == "}" and (i == 0 or source[i - 1] != "\\"):
            depth -= 1
        if depth < 0:
            errors.append(f"Unmatched closing brace '}}' near position {i}")
            depth = 0

    if depth != 0:
        errors.append(f"Unmatched opening brace(s): {depth} unclosed '{{' remaining")

    # ── Environment balance ────────────────────────────────────────────────────
    begin_pattern = re.compile(r"\\begin\{([^}]+)\}")
    end_pattern = re.compile(r"\\end\{([^}]+)\}")

    begins = [(m.group(1), m.start()) for m in begin_pattern.finditer(source)]
    ends = [(m.group(1), m.start()) for m in end_pattern.finditer(source)]

    # Simple stack-based check
    stack: list[str] = []
    events: list[tuple[int, str, str]] = []  # (pos, "begin"|"end", env)
    for env, pos in begins:
        events.append((pos, "begin", env))
    for env, pos in ends:
        events.append((pos, "end", env))
    events.sort()

    for _pos, kind, env in events:
        if kind == "begin":
            stack.append(env)
        else:
            if not stack:
                errors.append(f"\\end{{{env}}} has no matching \\begin")
            elif stack[-1] != env:
                errors.append(
                    f"Mismatched environments: expected \\end{{{stack[-1]}}}, "
                    f"got \\end{{{env}}}"
                )
                stack.pop()
            else:
                stack.pop()

    for env in stack:
        errors.append(f"Unclosed \\begin{{{env}}} — missing \\end{{{env}}}")

    return errors


def _run_chktex(source: str) -> list[str]:
    """Run chktex on source if installed; return parsed error messages."""
    if not shutil.which("chktex"):
        return []

    try:
        result = subprocess.run(
            ["chktex", "-q", "-n1", "-n2", "-n3", "-", ],
            input=source,
            capture_output=True,
            text=True,
            timeout=15,
        )
        # Parse chktex output: lines like "Warning N in <stdin> line M: ..."
        errors = []
        for line in result.stdout.splitlines():
            if line.startswith("Error") or line.startswith("Warning"):
                errors.append(line.strip())
        return errors[:10]  # Cap to first 10 to avoid flooding state
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

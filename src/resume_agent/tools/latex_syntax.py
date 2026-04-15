"""
LaTeX syntax validation — two-pass check:
  1. In-process brace/environment balance check (always runs)
  2. chktex external tool (optional, only if installed)
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


def check_latex(source: str) -> LatexCheckResult:
    """
    Check LaTeX source for syntax errors.

    Returns LatexCheckResult with ok=True if no errors found.
    """
    errors: list[str] = []

    # Pass 1: structural balance
    balance_errors = _check_balance(source)
    errors.extend(balance_errors)

    # Pass 2: chktex (if available)
    chktex_errors = _run_chktex(source)
    errors.extend(chktex_errors)

    return LatexCheckResult(ok=len(errors) == 0, errors=errors)


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

"""Latex Validator node — syntax-checks the generated LaTeX source."""

from __future__ import annotations

from ..state import ResumeGenState
from ..tools.latex_syntax import check_latex
from ..ui.panels import print_info, print_warning


def latex_validator_node(state: ResumeGenState) -> dict:
    """
    Run structural + chktex validation on state["latex_source"].
    Returns latex_errors if problems found; empty list on success.
    """
    latex_source = state.get("latex_source", "")

    if not latex_source:
        return {"latex_errors": ["LaTeX source is empty"]}

    print_info("Checking LaTeX syntax…")
    result = check_latex(latex_source)

    if result.ok:
        print_info("LaTeX syntax OK.")
        return {"latex_errors": []}

    print_warning(f"LaTeX syntax issues found ({len(result.errors)}):")
    for err in result.errors[:5]:
        print_warning(f"  {err}")

    return {"latex_errors": result.errors}

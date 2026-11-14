"""
Terminal Failure node — runs when the retry budget is exhausted.

Saves the last LaTeX attempt and error log to ./output/_failed/<timestamp>/
so the user can inspect and debug manually.
"""

from __future__ import annotations

import shutil
from uuid import uuid4

from ..artifacts import RunArtifacts
from ..config import ResumeAgentSettings
from ..state import ResumeGenState
from ..tools.fs import build_failed_path
from ..ui.panels import print_error


def terminal_failure_node(
    state: ResumeGenState, *, settings: ResumeAgentSettings | None = None
) -> dict:
    """Save debug artifacts and surface a clear error to the user."""
    settings = settings or ResumeAgentSettings.load()
    failed_dir = build_failed_path(settings.output_base_dir.resolve())
    # Timestamp alone can collide across concurrent failures.
    failed_dir = failed_dir / str(uuid4())
    failed_dir.mkdir()

    # Save whatever we have
    latex_source = state.get("latex_source", "")
    if latex_source:
        (failed_dir / "resume.tex").write_text(latex_source, encoding="utf-8")

    # Collect all error info
    all_errors: list[str] = []
    all_errors.extend(state.get("latex_errors", []))
    all_errors.extend(state.get("pdf_errors", []))
    if state.get("validation_feedback"):
        all_errors.append(f"Vision feedback: {state['validation_feedback']}")

    error_log = "\n".join(all_errors)
    if error_log:
        (failed_dir / "errors.txt").write_text(error_log, encoding="utf-8")

    # Copy the full Tectonic + TeX log if it exists
    if state.get("artifact_id"):
        attempt = RunArtifacts.create(state["artifact_id"]).attempt(state.get("attempt_number"))
        if attempt.log_path.exists():
            shutil.copy2(attempt.log_path, failed_dir / "tectonic_raw.log")

    print_error(
        f"Generation failed after {state.get('generator_retries', 0)} attempts.",
        hint=f"Debug artifacts saved to: {failed_dir}",
    )

    return {"final_pdf_path": None}

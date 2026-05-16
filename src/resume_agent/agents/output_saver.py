"""Output Saver node — moves the final PDF to the structured output directory."""

from __future__ import annotations

import shutil

from ..config import ResumeAgentSettings
from ..state import ResumeGenState
from ..tools.fs import build_output_path
from ..ui.panels import print_info, print_success


def output_saver_node(
    state: ResumeGenState, *, settings: ResumeAgentSettings | None = None
) -> dict:
    """
    Copy the compiled PDF to:
      <output.base_dir>/<company_slug>/<user_slug>_<company_slug>_<YYYY-MM-DD>.pdf

    Returns final_pdf_path on success.
    """
    settings = settings or ResumeAgentSettings.load()
    pdf_path = state.get("pdf_path")
    jd = state.get("jd")
    resume = state.get("tailored_resume") or state.get("base_resume")

    if not pdf_path or not jd or not resume:
        return {"final_pdf_path": None}

    base_dir = settings.output_base_dir.resolve()

    dest_path = build_output_path(
        base_dir=base_dir,
        company_name=jd.company,
        user_full_name=resume.personal.full_name,
    )

    shutil.copy2(pdf_path, str(dest_path))
    print_success(f"Resume saved → {dest_path}")
    if state.get("validation_feedback"):
        print_info("Saved with non-blocking layout advisories shown above.")
    return {"final_pdf_path": str(dest_path)}

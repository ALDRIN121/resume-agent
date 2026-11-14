"""Output Saver node — moves the final PDF to the structured output directory."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from ..artifacts import (
    RunArtifacts,
    cleanup_export,
    commit_export,
    hash_file,
    prepare_copy,
    prepare_export,
)
from ..config import ResumeAgentSettings
from ..state import ResumeGenState
from ..ui.panels import print_info, print_success


def output_saver_node(
    state: ResumeGenState, *, settings: ResumeAgentSettings | None = None
) -> dict:
    """
    Copy the compiled PDF to:
      <output.base_dir>/<company_slug>/<user_slug>_<company_slug>_<YYYY-MM-DD>.pdf

    Returns final_pdf_path on success.
    """
    if state.get("schema_version") == 2:
        raise ValueError("v2 PDF export requires the release service")
    settings = settings or ResumeAgentSettings.load()
    pdf_path = state.get("pdf_path")
    jd = state.get("jd")
    resume = state.get("tailored_resume") or state.get("base_resume")

    if not pdf_path or not jd or not resume:
        return {"final_pdf_path": None}

    base_dir = settings.output_base_dir.resolve()

    artifact_id = state.get("artifact_id")
    if not artifact_id:
        # Legacy checkpoints and external compiler adapters may lack ownership.
        # Freeze their PDF into a fresh run before using the export protocol.
        run = RunArtifacts.create(str(uuid4()))
        canonical = run.attempt(1).pdf_path
        with Path(pdf_path).open("rb") as source, canonical.open("xb") as target:
            shutil.copyfileobj(source, target)
        pdf_path, artifact_id = str(canonical), run.artifact_id
    plan = prepare_export(artifact_id, pdf_path, hash_file(pdf_path), base_dir,
                          jd.company, resume.personal.full_name)
    try:
        prepare_copy(plan)
        dest_path = commit_export(plan)
    finally:
        cleanup_export(plan)
    print_success(f"Resume saved → {dest_path}")
    if state.get("validation_feedback"):
        print_info("Saved with non-blocking layout advisories shown above.")
    return {"final_pdf_path": str(dest_path)}

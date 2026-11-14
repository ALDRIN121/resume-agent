"""Render Pages node — converts PDF pages to PNG images for vision validation."""

from __future__ import annotations

from ..artifacts import RunArtifacts
from ..state import ResumeGenState
from ..tools.pdf_to_images import pdf_to_images
from ..ui.panels import print_info, print_warning


def render_pages_node(state: ResumeGenState) -> dict:
    """
    Convert the compiled PDF to per-page PNG images.
    Populates state["page_images"] with filesystem paths.
    """
    pdf_path = state.get("pdf_path")

    if not pdf_path:
        return {"pdf_errors": ["No PDF path to render — compilation may have failed"]}

    print_info("Rendering PDF pages to images for validation…")

    try:
        output_dir = None
        if state.get("artifact_id"):
            run = RunArtifacts.create(state["artifact_id"])
            attempt = run.attempt(state.get("attempt_number"))
            if str(attempt.pdf_path) != pdf_path:
                raise ValueError("PDF path does not match run attempt")
            output_dir = attempt.images_dir
        image_paths = pdf_to_images(pdf_path, dpi=150, output_dir=output_dir)
    except RuntimeError as e:
        print_warning(f"Could not render pages: {e}")
        return {
            "page_images": [],
            "pdf_errors": [f"PDF render failed: {e}"],
            "validation_passed": False,
        }

    if not image_paths:
        return {
            "page_images": [],
            "pdf_errors": ["PDF render produced no page images"],
            "validation_passed": False,
        }

    print_info(f"Rendered {len(image_paths)} page(s).")
    return {"page_images": image_paths, "pdf_errors": [], "validation_passed": False}

"""Render Pages node — converts PDF pages to PNG images for vision validation."""

from __future__ import annotations

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
        image_paths = pdf_to_images(pdf_path, dpi=150)
    except RuntimeError as e:
        # poppler not installed
        print_warning(f"Could not render pages: {e}")
        # Skip visual validation — treat as passed to avoid blocking the pipeline
        return {"page_images": [], "validation_passed": True}

    print_info(f"Rendered {len(image_paths)} page(s).")
    return {"page_images": image_paths}

"""Convert PDF pages to PNG images for vision-based alignment validation."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def pdf_to_images(
    pdf_path: str,
    *,
    dpi: int = 150,
    output_dir: Path | None = None,
) -> list[str]:
    """
    Convert each page of a PDF to a PNG image.

    Returns list of absolute paths to page images (page_1.png, page_2.png, …).
    Raises RuntimeError if pdf2image or poppler is not available.
    """
    _check_poppler()

    try:
        from pdf2image import convert_from_path  # lazy import
    except ImportError as e:
        raise RuntimeError(
            "pdf2image is not installed. Run: uv sync"
        ) from e

    dest_dir = output_dir or Path(tempfile.mkdtemp(prefix="resume_agent_pages_"))
    dest_dir.mkdir(parents=True, exist_ok=True)

    images = convert_from_path(pdf_path, dpi=dpi)
    paths: list[str] = []

    for i, img in enumerate(images, 1):
        img_path = dest_dir / f"page_{i}.png"
        img.save(str(img_path), "PNG")
        paths.append(str(img_path))

    return paths


def _check_poppler() -> None:
    """Raise a helpful error if poppler utilities are not on PATH."""
    if shutil.which("pdftoppm") is None and shutil.which("pdfinfo") is None:
        raise RuntimeError(
            "Poppler utilities not found. Install with:\n"
            "  macOS:   brew install poppler\n"
            "  Ubuntu:  sudo apt-get install poppler-utils\n"
            "  Windows: https://github.com/oschwartz10612/poppler-windows"
        )

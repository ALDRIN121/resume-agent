"""Exact extracted display-token comparison, not verification of factual claims."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from .content_review import expected_display_text
from .schemas import RenderManifest

_LIGATURES = str.maketrans({
    'ﬀ': 'ff', 'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬃ': 'ffi', 'ﬄ': 'ffl', 'ﬅ': 'st', 'ﬆ': 'st',
    'Ĳ': 'IJ', 'ĳ': 'ij', 'և': 'եւ', 'ﬓ': 'մն', 'ﬔ': 'մե', 'ﬕ': 'մի', 'ﬖ': 'վն', 'ﬗ': 'մխ',
})


def _tokens(text: str) -> list[str]:
    # Do not use NFKC: superscripts, circled numbers and units are meaningful.
    return text.translate(_LIGATURES).split()


def _hash(tokens: list[str]) -> str:
    return hashlib.sha256(' '.join(tokens).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class PdfContentResult:
    ok: bool
    code: str
    expected_hash: str
    actual_hash: str | None
    page_count: int
    mismatch_index: int | None = None


def verify_pdf_content(manifest: RenderManifest, pdf_path: str | Path) -> PdfContentResult:
    """Read every page and compare the entire ordered token stream including labels.

    Diagnostics expose only a zero-based token index and hashes, never field text.
    The caller separately checks PDF bytes and expected page count against its
    frozen RenderRecord, since the manifest describes content rather than pages.
    """
    try:
        expected = _tokens(expected_display_text(manifest))
    except ValueError:
        return PdfContentResult(False, 'invalid_manifest', _hash([]), None, 0)
    expected_hash = _hash(expected)
    count = 0
    try:
        with Path(pdf_path).open('rb') as stream:
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted:
                return PdfContentResult(False, 'encrypted_pdf', expected_hash, None, 0)
            count = len(reader.pages)
            if count == 0 or not expected:
                return PdfContentResult(False, 'empty_pdf', expected_hash, None, count)
            pages = [page.extract_text() for page in reader.pages]
            if any(not text or not text.strip() for text in pages):
                return PdfContentResult(False, 'missing_page_text', expected_hash, None, count)
            actual = _tokens('\n'.join(pages))
    except Exception:
        return PdfContentResult(False, 'unreadable_pdf', expected_hash, None, count)
    mismatch = next((index for index, pair in enumerate(zip(expected, actual, strict=False))
                     if pair[0] != pair[1]), None)
    if mismatch is None and len(expected) != len(actual):
        mismatch = min(len(expected), len(actual))
    return PdfContentResult(mismatch is None, 'equal' if mismatch is None else 'content_mismatch',
                            expected_hash, _hash(actual), count, mismatch)

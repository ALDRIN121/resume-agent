"""Filesystem utilities: path building, slugification, output management."""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

from slugify import slugify


def slugify_name(name: str) -> str:
    """
    Convert a name to a filesystem-safe slug.
    E.g. "Aldrin Joseph" → "aldrin-joseph"
         "A&B Corp, LLC." → "a-and-b-corp-llc"
    """
    return slugify(name, separator="-", lowercase=True, allow_unicode=False, replacements=[("&", " and ")])


def build_output_path(
    base_dir: Path,
    company_name: str,
    user_full_name: str,
    *,
    today: date | None = None,
) -> Path:
    """
    Build the destination PDF path:
      <base_dir>/<company_slug>/<user_slug>_<company_slug>_<YYYY-MM-DD>.pdf

    If the file already exists, appends _v2, _v3, etc.
    """
    today = today or date.today()
    company_slug = slugify_name(company_name)
    user_slug = slugify_name(user_full_name)
    date_str = today.strftime("%Y-%m-%d")

    out_dir = base_dir / company_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = f"{user_slug}_{company_slug}_{date_str}"

    # Atomically claim a filename using O_CREAT|O_EXCL to eliminate TOCTOU race.
    # Two concurrent runs can no longer both pick the same versioned name.
    for version in [None, *range(2, 1000)]:
        suffix = "" if version is None else f"_v{version}"
        candidate = out_dir / f"{stem}{suffix}.pdf"
        try:
            fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return candidate
        except FileExistsError:
            continue

    # Fallback (virtually unreachable — 999 versions of the same file)
    raise RuntimeError(f"Could not find a free filename for {stem}")  # pragma: no cover


def build_failed_path(base_dir: Path) -> Path:
    """
    Build a path for saving failed generation artifacts:
      <base_dir>/_failed/<timestamp>/
    """
    from datetime import datetime

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    failed_dir = base_dir / "_failed" / ts
    failed_dir.mkdir(parents=True, exist_ok=True)
    return failed_dir


def sanitize_company_name(raw: str) -> str:
    """
    Lightly clean a company name for display (not slugified).
    Removes trailing punctuation, normalises whitespace.
    """
    cleaned = re.sub(r"[,\.\s]+$", "", raw.strip())
    return re.sub(r"\s+", " ", cleaned)

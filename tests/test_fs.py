"""Tests for filesystem utilities."""

import pytest
from datetime import date
from pathlib import Path


def test_slugify_name():
    from resume_agent.tools.fs import slugify_name

    assert slugify_name("Jane Doe") == "jane-doe"
    assert slugify_name("A&B Corp, LLC.") == "a-and-b-corp-llc"
    assert slugify_name("Héllo Wörld") == "hello-world"
    assert slugify_name("  Spaces  ") == "spaces"


def test_build_output_path_basic(tmp_path):
    from resume_agent.tools.fs import build_output_path

    today = date(2026, 4, 15)
    path = build_output_path(
        base_dir=tmp_path,
        company_name="TechCorp",
        user_full_name="Jane Doe",
        today=today,
    )

    assert path.parent.name == "techcorp"
    assert path.name == "jane-doe_techcorp_2026-04-15.pdf"
    # Atomic approach creates a zero-byte placeholder to claim the name;
    # output_saver_node overwrites it with the real PDF via shutil.copy2.
    assert path.exists()


def test_build_output_path_versioning(tmp_path):
    from resume_agent.tools.fs import build_output_path

    today = date(2026, 4, 15)
    # Create the base file so versioning kicks in
    base = tmp_path / "techcorp"
    base.mkdir()
    (base / "jane-doe_techcorp_2026-04-15.pdf").touch()

    path = build_output_path(
        base_dir=tmp_path,
        company_name="TechCorp",
        user_full_name="Jane Doe",
        today=today,
    )
    assert path.name == "jane-doe_techcorp_2026-04-15_v2.pdf"


def test_build_output_path_special_chars(tmp_path):
    from resume_agent.tools.fs import build_output_path

    path = build_output_path(
        base_dir=tmp_path,
        company_name="A&B Solutions, Inc.",
        user_full_name="João Silva",
        today=date(2026, 4, 15),
    )
    # Should not contain unsafe filesystem characters
    assert "&" not in path.name
    assert "," not in path.name
    assert "/" not in path.name


def test_sanitize_company_name():
    from resume_agent.tools.fs import sanitize_company_name

    assert sanitize_company_name("Google.") == "Google"
    assert sanitize_company_name("  Meta  ") == "Meta"
    assert sanitize_company_name("Amazon,") == "Amazon"

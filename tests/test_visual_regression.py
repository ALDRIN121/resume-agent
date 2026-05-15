"""
Visual regression tests — compile a fixture resume to PDF and assert structural
properties that would catch the original template defects:
  • orphan unicode glyphs from failed escape (Ȱ ć × f)
  • "companys" apostrophe loss
  • page count outside the expected range

Requires tectonic and pypdf.  Both guards use pytest.skip so CI can run the suite
without either dependency.  Mark with -m slow to opt in:

    pytest -m slow tests/test_visual_regression.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

# ── Skip markers ───────────────────────────────────────────────────────────────

pytestmark = pytest.mark.slow


def _tectonic_available() -> bool:
    return shutil.which("tectonic") is not None


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def _pypdf():
    return pytest.importorskip("pypdf")


@pytest.fixture(scope="module")
def fixture_resume():
    """A two-page-worthy resume with known-clean content."""
    from resume_agent.schemas import (
        Certification,
        Education,
        PersonalInfo,
        Project,
        Role,
        UserResume,
    )

    return UserResume(
        personal=PersonalInfo(
            full_name="Jane Doe",
            email="jane@example.com",
            phone="+1-555-010-0101",
            location="San Francisco, CA",
            linkedin="janedoe",
            github="janedoe",
            headline="Senior Software Engineer",
        ),
        summary=(
            "Backend engineer with 6 years building distributed systems. "
            "Led teams of up to 4 engineers and shipped products serving millions of users."
        ),
        experience=[
            Role(
                company="Acme Corp",
                title="Software Engineer II",
                start="Jan 2022",
                end=None,
                location="San Francisco, CA",
                bullets=[
                    "Built Python microservices platform handling 2M requests/day",
                    "Reduced API p99 latency from 450ms to 90ms via query optimisation",
                    "Migrated monolith to Docker, enabling 10x faster deployments",
                    "Mentored 2 junior engineers through code review and pair programming",
                ],
            ),
            Role(
                company="Beta Inc",
                title="Software Engineer",
                start="Jun 2019",
                end="Dec 2021",
                location="New York, NY",
                bullets=[
                    "Designed and shipped REST API used by 50 enterprise clients",
                    "Automated nightly ETL pipeline, saving 3 hours of manual work daily",
                    "Led migration from SVN to Git across 12-person engineering team",
                ],
            ),
        ],
        education=[
            Education(
                institution="State University",
                degree="B.S. Computer Science",
                graduation="May 2019",
            )
        ],
        projects=[
            Project(
                name="OpenMetrics",
                description="Open-source Prometheus exporter for distributed systems metrics.",
                url="github.com/janedoe/openmetrics",
                bullets=[
                    "Built open-source Prometheus exporter with 400+ GitHub stars",
                    "Published to PyPI; adopted by 3 Fortune 500 companies",
                ],
            )
        ],
        skills={
            "Languages": ["Python", "Go", "TypeScript"],
            "Infrastructure": ["Kubernetes", "Docker", "Terraform"],
            "Databases": ["PostgreSQL", "Redis", "Elasticsearch"],
        },
        certifications=[
            Certification(name="AWS Solutions Architect Associate", date="2023")
        ],
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _compile_fixture(resume, tmp_path) -> Path:
    """Render resume → LaTeX → PDF via tectonic.  Returns PDF path."""
    from resume_agent.agents.resume_generator import _render_template
    from resume_agent.tools.tectonic_compile import compile_latex

    latex = _render_template(resume)
    result = compile_latex(latex, output_dir=tmp_path)
    assert result.ok, "tectonic compilation failed:\n" + "\n".join(result.errors)
    assert result.pdf_path is not None
    return Path(result.pdf_path)


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _tectonic_available(), reason="tectonic not installed")
class TestVisualRegression:

    def test_pdf_compiles_without_errors(self, fixture_resume, tmp_path, _pypdf):
        """Full render→compile pipeline produces a valid PDF file."""
        pdf_path = _compile_fixture(fixture_resume, tmp_path)
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 1024  # non-trivial PDF

    def test_page_count_in_range(self, fixture_resume, tmp_path, _pypdf):
        """Fixture resume should compile to 1–2 pages."""
        from pypdf import PdfReader

        pdf_path = _compile_fixture(fixture_resume, tmp_path)
        reader = PdfReader(pdf_path)
        assert 1 <= len(reader.pages) <= 2, (
            f"Expected 1-2 pages, got {len(reader.pages)}"
        )

    def test_no_apostrophe_loss_typo(self, fixture_resume, tmp_path, _pypdf):
        """'companys' must not appear — catches the APOSTROPHE_LOSS defect."""
        from pypdf import PdfReader

        pdf_path = _compile_fixture(fixture_resume, tmp_path)
        reader = PdfReader(pdf_path)
        full_text = " ".join(page.extract_text() or "" for page in reader.pages)
        assert "companys" not in full_text.lower()

    def test_no_orphan_unicode_glyphs(self, fixture_resume, tmp_path, _pypdf):
        """Escaped unicode must not leave raw replacement glyphs in extracted text."""
        from pypdf import PdfReader

        # Characters that appear when unicode escape silently fails in the template
        orphan_glyphs = ["Ȱ", "ć", "×"]  # Ȱ  ć  ×

        pdf_path = _compile_fixture(fixture_resume, tmp_path)
        reader = PdfReader(pdf_path)
        full_text = " ".join(page.extract_text() or "" for page in reader.pages)

        for glyph in orphan_glyphs:
            assert glyph not in full_text, (
                f"Orphan unicode glyph U+{ord(glyph):04X} ({glyph!r}) found in PDF text — "
                "latex escape map is likely missing this character"
            )

    def test_candidate_name_present(self, fixture_resume, tmp_path, _pypdf):
        """Candidate full name must appear in the rendered PDF."""
        from pypdf import PdfReader

        pdf_path = _compile_fixture(fixture_resume, tmp_path)
        reader = PdfReader(pdf_path)
        full_text = " ".join(page.extract_text() or "" for page in reader.pages)
        assert "Jane Doe" in full_text

    def test_no_raw_jinja_blocks(self, fixture_resume, _pypdf, tmp_path):
        """Unrendered Jinja delimiters must never reach the LaTeX source."""
        from resume_agent.agents.resume_generator import _render_template

        latex = _render_template(fixture_resume)
        for delim in ("((", "))", "(%", "%)"):
            assert delim not in latex, (
                f"Unrendered Jinja delimiter {delim!r} found in LaTeX output"
            )

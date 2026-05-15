"""
Tests for the Jinja2 LaTeX template rendering (Phase 6.3).

These tests verify the template produces correct LaTeX output without requiring
a LaTeX compiler — they just inspect the rendered string.
"""

from __future__ import annotations

from resume_agent.agents.resume_generator import _render_template, _latex_escape
from resume_agent.schemas import (
    Education,
    PersonalInfo,
    Project,
    Role,
    UserResume,
)


def _simple_resume(**kwargs) -> UserResume:
    personal = PersonalInfo(full_name="Jane Doe", email="jane@example.com", **kwargs)
    return UserResume(personal=personal)


# ── Header rendering ───────────────────────────────────────────────────────────

class TestHeaderRender:

    def test_header_renders_name(self):
        tex = _render_template(_simple_resume())
        assert "Jane Doe" in tex

    def test_header_renders_single_line_when_short(self):
        # With only email (no linkedin/github/website), no second line break expected
        tex = _render_template(_simple_resume())
        # The \\ \vspace{1pt} line separator only appears when link fields are present
        assert r"\\ \vspace{1pt}" not in tex

    def test_header_wraps_to_two_lines_when_links_present(self):
        resume = _simple_resume(linkedin="janedoe", github="janedoe")
        tex = _render_template(resume)
        # Second-line separator should appear
        assert r"\\ \vspace{1pt}" in tex

    def test_header_linkedin_rendered(self):
        resume = _simple_resume(linkedin="janedoe")
        tex = _render_template(resume)
        assert "linkedin.com/in/janedoe" in tex

    def test_header_github_rendered(self):
        resume = _simple_resume(github="jdoe")
        tex = _render_template(resume)
        assert "github.com/jdoe" in tex

    def test_header_portfolio_rendered(self):
        resume = _simple_resume(portfolio="https://janedoe.dev/portfolio")
        tex = _render_template(resume)
        assert "Portfolio" in tex

    def test_header_headline_rendered(self):
        resume = _simple_resume(headline="Open to Remote -- EU & US")
        tex = _render_template(resume)
        # headline should appear as italic text
        assert r"\textit{" in tex
        # Ampersand must be escaped
        assert r"\&" in tex

    def test_header_no_headline_when_not_set(self):
        tex = _render_template(_simple_resume())
        # Jinja2 block for headline only renders when headline is set.
        # Scope check to the minipage (header) section to avoid matching
        # \textit inside the preamble macro definitions.
        header_start = tex.index(r"\begin{minipage}")
        header_end = tex.index(r"\end{minipage}")
        header_section = tex[header_start:header_end]
        assert r"\textit{" not in header_section

    def test_separator_is_textbar_not_math_pipe(self):
        resume = _simple_resume(phone="+1-555-0100")
        tex = _render_template(resume)
        assert r"\textbar" in tex
        # Old math-mode pipe should NOT appear in header
        # (it might still appear in other template parts, but not the header)
        header_start = tex.index(r"\begin{minipage}")
        header_end = tex.index(r"\end{minipage}")
        header_section = tex[header_start:header_end]
        assert "$|$" not in header_section


# ── Education rendering ────────────────────────────────────────────────────────

class TestEducationRender:

    def test_education_expands_when_notes_present(self):
        resume = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com"),
            education=[
                Education(
                    institution="MIT",
                    degree="B.S. Computer Science",
                    field="Computer Science",
                    graduation="May 2020",
                    notes=["Dean's List", "Thesis: Distributed Caching"],
                )
            ],
        )
        tex = _render_template(resume)
        assert r"\resumeItemListStart" in tex
        assert "Dean" in tex

    def test_education_collapses_when_notes_empty(self):
        resume = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com"),
            education=[
                Education(
                    institution="Kerala University",
                    degree="B.Tech",
                    graduation="May 2018",
                    # no field, no GPA, no notes
                )
            ],
        )
        tex = _render_template(resume)
        # The macro \resumeItemListStart appears in the preamble as a \newcommand.
        # Scope check to the Education section body only.
        edu_start = tex.index("Kerala University")
        edu_section = tex[edu_start : edu_start + 400]
        assert r"\resumeItemListStart" not in edu_section
        # Institution and degree should still appear
        assert "Kerala University" in tex
        assert "B.Tech" in tex

    def test_education_with_gpa_uses_full_form(self):
        resume = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com"),
            education=[
                Education(
                    institution="Stanford",
                    degree="M.S.",
                    gpa="3.9",
                    graduation="Jun 2022",
                )
            ],
        )
        tex = _render_template(resume)
        assert "GPA" in tex
        assert r"\resumeSubheading" in tex


# ── Project tech rendering ─────────────────────────────────────────────────────

class TestProjectRender:

    def test_project_tech_renders_gray_not_italic(self):
        resume = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com"),
            projects=[
                Project(
                    name="Resume Agent",
                    description="A CLI tool.",
                    tech=["Python", "LangGraph", "Tectonic"],
                )
            ],
        )
        tex = _render_template(resume)
        # Tech should be in gray, not italic
        assert r"\textcolor{gray!70}" in tex
        # \emph should NOT wrap the tech list
        tech_section_start = tex.index("Resume Agent")
        tech_section = tex[tech_section_start : tech_section_start + 300]
        assert r"\emph{Python" not in tech_section

    def test_project_tech_uses_period_centered_separator(self):
        resume = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com"),
            projects=[
                Project(
                    name="My Project",
                    description="Desc.",
                    tech=["Python", "Docker"],
                )
            ],
        )
        tex = _render_template(resume)
        # The separator should be \textperiodcentered{} (not comma)
        assert r"\textperiodcentered{}" in tex


# ── Skills ordering ────────────────────────────────────────────────────────────

class TestSkillsOrdering:

    def test_skill_categories_ordered_per_skill_order(self):
        resume = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com"),
            skills={
                "Tools": ["Docker", "Git"],
                "Languages": ["Python", "Go"],
                "Cloud": ["AWS", "GCP"],
            },
        )
        tex = _render_template(resume)
        # Languages should appear before Tools in the output
        lang_pos = tex.index("Languages")
        tools_pos = tex.index("Tools")
        cloud_pos = tex.index("Cloud")
        assert lang_pos < cloud_pos < tools_pos

    def test_unknown_categories_appended_after_known(self):
        resume = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com"),
            skills={
                "Hobbies": ["Chess"],
                "Languages": ["Python"],
            },
        )
        tex = _render_template(resume)
        lang_pos = tex.index("Languages")
        hobby_pos = tex.index("Hobbies")
        assert lang_pos < hobby_pos


# ── Unicode / escape ───────────────────────────────────────────────────────────

class TestEscapeFilters:

    def test_unicode_apostrophe_normalized(self):
        # The ’ right-single-quote should be mapped to straight apostrophe
        assert _latex_escape("company’s") == "company's"

    def test_unicode_em_dash_normalized(self):
        assert _latex_escape("foo—bar") == "foo---bar"

    def test_unicode_en_dash_normalized(self):
        assert _latex_escape("2020–2022") == "2020--2022"

    def test_left_double_quote_normalized(self):
        assert _latex_escape("“hello”") == "``hello''"

    def test_ampersand_escaped(self):
        assert _latex_escape("R&D") == r"R\&D"

    def test_percent_escaped(self):
        assert _latex_escape("50%") == r"50\%"

    def test_name_with_smart_quote_in_template(self):
        # Smart apostrophe in a bullet should render as straight apostrophe in LaTeX
        resume = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com"),
            experience=[
                Role(
                    company="Acme",
                    title="Engineer",
                    start="Jan 2020",
                    end="Dec 2022",
                    bullets=["Improved the team’s velocity"],
                )
            ],
        )
        tex = _render_template(resume)
        # Smart quote should be escaped to straight apostrophe, not left as Unicode
        assert "’" not in tex
        assert "team's velocity" in tex

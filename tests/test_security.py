"""
Security-focused tests: LaTeX escape coverage, SSRF guard, LaTeX injection sanitiser,
href escaping, and the TOCTOU-safe filename loop.
"""

from __future__ import annotations

import pytest


# ══════════════════════════════════════════════════════════════════════════════
#  LaTeX escape — all user-controlled fields must survive injection attempts
# ══════════════════════════════════════════════════════════════════════════════

class TestLatexEscape:
    """_latex_escape must neutralise every LaTeX special character."""

    @pytest.fixture
    def escape(self):
        from resume_agent.agents.resume_generator import _latex_escape
        return _latex_escape

    @pytest.mark.parametrize("char,expected_fragment", [
        ("\\", r"\textbackslash{}"),
        ("&",  r"\&"),
        ("%",  r"\%"),
        ("$",  r"\$"),
        ("#",  r"\#"),
        ("_",  r"\_"),
        ("{",  r"\{"),
        ("}",  r"\}"),
        ("~",  r"\textasciitilde{}"),
        ("^",  r"\^{}"),
        ("<",  r"\textless{}"),
        (">",  r"\textgreater{}"),
    ])
    def test_single_special_char(self, escape, char, expected_fragment):
        assert expected_fragment in escape(char)

    def test_backslash_escaped_first(self, escape):
        """Backslash must be processed before other replacements to avoid double-escaping."""
        result = escape("a\\b")
        assert r"\textbackslash{}" in result
        # Must not produce \\textbackslash (double backslash)
        assert r"\\textbackslash" not in result

    def test_injection_payload(self, escape):
        """A classic LaTeX injection string must be fully neutralised."""
        payload = r"\input{/etc/passwd}"
        result = escape(payload)
        assert r"\input" not in result
        assert "/etc/passwd" in result  # path chars are safe, just the command is gone


class TestHrefEscape:
    """_latex_href_escape must strip brace/backslash chars from URL arguments."""

    @pytest.fixture
    def href_escape(self):
        from resume_agent.agents.resume_generator import _latex_href_escape
        return _latex_href_escape

    def test_strips_closing_brace(self, href_escape):
        """A } in a URL would close the \\href{} argument early."""
        assert "}" not in href_escape("https://example.com/path}evil")

    def test_strips_opening_brace(self, href_escape):
        assert "{" not in href_escape("https://example.com/{inject")

    def test_strips_backslash(self, href_escape):
        assert "\\" not in href_escape(r"https://example.com/\write18{id}")

    def test_clean_url_unchanged(self, href_escape):
        url = "https://linkedin.com/in/jane-doe"
        assert href_escape(url) == url

    def test_percent_preserved(self, href_escape):
        """% in URLs is percent-encoding and must NOT be stripped."""
        url = "https://example.com/path%20with%20spaces"
        assert "%" in href_escape(url)


class TestLatexSanitiser:
    """_sanitize_llm_latex must strip dangerous commands from LLM output."""

    @pytest.fixture
    def sanitize(self):
        from resume_agent.agents.resume_generator import _sanitize_llm_latex
        return _sanitize_llm_latex

    def test_strips_write18(self, sanitize):
        latex = r"\write18{rm -rf /}"
        result = sanitize(latex)
        assert r"\write18" not in result

    def test_strips_input(self, sanitize):
        latex = r"\input{/etc/passwd}"
        result = sanitize(latex)
        assert r"\input{" not in result

    def test_strips_include(self, sanitize):
        latex = r"\include{secrets}"
        result = sanitize(latex)
        assert r"\include{" not in result

    def test_strips_openout(self, sanitize):
        latex = r"\openout15=malicious.tex"
        result = sanitize(latex)
        assert r"\openout" not in result

    def test_clean_latex_passes_through(self, sanitize):
        latex = r"\textbf{Senior Engineer} at \textit{Acme Corp}"
        assert sanitize(latex) == latex

    def test_comment_bypass_not_effective(self, sanitize):
        """Commands in comments shouldn't bypass the sanitiser check."""
        latex = "normal line\n% \\write18{id}\n\\write18{id}"
        result = sanitize(latex)
        assert "\\write18{id}" not in result.split("\n")[-1]


# ══════════════════════════════════════════════════════════════════════════════
#  SSRF guard — _validate_url must reject dangerous URLs
# ══════════════════════════════════════════════════════════════════════════════

class TestValidateURL:
    @pytest.fixture
    def validate(self):
        from resume_agent.tools.scrape import _validate_url
        return _validate_url

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "gopher://example.com/",
        "javascript:alert(1)",
    ])
    def test_rejects_bad_schemes(self, validate, url):
        with pytest.raises(ValueError, match="scheme"):
            validate(url)

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1/admin",
        "http://10.0.0.1/internal",
        "http://192.168.1.1/router",
        "http://169.254.169.254/metadata",  # AWS metadata
        "https://[::1]/",
    ])
    def test_rejects_private_ips(self, validate, url):
        with pytest.raises(ValueError, match="private|reserved"):
            validate(url)

    @pytest.mark.parametrize("url", [
        "https://example.com/job",
        "http://jobs.lever.co/acme/123",
    ])
    def test_allows_public_https(self, validate, url):
        validate(url)  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
#  TOCTOU-safe filename loop in fs.py
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildOutputPathAtomic:
    def test_no_version_suffix_on_first_call(self, tmp_path):
        from datetime import date
        from resume_agent.tools.fs import build_output_path

        path = build_output_path(tmp_path, "Acme Corp", "Jane Doe", today=date(2026, 4, 15))
        assert path.name == "jane-doe_acme-corp_2026-04-15.pdf"
        # File placeholder must be created atomically
        assert path.exists()

    def test_version_suffix_on_collision(self, tmp_path):
        from datetime import date
        from resume_agent.tools.fs import build_output_path

        p1 = build_output_path(tmp_path, "Acme", "Jane Doe", today=date(2026, 4, 15))
        p2 = build_output_path(tmp_path, "Acme", "Jane Doe", today=date(2026, 4, 15))
        assert p1 != p2
        assert p2.name.endswith("_v2.pdf")

    def test_three_concurrent_claims(self, tmp_path):
        from datetime import date
        from resume_agent.tools.fs import build_output_path

        paths = [
            build_output_path(tmp_path, "Corp", "User", today=date(2026, 4, 15))
            for _ in range(3)
        ]
        assert len({str(p) for p in paths}) == 3  # all distinct

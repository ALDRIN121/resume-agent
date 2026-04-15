"""
Pipeline node tests: Tectonic wrapper (binary-missing, timeout, stderr parsing)
and resume-generator retry-loop state contract.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════════════
#  Tectonic compile wrapper
# ══════════════════════════════════════════════════════════════════════════════

class TestCompileLatex:

    def test_binary_missing_returns_error(self):
        from resume_agent.tools.tectonic_compile import compile_latex

        with patch("resume_agent.tools.tectonic_compile.shutil.which", return_value=None):
            result = compile_latex("\\documentclass{article}", tectonic_path="tectonic")

        assert not result.ok
        assert result.pdf_path is None
        assert any("not found" in e.lower() or "install" in e.lower() for e in result.errors)

    def test_timeout_returns_error(self, tmp_path):
        from resume_agent.tools.tectonic_compile import compile_latex

        with patch("resume_agent.tools.tectonic_compile.shutil.which", return_value="/usr/bin/tectonic"), \
             patch("resume_agent.tools.tectonic_compile.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="tectonic", timeout=1)):
            result = compile_latex("\\documentclass{article}", timeout=1, output_dir=tmp_path)

        assert not result.ok
        assert result.pdf_path is None
        assert any("timeout" in e.lower() or "timed out" in e.lower() for e in result.errors)

    def test_parse_tectonic_errors_exclamation(self):
        from resume_agent.tools.tectonic_compile import _parse_tectonic_errors

        log = "! Undefined control sequence\n! LaTeX Error: Missing \\begin{document}.\nsome other line"
        errors = _parse_tectonic_errors(log)
        assert any("Undefined control sequence" in e for e in errors)

    def test_parse_tectonic_errors_fallback(self):
        """When no ! lines exist, return last non-empty lines."""
        from resume_agent.tools.tectonic_compile import _parse_tectonic_errors

        log = "line1\nline2\nline3\nline4\nfinal error line"
        errors = _parse_tectonic_errors(log)
        assert errors  # fallback must return something
        assert "final error line" in errors[-1]

    def test_nonzero_returncode_returns_errors(self, tmp_path):
        from resume_agent.tools.tectonic_compile import compile_latex

        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stderr = "! Undefined control sequence"
        fake_result.stdout = ""

        with patch("resume_agent.tools.tectonic_compile.shutil.which", return_value="/usr/bin/tectonic"), \
             patch("resume_agent.tools.tectonic_compile.subprocess.run", return_value=fake_result):
            result = compile_latex("\\documentclass{article}", output_dir=tmp_path)

        assert not result.ok
        assert result.errors


# ══════════════════════════════════════════════════════════════════════════════
#  Resume generator retry-loop state contract
# ══════════════════════════════════════════════════════════════════════════════

class TestResumeGeneratorNode:

    @pytest.fixture
    def fake_llm_factory(self):
        """Return a factory that yields a mock LLM returning canned LaTeX."""
        def _factory(latex_output: str):
            llm = MagicMock()
            llm.invoke.return_value = MagicMock(content=latex_output)
            return llm
        return _factory

    def test_first_run_increments_retries_to_one(self, fake_llm_factory):
        """On the first call generator_retries should go from 0 → 1."""
        from resume_agent.agents.resume_generator import resume_generator_node
        from resume_agent.schemas import PersonalInfo, UserResume

        canned_latex = "\\documentclass{article}\\begin{document}Hello\\end{document}"
        resume = UserResume(personal=PersonalInfo(full_name="Jane Doe", email="j@d.com"))

        state = {
            "generator_retries": 0,
            "base_resume": resume,
            "tailored_resume": None,
            "jd": None,
            "latex_source": "",
            "latex_errors": [],
            "pdf_errors": [],
            "validation_feedback": None,
        }

        with patch("resume_agent.agents.resume_generator.ResumeAgentSettings") as mock_cfg, \
             patch("resume_agent.agents.resume_generator.get_chat_model",
                   return_value=fake_llm_factory(canned_latex)):
            mock_cfg.load.return_value = MagicMock()
            result = resume_generator_node(state)

        assert result["generator_retries"] == 1
        assert result["latex_errors"] == []
        assert result["pdf_errors"] == []
        assert canned_latex in result["latex_source"]

    def test_retry_path_uses_fix_latex(self, fake_llm_factory):
        """On retries (retries > 0 + existing latex), node must take the fix path."""
        from resume_agent.agents.resume_generator import resume_generator_node
        from resume_agent.schemas import PersonalInfo, UserResume

        original_latex = "\\documentclass{article}\\begin{document}Bad\\end{document}"
        fixed_latex = "\\documentclass{article}\\begin{document}Fixed\\end{document}"
        resume = UserResume(personal=PersonalInfo(full_name="Jane Doe", email="j@d.com"))

        state = {
            "generator_retries": 1,  # already ran once → retry path
            "base_resume": resume,
            "tailored_resume": None,
            "jd": None,
            "latex_source": original_latex,
            "latex_errors": ["! Undefined control sequence"],
            "pdf_errors": [],
            "validation_feedback": None,
        }

        with patch("resume_agent.agents.resume_generator.ResumeAgentSettings") as mock_cfg, \
             patch("resume_agent.agents.resume_generator.get_chat_model",
                   return_value=fake_llm_factory(fixed_latex)):
            mock_cfg.load.return_value = MagicMock()
            result = resume_generator_node(state)

        assert result["generator_retries"] == 2
        assert fixed_latex in result["latex_source"]
        # Errors must be cleared so the validator runs fresh
        assert result["latex_errors"] == []

    def test_dangerous_commands_stripped_from_output(self, fake_llm_factory):
        """LLM output containing \\write18 must be sanitised before returning."""
        from resume_agent.agents.resume_generator import resume_generator_node
        from resume_agent.schemas import PersonalInfo, UserResume

        malicious_latex = "\\documentclass{article}\\write18{rm -rf /}\\begin{document}\\end{document}"
        resume = UserResume(personal=PersonalInfo(full_name="Jane Doe", email="j@d.com"))

        state = {
            "generator_retries": 0,
            "base_resume": resume,
            "tailored_resume": None,
            "jd": None,
            "latex_source": "",
            "latex_errors": [],
            "pdf_errors": [],
            "validation_feedback": None,
        }

        with patch("resume_agent.agents.resume_generator.ResumeAgentSettings") as mock_cfg, \
             patch("resume_agent.agents.resume_generator.get_chat_model",
                   return_value=fake_llm_factory(malicious_latex)):
            mock_cfg.load.return_value = MagicMock()
            result = resume_generator_node(state)

        assert r"\write18" not in result["latex_source"]


# ══════════════════════════════════════════════════════════════════════════════
#  Bot-wall test — verify it actually tests the fallback path
# ══════════════════════════════════════════════════════════════════════════════

class TestBotWallFallback:

    @pytest.mark.asyncio
    async def test_bot_wall_triggers_playwright_fallback_error(self):
        """
        When httpx returns bot-wall content AND playwright_fallback=True,
        the scraper must attempt Playwright (which fails without a real browser,
        giving a specific error message).
        """
        import respx
        import httpx

        with respx.mock:
            respx.get("https://linkedin.com/jobs/1").mock(
                return_value=httpx.Response(
                    200, text="<html><body>Please enable JavaScript to view this page.</body></html>"
                )
            )

            from resume_agent.tools.scrape import scrape_url
            # With playwright_fallback=True (default), it should attempt Playwright
            # and fail with an ImportError or Playwright error — not a content error.
            result = await scrape_url(
                "https://linkedin.com/jobs/1",
                playwright_fallback=True,
            )

        # Either Playwright is installed (and fails with network), or not installed.
        # In both cases, error should mention "Both scrapers failed" or "not installed".
        assert result.error is not None
        assert result.used_playwright is True

    @pytest.mark.asyncio
    async def test_bot_wall_playwright_disabled_returns_content_error(self):
        """
        With playwright_fallback=False, bot-wall returns an error about short/bot content,
        NOT a playwright error. This is the original test's intended behaviour.
        """
        import respx
        import httpx

        with respx.mock:
            respx.get("https://linkedin.com/jobs/1").mock(
                return_value=httpx.Response(
                    200, text="<html><body>Please enable JavaScript</body></html>"
                )
            )

            from resume_agent.tools.scrape import scrape_url
            result = await scrape_url(
                "https://linkedin.com/jobs/1",
                playwright_fallback=False,
            )

        assert result.error is not None
        assert not result.used_playwright

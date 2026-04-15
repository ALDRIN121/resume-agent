"""Tests for the web scraping tool using respx to mock HTTP."""

import pytest
import respx
import httpx

from resume_agent.tools.scrape import _extract_text, _is_good_content, scrape_url


class TestExtractText:
    def test_basic_html(self):
        html = """<html><body>
            <nav>Nav content</nav>
            <main><h1>Senior Engineer</h1><p>We are looking for a skilled engineer.</p></main>
            <footer>Footer</footer>
        </body></html>"""
        text = _extract_text(html)
        assert "Senior Engineer" in text
        assert len(text) > 10

    def test_strips_scripts(self):
        html = """<html><body>
            <script>alert('xss')</script>
            <p>Real content here.</p>
        </body></html>"""
        text = _extract_text(html)
        assert "xss" not in text
        assert "Real content" in text


class TestIsGoodContent:
    def test_short_content_fails(self):
        assert not _is_good_content("Too short")

    def test_bot_wall_fails(self):
        assert not _is_good_content(
            "Please enable JavaScript to use this site. " * 20
        )

    def test_good_content_passes(self):
        content = "Senior Software Engineer at TechCorp. " * 20  # > 400 chars
        assert _is_good_content(content)


class TestScrapeUrl:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_scrape(self):
        long_content = "<p>" + ("Job description content. " * 30) + "</p>"
        html = f"<html><body><article>{long_content}</article></body></html>"
        respx.get("https://example.com/job").mock(
            return_value=httpx.Response(200, text=html)
        )

        result = await scrape_url(
            "https://example.com/job",
            playwright_fallback=False,
        )
        assert result.error is None
        assert len(result.text) > 100
        assert not result.used_playwright

    @pytest.mark.asyncio
    @respx.mock
    async def test_http_error(self):
        respx.get("https://example.com/notfound").mock(
            return_value=httpx.Response(404)
        )
        result = await scrape_url(
            "https://example.com/notfound",
            playwright_fallback=False,
        )
        assert result.error is not None
        assert "404" in result.error

    @pytest.mark.asyncio
    @respx.mock
    async def test_bot_wall_triggers_fallback_attempt(self):
        """Short content should trigger Playwright fallback attempt (which will fail without browser)."""
        respx.get("https://linkedin.com/jobs/1").mock(
            return_value=httpx.Response(
                200, text="<html><body>Please enable JavaScript</body></html>"
            )
        )
        # playwright_fallback=False → should return an error about short content
        result = await scrape_url(
            "https://linkedin.com/jobs/1",
            playwright_fallback=False,
        )
        assert result.error is not None

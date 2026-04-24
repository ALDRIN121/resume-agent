"""
Web scraping tool with httpx+readability first, Playwright fallback.

Strategy:
  1. Validate URL (scheme allow-list + literal private-IP block)
  2. GET page with httpx (fast, no browser deps)
  3. Extract article text via readability-lxml
  4. If content too short or bot-wall detected → retry with Playwright headless
"""

from __future__ import annotations

import ipaddress
import re
from typing import NamedTuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from readability import Document

# Markers that indicate JS-gated or bot-wall pages
_BOT_WALL_PATTERNS = re.compile(
    r"enable javascript|please verify|captcha|sign in to view|"
    r"access denied|403 forbidden|bot detected",
    re.IGNORECASE,
)

_MIN_CONTENT_LENGTH = 400  # chars below this triggers Playwright fallback
_ALLOWED_SCHEMES = {"http", "https"}
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB cap


class ScrapeResult(NamedTuple):
    text: str
    used_playwright: bool
    error: str | None


def _validate_url(url: str) -> None:
    """
    Reject URLs that are unsafe to fetch.

    Blocks:
    - Non-http/https schemes (file://, gopher://, ftp://, etc.)
    - Literal private/loopback/link-local IP addresses in the hostname
    - URLs with no hostname

    Note: DNS-rebinding attacks (a public hostname resolving to a private IP)
    are not addressed here; mitigate at the network/firewall level.
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"Blocked URL scheme {parsed.scheme!r}. Only http/https are allowed."
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname.")

    # Block literal private/loopback/link-local/reserved IP addresses
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(
                f"Blocked URL: hostname {hostname!r} is a private/reserved address."
            )
    except ValueError as exc:
        # Re-raise our own ValueError; swallow the "not a valid IP" error from ip_address()
        if "Blocked" in str(exc):
            raise


async def scrape_url(
    url: str,
    *,
    user_agent: str = "resume-generator/1.0",
    timeout: int = 30,
    playwright_fallback: bool = True,
) -> ScrapeResult:
    """
    Scrape job description text from a URL.

    Returns ScrapeResult with clean text, or error if scraping fails.
    """
    try:
        _validate_url(url)
    except ValueError as exc:
        return ScrapeResult(text="", used_playwright=False, error=str(exc))

    # ── Step 1: httpx + readability ────────────────────────────────────────────
    text, error = await _scrape_httpx(url, user_agent=user_agent, timeout=timeout)

    if error is None and _is_good_content(text):
        return ScrapeResult(text=text, used_playwright=False, error=None)

    if not playwright_fallback:
        if error:
            return ScrapeResult(text="", used_playwright=False, error=error)
        return ScrapeResult(
            text=text,
            used_playwright=False,
            error=f"Content too short ({len(text)} chars) and Playwright fallback is disabled.",
        )

    # ── Step 2: Playwright fallback ────────────────────────────────────────────
    text, pw_error = await _scrape_playwright(url, timeout=timeout)
    if pw_error:
        original_err = error or f"httpx returned {len(text)} chars (too short)"
        return ScrapeResult(
            text="",
            used_playwright=True,
            error=f"Both scrapers failed. httpx: {original_err}. Playwright: {pw_error}",
        )

    if not _is_good_content(text):
        return ScrapeResult(
            text="",
            used_playwright=True,
            error=(
                f"Playwright returned {len(text)} chars — the page may require login or "
                "bypass a paywall. Tip: paste the job description as text with --jd-text."
            ),
        )

    return ScrapeResult(text=text, used_playwright=True, error=None)


async def _scrape_httpx(
    url: str, *, user_agent: str, timeout: int
) -> tuple[str, str | None]:
    """Fetch and extract text with httpx + readability. Returns (text, error)."""
    headers = {"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.9"}
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            max_redirects=5,
        ) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            # Enforce content-type and size limits
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return "", f"Unexpected content type: {content_type!r}"
            if len(resp.content) > _MAX_RESPONSE_BYTES:
                return "", f"Response too large ({len(resp.content)} bytes)"
            html = resp.text
    except httpx.HTTPStatusError as e:
        return "", f"HTTP {e.response.status_code}: {e.response.reason_phrase}"
    except httpx.RequestError as e:
        return "", f"Request failed: {e}"

    text = _extract_text(html)

    if _BOT_WALL_PATTERNS.search(text[:500]):
        return text, "Bot-wall detected in page content"

    return text, None


async def _scrape_playwright(url: str, *, timeout: int) -> tuple[str, str | None]:
    """Fetch via headless Chromium. Returns (text, error)."""
    try:
        from playwright.async_api import async_playwright  # lazy import
    except ImportError:
        return "", "Playwright not installed. Run: uv sync && playwright install chromium"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            # Block requests to private IPs at the Playwright level
            async def _block_private(route, request):
                try:
                    parsed = urlparse(request.url)
                    hostname = parsed.hostname or ""
                    _validate_url(request.url)
                    await route.continue_()
                except ValueError:
                    await route.abort()

            page = await context.new_page()
            await page.route("**/*", _block_private)
            await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            html = await page.content()
            await browser.close()

        text = _extract_text(html)
        return text, None

    except Exception as e:  # noqa: BLE001
        return "", str(e)


def _extract_text(html: str) -> str:
    """Extract main article text from HTML using readability + BeautifulSoup."""
    try:
        doc = Document(html)
        article_html = doc.summary()
        soup = BeautifulSoup(article_html, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
    except Exception:  # noqa: BLE001
        # Fallback: plain BS4 text extraction
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)

    # Collapse excess whitespace
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def _is_good_content(text: str) -> bool:
    """Return True if the scraped text looks like a real job description."""
    if len(text) < _MIN_CONTENT_LENGTH:
        return False
    if _BOT_WALL_PATTERNS.search(text[:500]):
        return False
    return True

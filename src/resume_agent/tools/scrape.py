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
import socket
from typing import NamedTuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from readability import Document

# Markers that indicate JS-gated or bot-wall pages
_BOT_WALL_PATTERNS = re.compile(
    r"enable javascript|please verify|captcha|sign in to view|"
    r"access denied|403 forbidden|bot detected|choose language|"
    r"選擇語言|join now|go to your feed|pumunta sa iyong feed",
    re.IGNORECASE,
)

_MIN_CONTENT_LENGTH = 400  # chars below this triggers Playwright fallback
_ALLOWED_SCHEMES = {"http", "https"}
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB cap
_MAX_REDIRECTS = 5


class ScrapeResult(NamedTuple):
    text: str
    used_playwright: bool
    error: str | None


def _reject_if_internal(ip_str: str, hostname: str) -> None:
    """Raise if an IP literal points at a private/loopback/reserved range."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        raise ValueError(
            f"Blocked URL: {hostname!r} maps to a private/reserved address ({ip_str})."
        )


def _validate_url(url: str) -> None:
    """
    Reject URLs that are unsafe to fetch.

    Blocks:
    - Non-http/https schemes (file://, gopher://, ftp://, etc.)
    - URLs with no hostname
    - Literal private/loopback/link-local/reserved IP addresses
    - Public hostnames that *resolve* to a private/reserved address (DNS
      rebinding): every address returned by getaddrinfo is checked.

    A residual TOCTOU gap remains between this check and the socket connect;
    each redirect hop is re-validated by the caller to narrow it.
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"Blocked URL scheme {parsed.scheme!r}. Only http/https are allowed."
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname.")

    # Literal IP — check directly without a DNS lookup.
    try:
        ipaddress.ip_address(hostname)
        _reject_if_internal(hostname, hostname)
        return
    except ValueError as exc:
        if "Blocked" in str(exc):
            raise

    # Hostname — resolve and validate every address it maps to.
    try:
        infos = socket.getaddrinfo(hostname, parsed.port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname {hostname!r}.") from exc
    for info in infos:
        _reject_if_internal(str(info[4][0]), hostname)


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
        # Follow redirects manually so every hop is re-validated against the
        # SSRF rules — httpx's own follow_redirects only validates the first URL.
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            current = url
            html = ""
            for _ in range(_MAX_REDIRECTS + 1):
                _validate_url(current)
                resp = await client.get(current, headers=headers)
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        break
                    current = str(resp.url.join(location))
                    continue
                resp.raise_for_status()
                # Enforce content-type and size limits
                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return "", f"Unexpected content type: {content_type!r}"
                if len(resp.content) > _MAX_RESPONSE_BYTES:
                    return "", f"Response too large ({len(resp.content)} bytes)"
                html = resp.text
                break
            else:
                return "", f"Too many redirects (>{_MAX_REDIRECTS})"
    except ValueError as e:
        return "", str(e)
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

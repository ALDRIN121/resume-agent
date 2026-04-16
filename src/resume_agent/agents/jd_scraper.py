"""JD Scraper agent node — scrapes job description text from a URL."""

from __future__ import annotations

import asyncio

from ..config import ResumeAgentSettings
from ..state import ResumeGenState
from ..tools.scrape import scrape_url
from ..ui.panels import print_agent_step, print_info, print_warning


def jd_scraper_node(state: ResumeGenState) -> dict:
    """
    Scrape the job description URL from state["raw_input"].
    Populates scraped_text on success, or scrape_error on failure.
    """
    settings = ResumeAgentSettings.load()
    url = state["raw_input"]

    print_agent_step("JD Scraper", "Fetching job posting from the web…")
    print_info(f"URL: {url}")

    result = asyncio.run(
        scrape_url(
            url,
            user_agent=settings.scraping.user_agent,
            timeout=settings.scraping.timeout_seconds,
            playwright_fallback=settings.scraping.playwright_fallback,
        )
    )

    if result.error:
        return {"scrape_error": result.error}

    if result.used_playwright:
        print_warning("Static scraping insufficient — used Playwright headless browser.")

    print_info(f"Scraped {len(result.text)} characters.")
    return {"scraped_text": result.text, "scrape_error": None}

"""Real browser recovery after a lost response and a crashed profile save."""
# Imported pytest fixtures are injected by their parameter names.
# ruff: noqa: F811
import asyncio
import json
import os

import httpx
import pytest
from playwright.async_api import expect

from tests.test_reliability_journey import real_page, real_server  # noqa: F401

pytestmark = pytest.mark.skipif(
    os.getenv("RESUME_REAL_BROWSER_TEST") != "1", reason="Real browser acceptance flag not set"
)


async def test_import_creation_with_lost_client_id_is_discovered_without_model_work(
    real_page, real_server
):
    page = real_page
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        before = (await client.get("/api/profile")).json()
        # Simulate a create response that never reached the browser's storage.
        created = await client.post(
            "/api/resume/upload?defer_processing=true",
            files={"file": ("lost-response.tex", b"Complete source.")},
        )
        assert created.status_code == 200
    await page.goto(real_server.url, wait_until="domcontentloaded")
    await expect(
        page.get_by_role("heading", name="Import ready to process", exact=True)
    ).to_be_visible()
    assert not (real_server.root / "model-calls.jsonl").exists()
    await page.get_by_role("button", name="Cancel import", exact=True).click()
    await expect(page.get_by_role("heading", name="Import stopped", exact=True)).to_be_visible()
    await page.get_by_role("button", name="Close", exact=True).last.click()
    await expect(page.get_by_role("button", name="Library", exact=True)).to_be_enabled()
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        assert (await client.get("/api/profile")).json() == before
        assert (await client.get("/api/profile/imports")).json()["total"] == 0
    assert not (real_server.root / "model-calls.jsonl").exists()


async def test_browser_continues_interrupted_profile_save_without_reparsing(real_page, real_server):
    page = real_page
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        operation = (
            await client.post(
                "/api/profile/imports",
                files={"file": ("resume.tex", b"Fictional complete profile source.")},
            )
        ).json()
    await page.goto(real_server.url, wait_until="domcontentloaded")
    await page.evaluate('(id)=>localStorage.setItem("rg.activeImport",id)', operation["id"])
    await page.reload(wait_until="domcontentloaded")
    await expect(
        page.get_by_role("heading", name="Review imported resume", exact=True)
    ).to_be_visible()
    (real_server.root / "crash-import-after-save").write_text("fixture")
    await page.get_by_role("button", name="Accept reviewed import", exact=True).click()
    for _ in range(100):
        if real_server.process.poll() is not None:
            break
        await asyncio.sleep(0.1)
    assert real_server.process.poll() == 91
    saved = (real_server.root / "base_resume.yaml").read_bytes()
    await real_server.restart()
    await page.reload(wait_until="domcontentloaded")
    await expect(page.get_by_role("heading", name="Import interrupted", exact=True)).to_be_visible()
    await page.get_by_role("button", name="Minimize", exact=True).first.click()
    await expect(page.get_by_role("button", name="Library", exact=True)).to_be_enabled()
    await page.locator(".resume-parsing-banner").click()
    await page.get_by_role("button", name="Continue saved import", exact=True).click()
    await expect(page.get_by_role("heading", name="Base resume parsed", exact=True)).to_be_visible()
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        assert (await client.get("/api/profile/imports/" + operation["id"])).json()[
            "status"
        ] == "complete"
    assert (real_server.root / "base_resume.yaml").read_bytes() == saved
    assert [
        json.loads(line)["stage"]
        for line in (real_server.root / "model-calls.jsonl").read_text().splitlines()
    ] == ["import_profile"]

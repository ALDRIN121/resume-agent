"""Unmocked browser/API/socket acceptance with real PDF tools and isolated state.

Enable with RESUME_REAL_BROWSER_TEST=1. CI's required browser job sets this flag.
This suite never intercepts API or WebSocket traffic.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from playwright.async_api import async_playwright, expect

pytestmark = pytest.mark.skipif(os.getenv('RESUME_REAL_BROWSER_TEST') != '1',
                                reason='Real browser acceptance is enabled in the required browser job')


class LocalServer:
    def __init__(self, root, port, profile='ready'):
        self.root, self.port, self.profile = root, port, profile
        self.process = None
        self.log = None
        self.url = f'http://127.0.0.1:{port}'

    async def start(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.log = (self.root / 'server.log').open('a', encoding='utf-8')
        self.process = subprocess.Popen([sys.executable, '-m', 'tests.reliability_server',
            '--root', str(self.root), '--port', str(self.port), '--profile', self.profile],
            cwd=Path(__file__).resolve().parents[1], env=os.environ.copy(),
            stdout=self.log, stderr=subprocess.STDOUT)
        async with httpx.AsyncClient() as client:
            for _ in range(150):
                if self.process.poll() is not None:
                    pytest.fail((self.root / 'server.log').read_text())
                try:
                    if (await client.get(self.url + '/api/health')).status_code == 200:
                        return self
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.1)
        self.stop()
        pytest.fail('The isolated real API did not start within 15 seconds.')

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log is not None:
            self.log.close()

    async def restart(self):
        self.stop()
        await self.start()


@pytest.fixture
async def real_server(tmp_path, unused_tcp_port):
    # Required acceptance must fail rather than skip if the toolchain is absent.
    for tool in ('tectonic', 'pdftoppm', 'pdfinfo'):
        assert shutil.which(tool), f'Required browser acceptance tool missing: {tool}'
    server = LocalServer(tmp_path / 'state', unused_tcp_port)
    await server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
async def real_page():
    async with async_playwright() as playwright:
        options = {'headless': True}
        if executable := os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE'):
            options['executable_path'] = executable
        browser = await playwright.chromium.launch(**options)
        page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        # Only an external font request is blocked; app/API/socket traffic is real.
        await page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        try:
            yield page
            assert errors == []
        finally:
            if output := os.getenv('RESUME_EVIDENCE_DIR'):
                destination = Path(output)
                destination.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(destination / 'last-browser-state.png'), full_page=True)
                (destination / 'last-browser-state.html').write_text(await page.content())
            await browser.close()


async def open_saved_run(page):
    await page.get_by_role('button', name='Library', exact=True).click()
    await page.get_by_text('Example QA — Reliability Engineer', exact=True).first.click()


@pytest.mark.parametrize("selected", [False, True], ids=["reject-all", "visible-edit"])
async def test_real_review_restart_and_exact_export(real_server, real_page, tmp_path, selected):
    page, base = real_page, real_server.url
    sockets = []
    page.on('websocket', lambda socket: sockets.append(socket.url))
    await page.goto(base, wait_until='domcontentloaded')
    await page.get_by_role('button', name='Create resume', exact=True).click()
    await expect(page.get_by_text('Ready to create a resume', exact=True)).to_be_visible()
    await page.get_by_placeholder('Paste the full job description here…').fill(
        'Example QA needs a Reliability Engineer with Python and production monitoring. ' * 4)
    async with page.expect_response(lambda response: response.url == base + '/api/runs'
                                    and response.request.method == 'POST') as created:
        await page.get_by_role('button', name=re.compile('^Generate')).click()
    run_id = (await (await created.value).json())['thread_id']
    answer = page.get_by_role('textbox', name='What should remain unchanged?', exact=True)
    await expect(answer).to_be_visible(timeout=15000)
    await answer.fill('Preserve the helper role and the supplied metric order.')
    # Observe the real IndexedDB commit before terminating the server/reloading.
    await page.wait_for_function("""({run, answer}) => new Promise(resolve => {
        const request = indexedDB.open('resume-agent-form-drafts', 1);
        request.onerror = () => resolve(false);
        request.onsuccess = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains('drafts')) { db.close(); resolve(false); return; }
            const read = db.transaction('drafts').objectStore('drafts').getAll();
            read.onerror = () => { db.close(); resolve(false); };
            read.onsuccess = () => {
                const found = read.result.some(row => row.identity.run === run && row.value.answers?.q1 === answer);
                db.close(); resolve(found);
            };
        };
    })""", arg={'run': run_id, 'answer': 'Preserve the helper role and the supplied metric order.'})
    async with httpx.AsyncClient(base_url=base) as client:
        first = (await client.get(f'/api/runs/{run_id}')).json()
        assert first['pending']['kind'] == 'ask_missing'
        assert (await client.get(f'/api/runs/{run_id}/pdf')).status_code in (404, 409)
    await real_server.restart()
    await page.reload(wait_until='domcontentloaded')
    await open_saved_run(page)
    await expect(answer).to_have_value('Preserve the helper role and the supplied metric order.')
    await page.get_by_role('button', name='Submit answers', exact=True).click()
    await expect(page.get_by_role('button', name='Review complete content', exact=True)).to_be_visible()
    for checkbox in await page.locator('.review-flow input[type=checkbox]').all():
        await expect(checkbox).not_to_be_checked()
    if selected:
        await page.get_by_role('checkbox', name='Select Summary', exact=True).check()
    await real_server.restart()
    await page.reload(wait_until='domcontentloaded')
    await open_saved_run(page)
    if selected:
        await expect(page.get_by_role('checkbox', name='Select Summary', exact=True)).to_be_checked()
    await page.get_by_role('button', name='Review complete content', exact=True).click()
    projection = page.get_by_role('region', name='Complete content preview')
    expected_summary = ('This summary must remain unselected in the reject-all journey.' if selected
                        else 'Engineer who helped maintain reliable systems.')
    await expect(projection).to_contain_text(expected_summary)
    if not selected:
        await expect(projection).not_to_contain_text('This summary must remain unselected')
    await page.get_by_role('button', name='Confirm this content', exact=True).click()
    await expect(page.get_by_role('button', name='Approve and release PDF', exact=True)).to_be_visible(timeout=30000)
    async with httpx.AsyncClient(base_url=base) as client:
        paused = (await client.get(f'/api/runs/{run_id}')).json()
        assert paused['pending']['kind'] == 'review_pdf'
        preview = await client.get(f'/api/runs/{run_id}/preview')
        assert preview.status_code == 200
        approved_hash = hashlib.sha256(preview.content).hexdigest()
        assert approved_hash == paused['pending']['review']['pdf_hash']
        assert (await client.get(f'/api/runs/{run_id}/pdf')).status_code in (404, 409)
    from resume_agent.checkpoint import read_v2_checkpoint
    from resume_agent.pdf_content_check import verify_pdf_content
    from resume_agent.schemas import RenderManifest
    saved = read_v2_checkpoint(real_server.root / 'state.sqlite', 'run', run_id)['values']
    record = saved['render_record']
    checked = verify_pdf_content(RenderManifest.model_validate(saved['manifest']), record['pdf_path'])
    assert checked.ok and 1 <= checked.page_count <= 2
    assert not record['overflow'] and record['overfull_boxes'] == []
    assert len(record['image_paths']) == checked.page_count
    # Real stale/hash-replaced PDF attempts must fail before recording a command.
    review = paused['pending']['review']
    approval = {'kind': 'review_pdf', 'decision': 'approve', 'action_id': 'blocked-approval',
                **{key: review[key] for key in ('review_id', 'content_hash', 'render_hash', 'pdf_hash')}}
    pdf = next((real_server.root / 'runs').rglob('resume.pdf'))
    async with httpx.AsyncClient(base_url=base) as client:
        stale = await client.post(f'/api/runs/{run_id}/resume', json=approval | {'review_id': str(uuid4())})
        assert stale.status_code == 409
        pdf.write_bytes(b'replaced canonical PDF bytes')
        try:
            assert (await client.get(f'/api/runs/{run_id}/preview')).status_code == 409
            assert (await client.post(f'/api/runs/{run_id}/resume', json=approval)).status_code == 409
            with sqlite3.connect(real_server.root / 'library.sqlite') as connection:
                assert connection.execute('SELECT count(*) FROM actions WHERE action_id=?',
                                          ('blocked-approval',)).fetchone()[0] == 0
        finally:
            pdf.write_bytes(preview.content)
    await real_server.restart()
    await page.reload(wait_until='domcontentloaded')
    await open_saved_run(page)
    await expect(page.get_by_role('button', name='Approve and release PDF', exact=True)).to_be_visible()
    evidence = Path(os.getenv('RESUME_EVIDENCE_DIR', str(tmp_path / 'evidence')))
    evidence.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(evidence / f'real-pdf-review-{selected}.png'), full_page=True)
    shutil.copytree(real_server.root / 'runs' / paused['artifact_id'],
                    evidence / f'real-artifacts-{selected}', dirs_exist_ok=True)
    (evidence / f'real-pdf-record-{selected}.json').write_text(json.dumps(record, indent=2))
    async with page.expect_request(lambda request: request.url.endswith(f'/runs/{run_id}/resume')
                                  and request.method == 'POST') as sent:
        await page.get_by_role('button', name='Approve and release PDF', exact=True).click()
    action = (await sent.value).post_data_json
    await expect(page.get_by_role('button', name='Download PDF', exact=True)).to_be_visible(timeout=15000)
    async with httpx.AsyncClient(base_url=base) as client:
        result = (await client.get(f'/api/runs/{run_id}')).json()
        final = await client.get(f'/api/runs/{run_id}/pdf')
        assert result['status'] == 'complete' and result['release']['status'] == 'released'
        assert hashlib.sha256(final.content).hexdigest() == approved_hash
        assert final.content == preview.content
        replay = await client.post(f'/api/runs/{run_id}/resume', json=action, timeout=15)
        assert replay.status_code == 200 and replay.json()['release'] == result['release']
    assert len(list((real_server.root / 'output').glob('*/*.pdf'))) == 1
    Path(result['release']['destination']).unlink()
    await page.reload(wait_until='domcontentloaded')
    await page.get_by_role('button', name='Library', exact=True).click()
    await page.get_by_text('Example QA · Reliability Engineer', exact=True).first.click()
    await expect(page.get_by_role('button', name='Restore export copy', exact=True)).to_be_visible()
    async with page.expect_response(lambda response: response.url.endswith('/reexport')
                                    and response.request.method == 'POST') as exported:
        await page.get_by_role('button', name='Restore export copy', exact=True).click()
    assert (await exported.value).status == 200
    await expect(page.get_by_role('button', name='Download PDF', exact=True)).to_be_visible()
    restored = list((real_server.root / 'output').glob('*/*.pdf'))
    assert len(restored) == 1 and hashlib.sha256(restored[0].read_bytes()).hexdigest() == approved_hash
    stages = [json.loads(line)['stage'] for line in (real_server.root / 'model-calls.jsonl').read_text().splitlines()]
    assert stages == ['extract_jd', 'questions', 'proposals']
    assert any(f'/ws/runs/{run_id}' in url for url in sockets)
    (evidence / f'real-journey-{selected}.json').write_text(json.dumps({
        'run_id': run_id, 'selected': selected, 'pdf_hash': approved_hash,
        'page_count': checked.page_count, 'text_equal': checked.ok,
        'overflow': record['overflow'], 'model_stages': stages, 'real_sockets': sockets,
        'release': result['release']}, indent=2))


async def test_real_import_source_draft_restart_reject_and_accept(real_page, tmp_path, unused_tcp_port):
    server = LocalServer(tmp_path / 'import-state', unused_tcp_port, profile='old')
    await server.start()
    page = real_page
    source = ('Original source for Casey Example. Preserve every supplied word. ' * 500).encode()
    try:
        async with httpx.AsyncClient(base_url=server.url, timeout=30) as client:
            original = (await client.get('/api/profile')).json()
            assert original['profile']['personal']['full_name'] == 'Previous Candidate'
            for decision in ('reject', 'accept'):
                response = await client.post('/api/resume/upload', files={'file': ('original.tex', source)})
                assert response.status_code == 200
                operation = response.json()
                assert operation['status'] == 'pending_review'
                assert (await client.get('/api/profile')).json() == original
                source_response = await client.get(f"/api/profile/imports/{operation['id']}/source")
                assert source_response.content == source
                assert operation['source']['text'] == source.decode()
                await server.restart()
                await page.goto(server.url, wait_until='domcontentloaded')
                await page.evaluate('(id) => localStorage.setItem("rg.activeImport", id)', operation['id'])
                await page.reload(wait_until='domcontentloaded')
                await expect(page.get_by_role('heading', name='Review imported resume', exact=True)).to_be_visible()
                await expect(page.get_by_text('Parsed profile draft', exact=True)).to_be_visible()
                await expect(page.locator('.resume-dialog .profile-facts').first).to_contain_text('Casey Example')
                assert (await client.get('/api/profile')).json() == original
                name = 'Reject import' if decision == 'reject' else 'Accept reviewed import'
                async with page.expect_response(lambda response: response.url.endswith('/' + decision)
                                                and response.request.method == 'POST') as decided:
                    await page.get_by_role('button', name=name, exact=True).click()
                assert (await decided.value).status == 200
                profile = (await client.get('/api/profile')).json()
                if decision == 'reject':
                    assert profile == original
                else:
                    assert profile['profile']['personal']['full_name'] == 'Casey Example'
                    assert profile['review_required'] is False
            assert [json.loads(line)['stage'] for line in
                    (server.root / 'model-calls.jsonl').read_text().splitlines()] == ['import_profile'] * 2
    finally:
        server.stop()

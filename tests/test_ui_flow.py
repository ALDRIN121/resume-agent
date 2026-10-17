"""Browser regression checks. Run with RESUME_UI_TEST_URL=http://127.0.0.1:5173 pytest tests/test_ui_flow.py.

API and event fixtures keep these checks independent of credentials and personal data.
Set PLAYWRIGHT_CHROMIUM_EXECUTABLE when using an existing Chromium installation.
"""
import asyncio
import json
import os
import re

import pytest
from playwright.async_api import async_playwright, expect

pytestmark = pytest.mark.skipif(not os.getenv('RESUME_UI_TEST_URL'), reason='UI preview URL not set')

RESUME = {
    'personal': {'full_name': 'Test User', 'email': 'test@example.com'},
    'summary': 'Engineer', 'experience': [], 'education': [],
    'projects': [{'name': 'Search tool', 'description': 'A search application', 'url': 'https://example.com', 'tech': ['Python'], 'bullets': ['Built search']}],
    'skills': {'Languages': ['Python']},
}
SETTINGS = {'provider': 'commandcode', 'providerId': 'commandcode', 'providerName': 'Command Code',
            'defaultModel': 'test-model', 'status': 'connected', 'visionEnabled': False,
            'generatorMax': 5, 'uiTheme': 'light', 'uiAccent': 'graphite', 'uiDensity': 'comfortable'}


@pytest.fixture
async def browser_page():
    async with async_playwright() as p:
        options = {'headless': True}
        if os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE'):
            options['executable_path'] = os.environ['PLAYWRIGHT_CHROMIUM_EXECUTABLE']
        browser = await p.chromium.launch(**options)
        page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            yield page
            assert errors == []
        finally:
            await browser.close()


async def prepare(page, status='awaiting-input', resume_error=False):
    saved = []
    events = [{'type': 'node_start', 'node_id': 'hitl_ask_missing'},
              {'type': 'hitl_pending', 'kind': 'ask_missing',
               'questions': [{'id': 'q1', 'prompt': 'Have you used Go?', 'why_asking': 'Required skill'}]}]
    if status == 'complete':
        events = [{'type': 'complete', 'pdf_url': '/api/runs/test-run/pdf', 'duration_s': 12}]
    elif status == 'failed':
        events = [{'type': 'failed', 'reason': 'Provider unavailable'}]
    run = {'id': 'test-run', 'thread_id': 'test-run', 'company': 'QA Company', 'role': 'Test Engineer',
           'status': status, 'created_at': 1792231186, 'duration': '12s', 'retries': 0,
           'pdf_url': '/api/runs/test-run/pdf' if status == 'complete' else None, 'events': events}

    async def api(route):
        path = route.request.url.split('/api/', 1)[1].split('?')[0]
        method = route.request.method
        code = 200
        if path == 'resume':
            if method == 'PUT':
                saved.append(route.request.post_data_json)
                body = saved[-1]
            else:
                body = saved[-1] if saved else RESUME
        elif path == 'settings/doctor':
            body = {'ok': True, 'checks': []}
        elif path == 'settings/providers':
            body = {'providers': [{'id': 'commandcode', 'name': 'Command Code', 'sub': 'API access · commandcode.ai/studio/api-keys', 'logo': 'C', 'needsKey': True}], 'models': {'commandcode': ['test-model']}, 'visionModels': {}}
        elif path == 'settings/detect':
            body = {'detected': []}
        elif path == 'settings':
            body = SETTINGS
        elif path in ['runs', 'library/resumes']:
            body = [run]
        elif path == 'library/companies':
            body = [{'name': 'QA Company', 'count': 1}]
        elif path.endswith('/resume'):
            code = 409 if resume_error else 200
            body = {'detail': 'Connection interrupted. Try again.'} if resume_error else run
        elif path.startswith('runs/test-run'):
            body = run
        else:
            body = {}
        await route.fulfill(status=code, content_type='application/json', body=json.dumps(body))

    await page.context.route(re.compile(r'^http://[^/]+/api/'), api)
    async def socket(ws):
        for event in events:
            ws.send(json.dumps(event))
    await page.route_web_socket('**/ws/**', socket)
    await page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
    await page.goto(os.environ['RESUME_UI_TEST_URL'], wait_until='domcontentloaded')
    return saved


async def open_run(page):
    await page.get_by_role('button', name='Library', exact=True).click()
    await page.get_by_text('QA Company — Test Engineer', exact=True).first.click()


async def test_skill_edits_are_saved(browser_page):
    page = browser_page
    saved = await prepare(page)
    await page.get_by_role('button', name='Base resume', exact=True).click()
    skill = page.get_by_placeholder('Type to add…').first
    await skill.fill('Go')
    await skill.press('Enter')
    await expect(page.get_by_role('button', name='Save', exact=True)).to_be_enabled()
    await page.get_by_role('button', name='Save', exact=True).click()
    await expect(page.get_by_text('All changes saved', exact=True)).to_be_visible()
    assert saved[-1]['skills']['Languages'] == ['Python', 'Go']
    await page.get_by_role('button', name='Remove Go', exact=True).click()
    await page.get_by_role('button', name='Save', exact=True).click()
    await expect(page.get_by_text('All changes saved', exact=True)).to_be_visible()
    assert saved[-1]['skills']['Languages'] == ['Python']


async def test_project_edits_are_saved(browser_page):
    page = browser_page
    saved = await prepare(page)
    await page.get_by_role('button', name='Base resume', exact=True).click()
    await page.get_by_role('textbox', name='Project name').fill('Updated search')
    await page.get_by_role('button', name='Save', exact=True).click()
    await expect(page.get_by_text('All changes saved', exact=True)).to_be_visible()
    assert saved[-1]['projects'][0]['name'] == 'Updated search'
    assert saved[-1]['projects'][0]['bullets'] == ['Built search']


async def test_failed_answers_remain_retryable(browser_page):
    page = browser_page
    await prepare(page, resume_error=True)
    await open_run(page)
    await page.get_by_placeholder('Your answer…').fill('Used Go on internal tools')
    await page.get_by_role('button', name='Submit answers', exact=True).click()
    await expect(page.get_by_role('alert')).to_contain_text('Connection interrupted')
    await expect(page.get_by_placeholder('Your answer…')).to_have_value('Used Go on internal tools')
    await expect(page.get_by_role('button', name='Submit answers', exact=True)).to_be_enabled()


async def test_completed_run_navigation(browser_page):
    page = browser_page
    await prepare(page, status='complete')
    await open_run(page)
    await page.get_by_role('button', name='New run', exact=True).click()
    await expect(page.get_by_placeholder('Paste the full job description here…')).to_be_visible()


@pytest.mark.parametrize('width', [320, 390, 768, 1024, 1440])
async def test_editor_toolbar_fits_viewport(browser_page, width):
    page = browser_page
    await prepare(page)
    await page.get_by_role('button', name='Base resume', exact=True).click()
    await page.set_viewport_size({'width': width, 'height': 900})
    save = page.get_by_role('button', name='Save', exact=True)
    await expect(save).to_be_visible()
    box = await save.bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= width
    assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('route_name', ['Create resume', 'Library', 'Companies', 'Settings', 'Doctor & setup'])
async def test_phone_pages_fit_content_area(browser_page, route_name):
    page = browser_page
    await prepare(page)
    await page.get_by_role('button', name=route_name, exact=True).click()
    await page.set_viewport_size({'width': 320, 'height': 844})
    await page.wait_for_timeout(250)
    content = page.locator('.route-in').first
    assert await content.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')


async def test_upload_parse_completion(browser_page):
    page = browser_page
    await prepare(page)
    async def upload(route):
        await route.fulfill(content_type='application/json', body=json.dumps({'job_id': 'parse-test'}))
    await page.route('**/api/resume/upload', upload)
    parse_sockets = []
    async def parse_socket(ws):
        parse_sockets.append(ws)
        for stage in ['upload', 'extract', 'write_yaml']:
            ws.send(json.dumps({'type': 'resume_parse', 'stage_id': stage, 'status': 'done'}))
    await page.route_web_socket('**/ws/resume-parse/*', parse_socket)
    await page.get_by_role('button', name='Base resume', exact=True).click()
    await page.get_by_role('button', name='Replace', exact=True).click()
    await page.locator('input[type=file]').set_input_files({'name': 'sample.tex', 'mimeType': 'text/plain', 'buffer': b'\\documentclass{article}\\begin{document}Test User\\end{document}'})
    await expect(page.get_by_text('Base resume parsed', exact=True)).to_be_visible()
    await parse_sockets[-1].close()
    await expect(page.get_by_text('Base resume parsed', exact=True)).to_be_visible()


async def test_resume_upload_can_be_minimized_reopened_and_replaced_again(browser_page):
    page = browser_page
    await prepare(page)
    hook_errors = []
    page.on('console', lambda msg: hook_errors.append(msg.text)
            if msg.type == 'error' and ('React' in msg.text or 'hook' in msg.text.lower()) else None)
    await page.route('**/api/resume/upload', lambda route: route.fulfill(
        content_type='application/json', body=json.dumps({'job_id': 'parse-lifecycle'})))
    sockets = []
    def parse_socket(ws):
        sockets.append(ws)
        ws.send(json.dumps({'type': 'resume_parse', 'stage_id': 'upload', 'status': 'done'}))
        ws.send(json.dumps({'type': 'resume_parse', 'stage_id': 'extract', 'status': 'running'}))
    await page.route_web_socket('**/ws/resume-parse/*', parse_socket)
    await page.get_by_role('button', name='Base resume', exact=True).click()
    for attempt in range(2):
        await page.get_by_role('button', name='Replace', exact=True).click()
        await page.locator('input[type=file]').set_input_files({
            'name': 'new.tex', 'mimeType': 'text/plain', 'buffer': b'New resume'})
        await expect(page.get_by_text('Parsing your base resume', exact=True)).to_be_visible()
        assert hook_errors == []
        await expect(page.get_by_role('button', name='Replace', exact=True)).to_be_disabled()
        await page.get_by_role('button', name='Minimize', exact=True).last.click()
        await expect(page.get_by_role('dialog')).to_have_count(0)
        await page.get_by_role('button', name=re.compile('Parsing your base resume')).click()
        await expect(page.get_by_role('dialog')).to_be_visible()
        await page.get_by_role('button', name='Minimize', exact=True).last.click()
        replacement = {**RESUME, 'personal': {'full_name': f'New Owner {attempt}', 'email': 'new@example.com'}}
        await page.route('**/api/resume', lambda route: route.fulfill(
            content_type='application/json', body=json.dumps(replacement)))
        sockets[-1].send(json.dumps({'type': 'resume_parse', 'stage_id': 'write_yaml', 'status': 'done'}))
        await expect(page.get_by_text('Base resume parsed', exact=True)).to_be_visible()
        await page.get_by_role('button', name='Done', exact=True).click()
        await expect(page.get_by_role('dialog')).to_have_count(0)
        await expect(page.locator('#sec-profile input').first).to_have_value(f'New Owner {attempt}')
    assert hook_errors == []


@pytest.mark.parametrize('failure', ['parse', 'disconnect', 'upload'])
async def test_minimized_resume_failure_is_visible_and_can_be_retried(browser_page, failure):
    page = browser_page
    await prepare(page)
    finish_upload = asyncio.Event()
    async def upload(route):
        if failure == 'upload':
            await finish_upload.wait()
            await route.fulfill(status=400, content_type='application/json',
                                body=json.dumps({'detail': 'Only .pdf and .tex resumes are supported.'}))
        else:
            await route.fulfill(content_type='application/json', body=json.dumps({'job_id': 'failed-parse'}))
    await page.route('**/api/resume/upload', upload)
    sockets = []
    def parse_socket(ws):
        sockets.append(ws)
        ws.send(json.dumps({'type': 'resume_parse', 'stage_id': 'extract', 'status': 'running'}))
    await page.route_web_socket('**/ws/resume-parse/*', parse_socket)
    await page.get_by_role('button', name='Base resume', exact=True).click()
    await page.get_by_role('button', name='Replace', exact=True).click()
    await page.locator('input[type=file]').set_input_files({
        'name': 'retry.tex', 'mimeType': 'text/plain', 'buffer': b'Resume'})
    await page.get_by_role('button', name='Minimize', exact=True).last.click()
    if failure == 'upload':
        finish_upload.set()
    elif failure == 'parse':
        await expect(page.get_by_role('button', name=re.compile('Read document'))).to_be_visible()
        sockets[-1].send(json.dumps({'type': 'resume_parse', 'stage_id': 'failed',
                                    'status': 'failed', 'detail': 'Could not extract text from the file.'}))
    else:
        await expect(page.get_by_role('button', name=re.compile('Read document'))).to_be_visible()
        await sockets[-1].close()
    await expect(page.get_by_text('Resume parsing failed', exact=True)).to_be_visible()
    await expect(page.locator('.editor-toolbar').get_by_text('Parsing', exact=True)).to_have_count(0)
    await expect(page.get_by_role('alert')).to_contain_text({
        'upload': 'Only .pdf and .tex', 'parse': 'Could not extract text',
        'disconnect': 'connection closed',
    }[failure])
    await page.get_by_role('dialog').get_by_role('button', name='Close', exact=True).last.click()
    await expect(page.locator('#sec-profile input').first).to_have_value('Test User')
    await page.get_by_role('button', name='Replace', exact=True).click()
    await expect(page.locator('input[type=file]')).to_have_count(1)


@pytest.mark.parametrize('width,height', [(1440, 900), (320, 568), (730, 400)])
async def test_resume_flow_shows_current_step_and_fits_window(browser_page, width, height):
    page = browser_page
    await prepare(page)
    await page.get_by_role('button', name='Base resume', exact=True).click()
    await page.set_viewport_size({'width': width, 'height': height})
    await page.get_by_role('button', name='Replace', exact=True).click()
    dialog = page.get_by_role('dialog', name='Replace base resume')
    await expect(dialog).to_be_visible()
    picker = page.get_by_role('button', name='Choose a resume file', exact=True)
    await picker.focus()
    async with page.expect_file_chooser() as chooser:
        await page.keyboard.press('Enter')
    await page.route('**/api/resume/upload', lambda route: route.fulfill(
        content_type='application/json', body=json.dumps({'job_id': 'progress-ui'})))
    sockets = []
    def socket(ws):
        sockets.append(ws)
        ws.send(json.dumps({'stage_id': 'upload', 'status': 'done'}))
        ws.send(json.dumps({'stage_id': 'extract', 'status': 'running'}))
    await page.route_web_socket('**/ws/resume-parse/*', socket)
    await (await chooser.value).set_files({
        'name': 'A-very-long-resume-filename-for-small-windows-2026.pdf',
        'mimeType': 'application/pdf', 'buffer': b'%PDF-1.4',
    })
    dialog = page.get_by_role('dialog', name='Parsing your base resume')
    await expect(dialog).to_be_visible()
    phases = page.get_by_role('list', name='Resume import progress')
    await expect(phases.locator('[aria-current=step] strong')).to_have_text('Read document')
    sockets[-1].send(json.dumps({'stage_id': 'extract', 'status': 'done'}))
    sockets[-1].send(json.dumps({'stage_id': 'parse', 'status': 'running'}))
    await expect(phases.locator('[aria-current=step] strong')).to_have_text('Understand resume')
    await expect(phases.locator('.resume-step-detail')).to_have_count(1)
    assert await dialog.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
    box = await dialog.bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= width
    assert box['y'] >= 0 and box['y'] + box['height'] <= height
    await page.get_by_role('button', name='Minimize', exact=True).last.click()
    banner = page.get_by_role('button', name=re.compile('Parsing your base resume'))
    await expect(banner).to_be_visible()
    assert await banner.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
    await banner.click()
    sockets[-1].send(json.dumps({'stage_id': 'parse', 'status': 'failed', 'detail': 'Please try another file.'}))
    await expect(page.get_by_role('alert')).to_contain_text('Please try another file.')
    await page.get_by_role('button', name='Choose another file', exact=True).click()
    await expect(page.get_by_role('dialog', name='Replace base resume')).to_be_visible()


async def test_resume_dialog_keeps_keyboard_focus_and_restores_trigger(browser_page):
    page = browser_page
    await prepare(page)
    await page.get_by_role('button', name='Base resume', exact=True).click()
    trigger = page.get_by_role('button', name='Replace', exact=True)
    await trigger.click()
    dialog = page.get_by_role('dialog', name='Replace base resume')
    await page.keyboard.press('Shift+Tab')
    await expect(dialog.get_by_role('button', name='Cancel', exact=True)).to_be_focused()
    await page.keyboard.press('Tab')
    await expect(dialog.get_by_role('button', name='Close', exact=True)).to_be_focused()
    await page.keyboard.press('Escape')
    await expect(dialog).to_have_count(0)
    await expect(trigger).to_be_focused()


async def test_first_resume_import_cannot_overlap_another_upload(browser_page):
    page = browser_page
    await prepare(page)
    await page.route('**/api/resume', lambda route: route.fulfill(
        status=404, content_type='application/json', body='{"detail":"No base resume"}'))
    await page.route('**/api/resume/upload', lambda route: route.fulfill(
        content_type='application/json', body='{"job_id":"first-import"}'))
    await page.route_web_socket('**/ws/resume-parse/*', lambda ws: ws.send(
        json.dumps({'stage_id': 'parse', 'status': 'running'})))
    await page.get_by_role('button', name='Base resume', exact=True).click()
    upload = page.get_by_role('button', name='Upload base resume', exact=True)
    await upload.click()
    await page.locator('input[type=file]').set_input_files({
        'name': 'first.tex', 'mimeType': 'text/plain', 'buffer': b'Resume'})
    await page.get_by_role('button', name='Minimize', exact=True).last.click()
    await expect(upload).to_be_disabled()


async def test_candidate_location_preferences_save_without_changing_home(browser_page):
    page = browser_page
    saved = await prepare(page)
    await page.get_by_role('button', name='Base resume', exact=True).click()
    await page.get_by_label('Preferred locations', exact=True).fill('Bengaluru, India\nLondon, UK')
    await page.get_by_role('checkbox', name='Remote', exact=True).check()
    await page.get_by_role('checkbox', name='Hybrid', exact=True).check()
    await page.get_by_role('button', name='Save', exact=True).click()
    await expect(page.get_by_text('Saved', exact=True)).to_be_visible()
    assert saved[-1]['work_preferences'] == {
        'preferred_locations': ['Bengaluru, India', 'London, UK'], 'work_modes': ['Remote', 'Hybrid'],
    }
    assert saved[-1]['personal'].get('location') is None
    await page.get_by_role('button', name='Library', exact=True).click()
    await page.get_by_role('button', name='Base resume', exact=True).click()
    await expect(page.get_by_label('Preferred locations', exact=True)).to_have_value('Bengaluru, India\nLondon, UK')
    await expect(page.get_by_role('checkbox', name='Remote', exact=True)).to_be_checked()


@pytest.mark.parametrize('input_kind', ['text', 'url', 'file'])
async def test_job_context_is_sent_for_every_posting_input(browser_page, input_kind):
    page = browser_page
    await prepare(page)
    posted = []
    async def start(route):
        posted.append(route.request.post_data_json)
        await route.fulfill(content_type='application/json', body='{"thread_id":"test-run"}')
    await page.route('**/api/runs', start)
    await page.get_by_role('button', name='Create resume', exact=True).click()
    await page.get_by_label('Job location', exact=True).fill('Pune, India')
    await page.get_by_label('Work mode', exact=True).select_option('Hybrid')
    if input_kind == 'text':
        await page.get_by_placeholder('Paste the full job description here…').fill('Engineer at Example. Python skills required.')
    elif input_kind == 'url':
        await page.get_by_role('button', name='From URL', exact=True).click()
        await page.get_by_placeholder('https://jobs.example.com/staff-engineer').fill('https://example.com/jobs/1')
    else:
        await page.get_by_role('button', name='Upload file', exact=True).click()
        await page.route('**/api/runs/jd-file', lambda route: route.fulfill(
            content_type='application/json', body='{"file_id":"test-file"}'))
        await page.locator('input[type=file]').set_input_files({
            'name': 'job.pdf', 'mimeType': 'application/pdf', 'buffer': b'PDF'})
    await page.get_by_role('button', name='Generate tailored resume', exact=True).click()
    await expect(page.locator('.live-run')).to_be_visible()
    assert posted[-1]['job_location'] == 'Pune, India'
    assert posted[-1]['work_mode'] == 'Hybrid'


async def test_work_context_is_visible_in_run_details_on_phone(browser_page):
    page = browser_page
    await prepare(page)
    detail = {'thread_id': 'test-run', 'company': 'Example', 'role': 'Engineer', 'status': 'failed',
              'location': 'London, UK', 'work_mode': 'On-site',
              'remote_policy': 'UK only; three office days per week',
              'work_preferences': {'preferred_locations': ['Bengaluru, India'], 'work_modes': ['Remote']}}
    await page.route('**/api/runs/test-run', lambda route: route.fulfill(
        content_type='application/json', body=json.dumps(detail)))
    await open_run(page)
    await page.set_viewport_size({'width': 390, 'height': 844})
    await page.get_by_role('tab', name='Details', exact=True).click()
    context = page.get_by_role('region', name='Location and work mode')
    await expect(context.get_by_text('London, UK', exact=True)).to_be_visible()
    await expect(context.get_by_text('On-site', exact=True)).to_be_visible()
    await expect(context.get_by_text('Bengaluru, India', exact=True)).to_be_visible()
    await expect(context.get_by_text('Remote', exact=True)).to_be_visible()
    await expect(context.get_by_text('UK only; three office days per week', exact=True)).to_be_visible()
    assert await context.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')


async def test_failed_run_actions(browser_page):
    page = browser_page
    await prepare(page, status='failed')
    await open_run(page)
    await expect(page.get_by_text('Provider unavailable', exact=True)).to_be_visible()
    await page.get_by_role('button', name='Edit base resume', exact=True).click()
    await expect(page.get_by_role('button', name='Save', exact=True)).to_be_visible()


async def test_url_input_is_not_blocked_by_previous_long_paste(browser_page):
    page = browser_page
    await prepare(page)
    await page.get_by_role('button', name='Create resume', exact=True).click()
    await page.get_by_placeholder('Paste the full job description here…').fill('Job details ' * 800)
    await expect(page.get_by_role('button', name='Generate tailored resume', exact=True)).to_be_disabled()
    await page.get_by_role('button', name='From URL', exact=True).click()
    await page.get_by_placeholder('https://jobs.example.com/staff-engineer').fill('https://example.com/job')
    await expect(page.get_by_role('button', name='Generate tailored resume', exact=True)).to_be_enabled()


async def test_answer_response_does_not_hide_next_review(browser_page):
    page = browser_page
    await prepare(page)
    sockets = []
    def socket(ws):
        sockets.append(ws)
        ws.send(json.dumps({'type': 'hitl_pending', 'kind': 'ask_missing',
                            'questions': [{'id': 'q1', 'prompt': 'Used Go?'}]}))
    await page.route_web_socket('**/ws/runs/*', socket)
    async def resume(route):
        sockets[-1].send(json.dumps({'type': 'hitl_pending', 'kind': 'present_suggestions',
                                     'suggestions': [{'id': 's1', 'before': 'Built APIs', 'after': 'Built Python APIs'}]}))
        await asyncio.sleep(0.1)
        await route.fulfill(content_type='application/json', body='{}')
    await page.route('**/api/runs/*/resume', resume)
    await open_run(page)
    await page.get_by_role('button', name='Skip all', exact=True).click()
    await expect(page.get_by_text('Suggested rewrites', exact=True)).to_be_visible()
    await expect(page.get_by_role('button', name='Continue', exact=True)).to_be_enabled()


async def test_review_draft_survives_reconnection(browser_page):
    page = browser_page
    await prepare(page)
    sockets = []
    def socket(ws):
        sockets.append(ws)
        ws.send(json.dumps({'type': 'hitl_pending', 'ts': '2026-10-17T14:00:00Z', 'kind': 'ask_missing',
                            'questions': [{'id': 'q1', 'prompt': 'Used Go?'}]}))
    await page.route_web_socket('**/ws/runs/*', socket)
    await open_run(page)
    await page.get_by_placeholder('Your answer…').fill('My unsent answer')
    await sockets[-1].close()
    await page.wait_for_timeout(800)
    assert len(sockets) >= 2
    await expect(page.get_by_placeholder('Your answer…')).to_have_value('My unsent answer')


async def test_completed_run_downloads_without_opening_tab(browser_page):
    page = browser_page
    await prepare(page, status='complete')
    await open_run(page)
    async with page.expect_download(timeout=3000) as download:
        await page.get_by_role('button', name='Download PDF', exact=True).click()
    assert (await download.value).url.endswith('/api/runs/test-run/pdf')
    assert len(page.context.pages) == 1


async def test_editor_secondary_action_becomes_accessible_icon(browser_page):
    page = browser_page
    await prepare(page)
    await page.get_by_role('button', name='Base resume', exact=True).click()
    replace = page.get_by_role('button', name='Replace', exact=True)
    await expect(replace.locator('.button-label')).to_be_visible()
    await page.set_viewport_size({'width': 390, 'height': 844})
    await expect(replace.locator('.button-label')).to_be_hidden()
    assert (await replace.bounding_box())['width'] <= 48
    await replace.click()
    await expect(page.locator('input[type=file]')).to_have_count(1)


async def test_sidebar_adapts_to_desktop_tablet_and_phone(browser_page):
    page = browser_page
    await prepare(page)
    sidebar = page.locator('.app-sidebar')
    await page.set_viewport_size({'width': 1024, 'height': 900})
    await expect(sidebar).to_have_css('width', '60px')
    await page.get_by_role('button', name='Library', exact=True).click()
    await page.set_viewport_size({'width': 390, 'height': 844})
    await page.get_by_role('button', name='Open navigation', exact=True).click()
    await expect(sidebar).to_have_css('width', '236px')
    await page.get_by_role('button', name='Base resume', exact=True).click()
    await expect(sidebar).not_to_have_class('app-sidebar open')


async def test_dashboard_tabs_fit_and_remain_named_on_phone(browser_page):
    page = browser_page
    await prepare(page)
    await page.set_viewport_size({'width': 320, 'height': 844})
    tabs = page.get_by_role('tablist', name='Overview sections')
    assert await tabs.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
    await page.get_by_role('tab', name='Companies', exact=True).click()
    await expect(page.get_by_role('tab', name='Companies', exact=True)).to_have_attribute('aria-selected', 'true')


async def test_phone_run_has_switchable_activity_progress_and_details(browser_page):
    page = browser_page
    await prepare(page)
    await open_run(page)
    await page.set_viewport_size({'width': 390, 'height': 844})
    await expect(page.get_by_placeholder('Your answer…')).to_be_visible()
    await page.get_by_role('tab', name='Progress', exact=True).click()
    await expect(page.get_by_placeholder('Your answer…')).to_be_hidden()
    await expect(page.get_by_role('tabpanel', name='Progress')).to_be_visible()
    await page.get_by_role('tab', name='Activity', exact=True).click()
    await expect(page.get_by_placeholder('Your answer…')).to_be_visible()


async def test_library_adapts_company_filter_and_ledger_on_phone(browser_page):
    page = browser_page
    await prepare(page)
    await page.get_by_role('button', name='Library', exact=True).click()
    await page.get_by_role('button', name='Ledger', exact=True).click()
    await page.set_viewport_size({'width': 390, 'height': 844})
    await expect(page.get_by_role('combobox', name='Filter by company')).to_be_visible()
    await expect(page.get_by_role('button', name='Ledger', exact=True).locator('.view-label')).to_be_hidden()
    ledger = page.locator('.ledger-table')
    assert await ledger.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')


async def test_progress_advances_one_phase_at_a_time(browser_page):
    page = browser_page
    await prepare(page)
    sockets = []
    def socket(ws):
        sockets.append(ws)
        ws.send(json.dumps({'type': 'node_start', 'node_id': 'analyze_gaps'}))
    await page.route_web_socket('**/ws/runs/*', socket)
    await open_run(page)
    await page.set_viewport_size({'width': 730, 'height': 635})
    await page.get_by_role('tab', name='Progress', exact=True).click()
    phases = page.get_by_role('list', name='Generation phases')
    await expect(phases.locator(':scope > li')).to_have_count(5)
    await expect(phases.locator('.is-current .phase-description strong')).to_have_text('Compare experience')
    await expect(phases.locator('.phase-header[aria-expanded=true]')).to_have_count(1)
    sockets[-1].send(json.dumps({'type': 'node_end', 'node_id': 'analyze_gaps', 'duration_ms': 4200}))
    sockets[-1].send(json.dumps({'type': 'node_start', 'node_id': 'hitl_ask_missing'}))
    await expect(phases.locator('.is-current .phase-description strong')).to_have_text('Review together')
    await expect(phases.locator('.is-complete')).to_have_count(2)
    await expect(phases.locator('.phase-header[aria-expanded=true]')).to_have_count(1)


async def test_saved_run_does_not_invent_step_timings(browser_page):
    page = browser_page
    await prepare(page, status='complete')
    await open_run(page)
    await expect(page.get_by_text('This saved run has no detailed step history. Its PDF is ready to download.', exact=True)).to_be_visible()
    await expect(page.get_by_text('320ms', exact=True)).to_have_count(0)


async def test_route_change_starts_at_top_in_short_window(browser_page):
    page = browser_page
    await prepare(page)
    await page.set_viewport_size({'width': 1440, 'height': 500})
    await page.locator('.workspace-view').evaluate('(e) => { e.parentElement.scrollTop = 300; }')
    assert await page.locator('.workspace-view').evaluate('(e) => e.parentElement.scrollTop') > 0
    await page.get_by_role('button', name='Base resume', exact=True).click()
    assert await page.locator('.workspace-view').evaluate('(e) => e.parentElement.scrollTop') == 0


async def test_compile_failure_stays_in_pdf_phase(browser_page):
    page = browser_page
    await prepare(page, status='failed')
    def socket(ws):
        for event in [{'type': 'node_start', 'node_id': 'compile_pdf'},
                      {'type': 'node_end', 'node_id': 'compile_pdf', 'duration_ms': 100},
                      {'type': 'failed', 'reason': 'Could not compile PDF'}]:
            ws.send(json.dumps(event))
    await page.route_web_socket('**/ws/runs/*', socket)
    await open_run(page)
    await expect(page.locator('.pipeline-phase.is-current .phase-description strong')).to_have_text('Create the PDF')
    await expect(page.locator('.pipeline-phase.is-current .phase-description > span')).to_have_text('Failed')

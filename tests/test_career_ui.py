"""Actual backend/browser career decisions with only model output substituted."""
import os
from pathlib import Path

import httpx
import pytest
from playwright.async_api import expect

from tests.test_reliability_journey import real_page,real_server  # noqa: F401

pytestmark=pytest.mark.skipif(os.getenv('RESUME_REAL_BROWSER_TEST')!='1',reason='Real browser acceptance flag not set')


@pytest.mark.parametrize('case,recommendation,override',[
    ('CASE_PRIORITY','prioritize',False),('CASE_UNKNOWN','review',True),('CASE_INELIGIBLE','skip',True),
])
async def test_role_decision_preserves_sources_and_explicit_generation_override(real_page,real_server,case,recommendation,override):
    page=real_page
    text=f'Python required. No visa sponsorship. {case}'
    await page.goto(real_server.url,wait_until='domcontentloaded')
    await page.get_by_role('button',name='Jobs',exact=True).click()
    await page.get_by_label('Full job description',exact=True).fill(text)
    await page.get_by_label('Company',exact=True).fill('Example Career')
    await page.get_by_label('Role',exact=True).fill('Engineer')
    await page.get_by_role('button',name='Save role',exact=True).click()
    await expect(page.get_by_role('heading',name='Saved role',exact=True)).to_be_visible()
    assert not (real_server.root/'model-calls.jsonl').exists()
    if case=='CASE_INELIGIBLE':
        await page.get_by_label('Work authorization statement',exact=True).fill('I require visa sponsorship.')
    await page.get_by_role('button',name='Evaluate role',exact=True).click()
    await expect(page.get_by_test_id('recommendation')).to_have_text(recommendation)
    await expect(page.get_by_role('region',name='Requirement evidence')).to_contain_text('Python')
    await expect(page.get_by_text('Evidence coverage',exact=True)).to_be_visible()
    button=page.get_by_role('button',name='Generate from this role',exact=True)
    if override:
        await expect(button).to_be_disabled()
        await page.get_by_label('I reviewed this advice and want to generate anyway.',exact=True).check()
    if output:=os.getenv('RESUME_EVIDENCE_DIR'):
        destination=Path(output);destination.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(destination/f'career-{case}.png'),full_page=True)
    async with page.expect_response(lambda response:response.url.endswith('/api/runs') and response.request.method=='POST') as generated:
        await button.click()
    response=await generated.value
    assert response.status==200
    run=(await response.json())
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        detail=(await client.get('/api/runs/'+run['id'])).json()
        assert detail['job_id'] and detail['evaluation_id']
        assert detail['evaluation_override']==override
    from resume_agent.run_store import RunStore
    store=RunStore(real_server.root/'library.sqlite',real_server.root/'state.sqlite')
    assert store.input('run',run['id'])['request']['job_input']==text


async def test_changed_profile_marks_evaluation_stale_and_keeps_old_result(real_page,real_server):
    page=real_page
    await page.goto(real_server.url,wait_until='domcontentloaded')
    await page.get_by_role('button',name='Jobs',exact=True).click()
    await page.get_by_label('Full job description',exact=True).fill('Python required. CASE_PRIORITY')
    await page.get_by_role('button',name='Save role',exact=True).click()
    await page.get_by_role('button',name='Evaluate role',exact=True).click()
    await expect(page.get_by_test_id('recommendation')).to_have_text('prioritize')
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        profile=(await client.get('/api/profile')).json()
        changed=profile['profile']
        changed['summary']='A later reviewed profile edit.'
        response=await client.put('/api/resume',json=changed,headers={'If-Match':profile['revision']})
        assert response.status_code==200
    await page.get_by_role('button',name='Refresh evaluation',exact=True).click()
    await expect(page.get_by_text('Inputs changed: profile',exact=True)).to_be_visible()
    await expect(page.get_by_role('button',name='Generate from this role',exact=True)).to_be_disabled()


async def test_evaluation_inspection_remains_available_without_pdf_readiness(real_page,real_server):
    page=real_page
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        job=(await client.post('/api/jobs',json={'text':'Python CASE_PRIORITY','company':'Example','role':'Engineer'})).json()
        op=(await client.post(f"/api/jobs/{job['id']}/evaluations",json={})).json()
        assert (await client.post(f"/api/evaluations/{op['id']}/continue",json=None)).status_code==200
    await page.goto(real_server.url,wait_until='domcontentloaded')
    await page.evaluate('(id)=>localStorage.setItem("rg.selectedCareerJob",id)',job['id'])
    # Deliberately substitute only local tool-readiness display; all career operations stay real.
    await page.route('**/api/readiness',lambda route:route.fulfill(json={'generation_ready':False,
        'profile':{'status':'ready'},'provider':{'status':'configured_unverified'},'parser':{'status':'ready'},
        'compiler':{'status':'missing'},'renderer':{'status':'missing'},'next_steps':['Install PDF tools.']}))
    await page.get_by_role('button',name='Jobs',exact=True).click()
    await expect(page.get_by_role('button',name='Generate from this role',exact=True)).to_be_disabled()
    await expect(page.get_by_role('button',name='Refresh evaluation',exact=True)).to_be_enabled()
    await page.get_by_role('button',name='Example · Engineer',exact=True).click()
    await expect(page.get_by_role('button',name='Evaluate role',exact=True)).to_be_enabled()

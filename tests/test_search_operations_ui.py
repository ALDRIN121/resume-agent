import json
import os

import httpx
import pytest
from playwright.async_api import expect

from tests.test_discovery import greenhouse
from tests.test_reliability_journey import real_page,real_server  # noqa: F401

pytestmark=pytest.mark.skipif(os.getenv('RESUME_REAL_BROWSER_TEST')!='1',reason='Real browser acceptance flag not set')


async def test_manual_discovery_partial_failure_restart_and_exact_job_handoff(real_page,real_server):
    page=real_page
    feed=real_server.root/'discovery-feed.json'
    feed.write_text(json.dumps({'payload':{'jobs':[greenhouse(1,content='<p>Python required. CASE_PRIORITY</p>'),greenhouse(2)],'meta':{'total':2}}}))
    await page.goto(real_server.url,wait_until='domcontentloaded')
    await page.get_by_role('button',name='Discover',exact=True).click()
    await page.get_by_role('button',name='Add source',exact=True).click()
    await page.get_by_label('Board name 1',exact=True).fill('example')
    await page.get_by_label('Confirmed company 1',exact=True).fill('Search Example')
    await page.get_by_role('button',name='Save sources',exact=True).click()
    await expect(page.get_by_text('Source configuration saved.',exact=True)).to_be_visible()
    assert not (real_server.root/'model-calls.jsonl').exists()
    async with page.expect_response(lambda r:'/api/discovery/syncs/' in r.url and r.url.endswith('/continue')) as drove:
        await page.get_by_role('button',name='Refresh enabled sources',exact=True).click()
    driven=await drove.value
    assert driven.status==200,await driven.text()
    await expect(page.get_by_test_id('scan-status')).to_have_text('complete')
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        first=(await client.get('/api/discovery/postings')).json()['items']
        chosen=next(p for p in first if p['external_id']=='1')
        assert (await client.get('/api/metrics')).json()['applications']['submitted']==0
    feed.write_text(json.dumps({'payload':{'jobs':[greenhouse(1,content='<p>Python required. CASE_PRIORITY</p>'),{}],'meta':{'total':2}}}))
    await page.get_by_role('button',name='Refresh enabled sources',exact=True).click()
    await expect(page.get_by_test_id('scan-status')).to_have_text('partial')
    await expect(page.get_by_test_id('posting-2')).to_contain_text('stale')
    await expect(page.get_by_test_id('posting-2')).to_contain_text('active')
    feed.write_text(json.dumps({'status':503,'payload':{}}))
    await page.get_by_role('button',name='Refresh enabled sources',exact=True).click()
    await expect(page.get_by_test_id('scan-status')).to_have_text('failed')
    await real_server.restart()
    await page.reload(wait_until='domcontentloaded')
    await page.get_by_role('button',name='Discover',exact=True).click()
    await expect(page.get_by_test_id('scan-status')).to_have_text('failed')
    await expect(page.get_by_test_id('posting-1')).to_contain_text('stale')
    assert not (real_server.root/'model-calls.jsonl').exists()
    await page.get_by_test_id('posting-1').get_by_role('button',name='Review role',exact=True).click()
    await expect(page.get_by_role('heading',name='Saved role',exact=True)).to_be_visible()
    await expect(page.get_by_test_id('job-origin')).to_contain_text('greenhouse')
    await page.get_by_role('button',name='Evaluate role',exact=True).click()
    await expect(page.get_by_test_id('recommendation')).to_have_text('prioritize')
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        evaluations=(await client.get('/api/jobs/'+chosen['job_id']+'/evaluations')).json()
        assert len(evaluations)==1 and evaluations[0]['job_id']==chosen['job_id']
    async with page.expect_response(lambda r:r.url.endswith('/api/runs') and r.request.method=='POST') as generated:
        await page.get_by_role('button',name='Generate from this role',exact=True).click()
    run=(await (await generated.value).json())
    await page.get_by_role('textbox',name='What should remain unchanged?',exact=True).fill('Keep the original contribution scope.')
    await page.get_by_role('button',name='Submit answers',exact=True).click()
    await page.get_by_role('button',name='Review complete content',exact=True).click()
    await page.get_by_role('button',name='Confirm this content',exact=True).click()
    await expect(page.get_by_role('button',name='Approve and release PDF',exact=True)).to_be_visible(timeout=30000)
    async with page.expect_response(lambda r:r.url.endswith('/resume') and r.request.method=='POST') as approved:
        await page.get_by_role('button',name='Approve and release PDF',exact=True).click()
    assert (await approved.value).status==200
    await page.get_by_role('button',name='Applications',exact=True).click()
    await page.get_by_label('Application role',exact=True).select_option(chosen['job_id'])
    await page.get_by_role('button',name='Create application record',exact=True).click()
    await expect(page.get_by_test_id('application-stage')).to_have_text('planned')
    await page.get_by_label('Event type',exact=True).select_option('submit')
    await page.get_by_label('Submitted document',exact=True).select_option(run['id'])
    await page.get_by_label('Evaluation to freeze (optional)',exact=True).select_option(evaluations[0]['id'])
    await page.get_by_role('button',name='Record event',exact=True).click()
    await expect(page.get_by_test_id('application-stage')).to_have_text('submitted')
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        recorded=(await client.get('/api/applications')).json()[0]
        released=(await client.get('/api/runs/'+run['id'])).json()
        assert recorded['job_id']==released['job_id']==chosen['job_id']
        assert recorded['submission']['artifact']['pdf_hash']==released['release']['pdf_hash']
        assert recorded['submission']['artifact']['job_match']
        assert recorded['submission']['evaluation']['id']==released['evaluation_id']==evaluations[0]['id']
    await page.get_by_role('button',name='Discover',exact=True).click()
    feed.write_text(json.dumps({'payload':{'jobs':[],'meta':{'total':0}}}))
    await page.get_by_role('button',name='Refresh enabled sources',exact=True).click()
    await expect(page.get_by_test_id('scan-status')).to_have_text('empty')
    await expect(page.get_by_test_id('posting-1')).to_contain_text('Absent from a complete scan')


async def test_application_tracker_records_only_explicit_submission_and_audited_correction(real_page,real_server):
    page=real_page
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        job=(await client.post('/api/jobs',json={'text':'Python required.','company':'Tracker Example','role':'Engineer'})).json()
    await page.goto(real_server.url,wait_until='domcontentloaded')
    await page.get_by_role('button',name='Applications',exact=True).click()
    await page.get_by_label('Application role',exact=True).select_option(job['id'])
    await page.get_by_role('button',name='Create application record',exact=True).click()
    await expect(page.get_by_test_id('application-stage')).to_have_text('planned')
    await page.get_by_label('Event type',exact=True).select_option('submit')
    await expect(page.get_by_role('button',name='Record event',exact=True)).to_be_disabled()
    await page.get_by_label('Submitted document',exact=True).select_option('unknown')
    await page.get_by_label('Event date (optional)',exact=True).fill('2026-11-10')
    await page.get_by_role('button',name='Record event',exact=True).click()
    await expect(page.get_by_test_id('application-stage')).to_have_text('submitted')
    await expect(page.get_by_test_id('submission-binding')).to_contain_text('Document unknown')
    await page.get_by_label('Event type',exact=True).select_option('response_received')
    await page.get_by_label('Response category',exact=True).select_option('favorable')
    await page.get_by_role('button',name='Record event',exact=True).click()
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        view=(await client.get('/api/applications')).json()[0]
        assert (await client.get('/api/metrics')).json()['applications']['positive']==1
    await page.get_by_label('Event type',exact=True).select_option('correction')
    await page.get_by_label('Original event',exact=True).select_option(view['events'][-1]['id'])
    await page.get_by_label('Correction reason',exact=True).fill('This was an automated acknowledgment.')
    await page.get_by_label('Correction action',exact=True).select_option('response_received')
    await page.get_by_label('Response category',exact=True).select_option('acknowledgment')
    await page.get_by_role('button',name='Record event',exact=True).click()
    await expect(page.get_by_test_id('application-audit')).to_contain_text('This was an automated acknowledgment.')
    await page.reload(wait_until='domcontentloaded')
    await page.get_by_role('button',name='Applications',exact=True).click()
    await expect(page.get_by_test_id('application-audit')).to_contain_text('This was an automated acknowledgment.')
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        metrics=(await client.get('/api/metrics')).json()['applications']
        assert metrics['submitted']==1 and metrics['positive']==0 and metrics['pending']==1
        view=(await client.get('/api/applications')).json()[0]
        assert len(view['events'])==3 and view['events'][0]['payload']['occurred_at']=='2026-11-10'
    assert not (real_server.root/'model-calls.jsonl').exists()


async def test_source_draft_cancel_and_interrupted_scan_need_explicit_continue(real_page,real_server):
    page=real_page
    feed=real_server.root/'discovery-feed.json'
    feed.write_text(json.dumps({'delay':3,'payload':{'jobs':[greenhouse(1)],'meta':{'total':1}}}))
    await page.goto(real_server.url,wait_until='domcontentloaded')
    await page.get_by_role('button',name='Discover',exact=True).click()
    await page.get_by_role('button',name='Add source',exact=True).click()
    await page.get_by_label('Board name 1',exact=True).fill('saved-draft')
    await page.wait_for_function("""() => new Promise(resolve => {
        const request=indexedDB.open('resume-agent-form-drafts',1);
        request.onsuccess=()=>{const db=request.result;const read=db.transaction('drafts').objectStore('drafts').getAll();
            read.onsuccess=()=>{resolve(read.result.some(r=>r.identity.form==='discovery-sources'&&r.value.sources?.[0]?.board==='saved-draft'));db.close();};};
    })""")
    await page.reload(wait_until='domcontentloaded')
    await page.get_by_role('button',name='Discover',exact=True).click()
    await expect(page.get_by_label('Board name 1',exact=True)).to_have_value('saved-draft')
    await page.get_by_role('button',name='Save sources',exact=True).click()
    await expect(page.get_by_text('Source configuration saved.',exact=True)).to_be_visible()
    await page.get_by_role('button',name='Refresh enabled sources',exact=True).click()
    await expect(page.get_by_test_id('scan-status')).to_have_text('running')
    await page.get_by_role('button',name='Cancel scan',exact=True).click()
    await expect(page.get_by_test_id('scan-status')).to_have_text('cancelled')
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        assert (await client.get('/api/discovery/postings')).json()['total']==0
    await page.get_by_role('button',name='Refresh enabled sources',exact=True).click()
    await expect(page.get_by_test_id('scan-status')).to_have_text('running')
    real_server.process.kill()
    real_server.process.wait(timeout=5)
    feed.write_text(json.dumps({'payload':{'jobs':[greenhouse(1)],'meta':{'total':1}}}))
    await real_server.restart()
    await page.reload(wait_until='domcontentloaded')
    await page.get_by_role('button',name='Discover',exact=True).click()
    await expect(page.get_by_test_id('scan-status')).to_have_text('interrupted')
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        scan=(await client.get('/api/discovery/syncs')).json()[0]
        assert scan['request_attempts']==1 and (await client.get('/api/discovery/postings')).json()['total']==0
    await page.get_by_role('button',name='Continue saved scan',exact=True).click()
    await expect(page.get_by_test_id('scan-status')).to_have_text('complete')
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        continued=(await client.get('/api/discovery/syncs/'+scan['id'])).json()
        assert continued['request_attempts']==2 and (await client.get('/api/discovery/postings')).json()['total']==1
    assert not (real_server.root/'model-calls.jsonl').exists()

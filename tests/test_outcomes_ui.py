import json
import os
from pathlib import Path

import httpx
import pytest
from playwright.async_api import expect

from tests.test_reliability_journey import real_page,real_server  # noqa: F401

pytestmark=pytest.mark.skipif(os.getenv('RESUME_REAL_BROWSER_TEST')!='1',reason='Real browser acceptance flag not set')


async def test_dashboard_company_and_export_use_explicit_application_events(real_page,real_server):
    page=real_page
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        job=(await client.post('/api/jobs',json={'text':'Python CASE_PRIORITY','company':'Metrics Example','role':'Engineer'})).json()
        app=(await client.post('/api/applications',json={'job_id':job['id'],'action_id':'plan'})).json()
        await page.goto(real_server.url,wait_until='domcontentloaded')
        await page.get_by_role('button',name='Overview',exact=True).click()
        await expect(page.get_by_test_id('submitted-applications')).to_contain_text('0')
        assert (await client.get('/api/metrics')).json()['applications']['submitted']==0
        submitted=(await client.post(f"/api/applications/{app['id']}/events",json={'action_id':'sent',
            'expected_revision':app['revision'],'event':{'kind':'submit','artifact_unknown':True}})).json()
        response=await client.post(f"/api/applications/{app['id']}/events",json={'action_id':'reply',
            'expected_revision':submitted['revision'],'event':{'kind':'response_received','category':'favorable'}})
        assert response.status_code==200
    await page.reload(wait_until='domcontentloaded')
    await page.get_by_role('button',name='Overview',exact=True).click()
    await expect(page.get_by_test_id('submitted-applications')).to_contain_text('1')
    await expect(page.get_by_test_id('positive-outcomes')).to_contain_text('1')
    await expect(page.get_by_text('Generation health',exact=True)).to_be_visible()
    await page.get_by_role('button',name='Companies',exact=True).click()
    await expect(page.get_by_text('Metrics Example',exact=True)).to_be_visible()
    await expect(page.get_by_text('1 submitted',exact=True)).to_be_visible()
    await expect(page.get_by_text('1 application record',exact=True)).to_be_visible()
    await page.get_by_role('button',name='Outcomes',exact=True).click()
    await expect(page.get_by_role('heading',name='Outcome evidence',exact=True)).to_be_visible()
    await expect(page.get_by_text('Unknown submission score: 1',exact=True)).to_be_visible()
    async with page.expect_download() as downloaded:
        await page.get_by_role('link',name='Export local report',exact=True).click()
    report=json.loads(Path(await (await downloaded.value).path()).read_text())
    assert report['counts']['positive']==1 and report['counts']['unknown_score']==1
    assert all(row['positive_rate'] is None for row in report['bands'])

"""Actual memory UI and API; no request interception."""
import os

import httpx
import pytest
from playwright.async_api import expect

from tests.test_reliability_journey import real_page, real_server  # noqa: F401

pytestmark = pytest.mark.skipif(os.getenv('RESUME_REAL_BROWSER_TEST') != '1',reason='Real browser acceptance flag not set')


async def test_memory_is_reviewed_then_reused_or_revoked(real_page,real_server):
    page = real_page
    await page.goto(real_server.url,wait_until='domcontentloaded')
    await page.get_by_role('button',name='Memory',exact=True).click()
    await page.get_by_label('Writing instruction',exact=True).fill('Keep original metric wording.')
    await page.get_by_label('Source or reason',exact=True).fill('My preferred writing style.')
    await page.get_by_role('button',name='Create proposal',exact=True).click()
    await expect(page.get_by_role('heading',name='Review memory proposal')).to_be_visible()
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        assert (await client.get('/api/memory/active')).json()['records'] == []
        await page.get_by_role('button',name='Reject proposal',exact=True).click()
        assert (await client.get('/api/memory/active')).json()['records'] == []
        await page.get_by_label('Writing instruction',exact=True).fill('Keep original metric wording.')
        await page.get_by_label('Source or reason',exact=True).fill('My preferred writing style.')
        await page.get_by_role('button',name='Create proposal',exact=True).click()
        await page.get_by_role('button',name='Accept reviewed change',exact=True).click()
        await expect(page.get_by_text('Active memory',exact=True)).to_be_visible()
        await expect(page.get_by_role('button',name='Revoke',exact=True)).to_be_visible()
        assert len((await client.get('/api/memory/active')).json()['records']) == 1
        await page.reload(wait_until='domcontentloaded')
        await page.get_by_role('button',name='Memory',exact=True).click()
        await page.get_by_role('button',name='Revoke',exact=True).click()
        await expect(page.get_by_role('button',name='Revoke',exact=True)).to_have_count(0)
        assert (await client.get('/api/memory/active')).json()['records'] == []
        assert sorted(r['status'] for r in (await client.get('/api/memory/proposals')).json()) == ['rejected','revoked']


async def test_fact_correction_shows_exact_before_after_and_requires_acceptance(real_page,real_server):
    page = real_page
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        original = (await client.get('/api/profile')).json()
        await page.goto(real_server.url,wait_until='domcontentloaded')
        await page.get_by_role('button',name='Memory',exact=True).click()
        await page.get_by_label('Change type',exact=True).select_option('candidate_fact')
        await page.get_by_label('Profile field',exact=True).select_option('/personal/full_name')
        await page.get_by_label('Corrected value',exact=True).fill('Casey Corrected Example')
        await page.get_by_label('Source or reason',exact=True).fill('This is my corrected full name.')
        await page.get_by_role('button',name='Create proposal',exact=True).click()
        review=page.get_by_role('region',name='Memory review')
        await expect(review).to_contain_text(original['profile']['personal']['full_name'])
        await expect(review).to_contain_text('Casey Corrected Example')
        assert (await client.get('/api/profile')).json() == original
        await page.get_by_role('button',name='Accept reviewed change',exact=True).click()
        await expect(review).to_have_count(0)
        corrected=(await client.get('/api/profile')).json()
        assert corrected['profile']['personal']['full_name']=='Casey Corrected Example'
        assert not corrected['review_required']
        await page.get_by_label('Change type',exact=True).select_option('target_preference')
        await page.get_by_label('Preferred locations',exact=True).fill('Berlin, Amsterdam')
        await page.get_by_label('Remote',exact=True).check()
        await page.get_by_label('Source or reason',exact=True).fill('My target locations and work mode.')
        await page.get_by_role('button',name='Create proposal',exact=True).click()
        await page.get_by_role('button',name='Accept reviewed change',exact=True).click()
        await expect(page.get_by_role('button',name='Revoke',exact=True)).to_be_visible()
        active=(await client.get('/api/memory/active')).json()['records']
        assert active[0]['payload']['work_modes']==['Remote']


async def test_memory_form_survives_reload_and_hard_constraints_need_review(real_page,real_server):
    page=real_page
    await page.goto(real_server.url,wait_until='domcontentloaded')
    await page.get_by_role('button',name='Memory',exact=True).click()
    await page.get_by_label('Writing instruction',exact=True).fill('Preserve C++ and C# exactly.')
    await page.get_by_label('Source or reason',exact=True).fill('My draft preference.')
    await page.reload(wait_until='domcontentloaded')
    await page.get_by_role('button',name='Memory',exact=True).click()
    await expect(page.get_by_label('Writing instruction',exact=True)).to_have_value('Preserve C++ and C# exactly.')
    await page.get_by_label('Change type',exact=True).select_option('target_preference')
    await page.get_by_role('button',name='Add hard constraint',exact=True).click()
    await page.get_by_label('Constraint category 1',exact=True).select_option('authorization')
    await page.get_by_label('Constraint value 1',exact=True).fill('Needs sponsorship')
    await page.get_by_label('Confirmed statement 1',exact=True).fill('I need employer visa sponsorship.')
    await page.get_by_role('button',name='Create proposal',exact=True).click()
    async with httpx.AsyncClient(base_url=real_server.url) as client:
        assert (await client.get('/api/memory/active')).json()['records']==[]
        await page.get_by_role('button',name='Accept reviewed change',exact=True).click()
        await expect(page.get_by_role('button',name='Revoke',exact=True)).to_be_visible()
        active=(await client.get('/api/memory/active')).json()['records']
        assert active[0]['payload']['hard_constraints'][0]['text']=='I need employer visa sponsorship.'

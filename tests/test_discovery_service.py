import json

import httpx
import pytest

from resume_agent.run_store import Conflict
from tests.test_discovery import greenhouse
from tests.test_discovery_http import Chunks
from tests.test_v2_api import services


class Feed:
    def __init__(self):
        self.payload={'jobs':[greenhouse(1),greenhouse(2)],'meta':{'total':2}}
        self.status=200
        self.calls=[]
    async def handler(self,request):
        self.calls.append(str(request.url))
        return httpx.Response(self.status,headers={'content-type':'application/json'},
            stream=Chunks([json.dumps(self.payload).encode()]))


def setup_discovery(tmp_path):
    from resume_agent.discovery.http import BoundedHttpClient
    runtime,calls=services(tmp_path)
    feed=Feed()
    runtime.discovery.http_factory=lambda:BoundedHttpClient(transport=httpx.MockTransport(feed.handler),validator=lambda _:None)
    async def sleep(delay):
        pass
    runtime.discovery.sleep=sleep
    original=runtime.discovery.sources()
    configured=runtime.discovery.replace_sources([{'provider':'greenhouse','board':'example','company':'Example'}],
        expected_revision=original['revision'],action_id='configure')
    return runtime,feed,calls,configured


def sync(service,action):
    return service.create_sync(expected_sources_revision=service.sources()['revision'],action_id=action)


def test_sources_are_reviewed_revision_bound_and_preserve_identity(tmp_path):
    runtime,feed,calls,configured=setup_discovery(tmp_path)
    service=runtime.discovery
    assert len(configured['sources'])==1
    with pytest.raises(Conflict):
        service.replace_sources([],expected_revision='f'*64,action_id='stale')
    with pytest.raises(Conflict):
        service.replace_sources([],expected_revision=configured['revision'],action_id='configure')
    source=configured['sources'][0]
    with pytest.raises(Conflict):
        service.replace_sources([{**source,'board':'different'}],expected_revision=configured['revision'],action_id='change-id')
    with pytest.raises(ValueError):
        service.replace_sources([{'provider':'greenhouse','board':'x','api_key':'secret'}],expected_revision=configured['revision'],action_id='secret')
    assert feed.calls==calls==[]


@pytest.mark.asyncio
async def test_partial_failure_and_clean_empty_have_distinct_safe_posting_state(tmp_path):
    runtime,feed,calls,_=setup_discovery(tmp_path)
    service=runtime.discovery
    complete=await service.drive(sync(service,'first')['id'])
    assert complete['status']=='complete'
    original=service.list_postings()
    assert len(original)==2 and all(p['state']=='active' for p in original)
    feed.payload={'jobs':[greenhouse(1),{'title':'Malformed'}],'meta':{'total':2}}
    partial=await service.drive(sync(service,'partial')['id'])
    assert partial['status']=='partial'
    kept=service.list_postings()
    assert len(kept)==2 and all(p['state']=='active' for p in kept)
    assert next(p for p in kept if p['external_id']=='2')['freshness']=='stale'
    feed.status=503
    failed=await service.drive(sync(service,'failure')['id'])
    assert failed['status']=='failed' and len(service.list_postings())==2
    assert all(p['state']=='active' for p in service.list_postings())
    feed.status=200;feed.payload={'jobs':[],'meta':{'total':0}}
    empty=await service.drive(sync(service,'empty')['id'])
    assert empty['status']=='empty'
    assert all(p['state']=='removed' for p in service.list_postings())
    assert len(runtime.jobs.list())==2
    assert calls==[]


@pytest.mark.asyncio
async def test_cached_response_and_frozen_config_survive_hard_restart_without_new_get(tmp_path):
    from resume_agent.runtime import Runtime
    runtime,feed,calls,configured=setup_discovery(tmp_path)
    service=runtime.discovery
    created=sync(service,'first')
    class Crash(BaseException):
        pass
    def crash(stage):
        if stage=='after_response_cached':
            raise Crash()
    service.crash_hook=crash
    with pytest.raises(Crash):
        await service.drive(created['id'])
    assert len(feed.calls)==1
    service.replace_sources([{**configured['sources'][0],'company':'Changed Company','enabled':False}],
        expected_revision=configured['revision'],action_id='changed-config')
    reopened=Runtime(root=tmp_path,settings=runtime.settings,tool_finder=lambda _: '/tool')
    reopened.discovery.http_factory=service.http_factory
    assert reopened.discovery.get_sync(created['id'])['status']=='interrupted'
    complete=await reopened.discovery.drive(created['id'],continue_action_id='continue')
    assert complete['status']=='complete' and len(feed.calls)==1
    assert all(job.company=='Example' for job in reopened.jobs.list())
    assert await reopened.discovery.drive(created['id'],continue_action_id='continue')==complete
    assert calls==[]


@pytest.mark.asyncio
async def test_request_budget_is_consumed_before_crashed_get_and_never_reset(tmp_path):
    runtime,feed,calls,_=setup_discovery(tmp_path)
    service=runtime.discovery
    created=sync(service,'first')
    class Crash(BaseException):
        pass
    def crash(stage):
        if stage=='before_http_attempt':
            raise Crash()
    service.crash_hook=crash
    for index in range(3):
        with pytest.raises(Crash):
            await service.drive(created['id'],continue_action_id=f'continue-{index}' if index else None)
        assert service.get_sync(created['id'])['status']=='interrupted'
    service.crash_hook=None
    failed=await service.drive(created['id'],continue_action_id='exhausted')
    assert failed['status']=='failed' and feed.calls==[]
    assert 'request_budget_exhausted' in failed['boards'][0]['diagnostics']
    assert calls==[]


@pytest.mark.asyncio
async def test_board_write_is_atomic_and_recovery_uses_success_cache(tmp_path):
    import sqlite3
    runtime,feed,calls,_=setup_discovery(tmp_path)
    service=runtime.discovery
    created=sync(service,'first')
    with runtime.store.connection() as conn:
        conn.execute("CREATE TRIGGER reject_posting BEFORE INSERT ON discovery_postings BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    with pytest.raises(sqlite3.Error):
        await service.drive(created['id'])
    assert runtime.jobs.list()==[] and service.list_postings()==[]
    assert service.get_sync(created['id'])['status']=='interrupted'
    with runtime.store.connection() as conn:
        conn.execute('DROP TRIGGER reject_posting')
    assert (await service.drive(created['id'],continue_action_id='recover'))['status']=='complete'
    assert len(feed.calls)==1 and len(runtime.jobs.list())==2 and calls==[]


@pytest.mark.asyncio
async def test_no_enabled_sources_and_cancellation_never_fetch(tmp_path):
    runtime,feed,calls,configured=setup_discovery(tmp_path)
    service=runtime.discovery
    queued=sync(service,'queued')
    cancelled=service.cancel(queued['id'],action_id='cancel')
    assert cancelled['status']=='cancelled'
    assert (await service.drive(queued['id']))['status']=='cancelled'
    service.replace_sources([],expected_revision=configured['revision'],action_id='clear')
    empty=sync(service,'none')
    assert empty['status']=='empty' and empty['source_count']==0
    assert feed.calls==calls==[]


@pytest.mark.asyncio
async def test_resuming_an_older_cached_scan_cannot_roll_back_newer_posting_evidence(tmp_path):
    runtime,feed,calls,_=setup_discovery(tmp_path)
    service=runtime.discovery
    older=sync(service,'older')
    class Crash(BaseException):
        pass
    def crash(stage):
        if stage=='after_response_cached':
            raise Crash()
    service.crash_hook=crash
    with pytest.raises(Crash):
        await service.drive(older['id'])
    assert service.get_sync(older['id'])['status']=='interrupted'
    service.crash_hook=None
    feed.payload={'jobs':[greenhouse(1,content='<p>Newer observed requirements.</p>'),greenhouse(3)],'meta':{'total':2}}
    newer=await service.drive(sync(service,'newer')['id'])
    assert newer['status']=='complete'
    current={p['external_id']:p for p in service.list_postings()}
    assert set(current)=={'1','3'}
    restored=await service.drive(older['id'],continue_action_id='restore-old')
    assert restored['status']=='partial' and len(feed.calls)==2
    after={p['external_id']:p for p in service.list_postings()}
    assert set(after)=={'1','3'} and all(p['state']=='active' for p in after.values())
    assert after['1']['job_id']==current['1']['job_id']
    assert 'Newer observed requirements.' in runtime.jobs.get(after['1']['job_id']).text
    assert calls==[]


@pytest.mark.asyncio
async def test_retry_wait_is_persisted_and_respected_after_restart(tmp_path):
    runtime,feed,calls,_=setup_discovery(tmp_path)
    service=runtime.discovery
    now=[1000.0];waits=[]
    service.clock=lambda:now[0]
    async def sleep(delay):
        waits.append(delay);now[0]+=delay
    service.sleep=sleep
    feed.status=503
    created=sync(service,'retry')
    class Crash(BaseException):
        pass
    def crash(stage):
        if stage=='after_retry_intent':
            raise Crash()
    service.crash_hook=crash
    with pytest.raises(Crash):
        await service.drive(created['id'])
    assert len(feed.calls)==1 and waits==[]
    service.crash_hook=None;feed.status=200
    done=await service.drive(created['id'],continue_action_id='resume-wait')
    assert done['status']=='complete' and waits==[1] and len(feed.calls)==2
    assert calls==[]


@pytest.mark.asyncio
async def test_global_owner_prevents_simultaneous_scans_and_active_cancellation_publishes_no_board(tmp_path):
    import asyncio
    runtime,feed,calls,_=setup_discovery(tmp_path)
    service=runtime.discovery
    entered,finish=asyncio.Event(),asyncio.Event()
    original=feed.handler
    async def handler(request):
        entered.set();await finish.wait();return await original(request)
    from resume_agent.discovery.http import BoundedHttpClient
    service.http_factory=lambda:BoundedHttpClient(transport=httpx.MockTransport(handler),validator=lambda _:None)
    first=sync(service,'first');second=sync(service,'second')
    task=asyncio.create_task(service.drive(first['id']))
    await entered.wait()
    from resume_agent.runtime import Runtime
    other=Runtime(root=tmp_path,settings=runtime.settings,tool_finder=lambda _: '/tool')
    other.discovery.http_factory=service.http_factory
    with pytest.raises(Conflict):
        await other.discovery.drive(second['id'])
    service.cancel(first['id'],action_id='cancel-active')
    finish.set()
    assert (await task)['status']=='cancelled'
    assert service.list_postings()==[] and runtime.jobs.list()==[]
    assert service.get_sync(second['id'])['status']=='queued'
    assert calls==[]


def test_source_configuration_is_bounded_and_readding_identity_keeps_history(tmp_path):
    runtime,feed,calls,configured=setup_discovery(tmp_path)
    service=runtime.discovery
    with pytest.raises(ValueError):
        service.replace_sources([{'provider':'greenhouse','board':f'example{i}'} for i in range(21)],
            expected_revision=configured['revision'],action_id='too-many')
    cleared=service.replace_sources([],expected_revision=configured['revision'],action_id='clear')
    restored=service.replace_sources([{'provider':'greenhouse','board':'example','company':'Example'}],
        expected_revision=cleared['revision'],action_id='restore')
    assert restored['sources'][0]['id']==configured['sources'][0]['id']
    assert feed.calls==calls==[]


@pytest.mark.asyncio
async def test_cross_provider_similarity_is_a_hint_never_a_merge(tmp_path):
    from tests.test_discovery import lever
    from resume_agent.discovery.http import BoundedHttpClient
    runtime,feed,calls,configured=setup_discovery(tmp_path)
    service=runtime.discovery
    service.replace_sources([configured['sources'][0],{'provider':'lever','board':'example','company':'Example'}],
        expected_revision=configured['revision'],action_id='second-provider')
    async def handler(request):
        payload=[lever('one',text='Python Engineer')] if request.url.host=='api.lever.co' else feed.payload
        return httpx.Response(200,headers={'content-type':'application/json'},stream=Chunks([json.dumps(payload).encode()]))
    service.http_factory=lambda:BoundedHttpClient(transport=httpx.MockTransport(handler),validator=lambda _:None)
    assert (await service.drive(sync(service,'all')['id']))['status']=='complete'
    postings=service.list_postings()
    assert len(postings)==len({p['job_id'] for p in postings})==3
    assert all(p['possible_duplicates'] for p in postings)
    assert calls==[]


@pytest.mark.asyncio
async def test_posting_pages_are_bounded_and_report_total_instead_of_silent_truncation(tmp_path):
    runtime,feed,calls,_=setup_discovery(tmp_path)
    service=runtime.discovery
    await service.drive(sync(service,'first')['id'])
    page=service.postings_page(limit=1)
    assert page['total']==2 and page['has_more'] and len(page['items'])==1
    following=service.postings_page(limit=1,offset=1)
    assert not following['has_more'] and len(following['items'])==1
    assert page['items'][0]['external_id']!=following['items'][0]['external_id']
    with pytest.raises(ValueError):
        service.postings_page(limit=1001)
    assert calls==[]

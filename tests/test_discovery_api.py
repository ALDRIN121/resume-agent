import asyncio

from fastapi.testclient import TestClient

from tests.test_discovery_service import setup_discovery


def test_discovery_routes_are_explicit_typed_and_share_durable_service(tmp_path):
    from resume_agent.api.app import create_app
    from resume_agent.runtime import Runtime
    runtime,feed,calls,configured=setup_discovery(tmp_path)
    with TestClient(create_app(services=runtime),base_url='http://localhost') as client:
        response=client.get('/api/discovery/sources')
        assert response.headers['content-type'].startswith('application/json')
        assert response.json()==configured
        body={'sources':configured['sources'],'expected_revision':configured['revision'],'action_id':'save-api'}
        assert client.put('/api/discovery/sources',json={**body,'url':'http://127.0.0.1'}).status_code==422
        assert client.put('/api/discovery/sources',json={**body,'expected_revision':'f'*64}).status_code==409
        saved=client.put('/api/discovery/sources',json=body).json()
        created=client.post('/api/discovery/syncs',json={'expected_sources_revision':saved['revision'],'action_id':'scan-api'}).json()
        assert created['status']=='queued' and feed.calls==calls==[]
        completed=client.post('/api/discovery/syncs/'+created['id']+'/continue',json=None)
        assert completed.status_code==200,completed.text
        assert completed.json()['status']=='complete'
        replay=client.post('/api/discovery/syncs',json={'expected_sources_revision':saved['revision'],'action_id':'scan-api'}).json()
        assert replay['id']==created['id'] and len(feed.calls)==1
        page=client.get('/api/discovery/postings?limit=1').json()
        assert page['total']==2 and page['has_more']
        job_id=page['items'][0]['job_id']
        origin=client.get('/api/jobs/'+job_id+'/origin').json()
        assert origin[0]['raw']['id'] and origin[0]['selected_snapshot_is_current']
        assert client.get('/api/discovery/postings?limit=1001').status_code==422
        assert client.get('/api/discovery/syncs/missing').status_code==404
    reopened=Runtime(root=tmp_path,settings=runtime.settings)
    assert reopened.discovery.get_sync(created['id'])['status']=='complete'
    assert len(reopened.discovery.list_postings())==2 and calls==[]


def test_origin_retains_exact_raw_observation_after_posting_changes(tmp_path):
    from tests.test_discovery import greenhouse
    from tests.test_discovery_service import sync
    runtime,feed,calls,_=setup_discovery(tmp_path)
    service=runtime.discovery
    asyncio.run(service.drive(sync(service,'first')['id']))
    selected=service.list_postings()[0]
    feed.payload={'jobs':[greenhouse(int(selected['external_id']),content='<p>Changed complete role text.</p>')],'meta':{'total':1}}
    asyncio.run(service.drive(sync(service,'later')['id']))
    origins=service.job_origin(selected['job_id'])
    assert len(origins)==1 and not origins[0]['selected_snapshot_is_current']
    assert origins[0]['raw']['content']!='<p>Changed complete role text.</p>'
    assert origins[0]['current_job_id']!=selected['job_id']
    assert runtime.jobs.get(selected['job_id']).text==selected['job']['text'] and calls==[]


def test_documented_sync_alias_creates_without_implicit_network_work(tmp_path):
    from resume_agent.api.app import create_app
    runtime,feed,calls,configuration=setup_discovery(tmp_path)
    with TestClient(create_app(services=runtime),base_url='http://localhost') as client:
        body={'expected_sources_revision':configuration['revision'],'action_id':'documented-alias'}
        created=client.post('/api/discovery/sync',json=body)
        assert created.status_code==200,created.text
        assert created.json()['status']=='queued' and feed.calls==calls==[]
        assert client.post('/api/discovery/syncs',json=body).json()==created.json()

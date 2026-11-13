from fastapi.testclient import TestClient

from tests.test_evaluation_operations import setup_evaluation


def test_http_application_requires_explicit_revision_bound_submission(tmp_path):
    from resume_agent.api.app import create_app
    runtime,job,calls=setup_evaluation(tmp_path)
    with TestClient(create_app(services=runtime),base_url='http://localhost') as client:
        response=client.post('/api/applications',json={'job_id':job.id,'action_id':'plan'})
        assert response.status_code==200,response.text
        app=response.json()
        assert app['stage']=='planned' and app['submission'] is None
        url='/api/applications/'+app['id']
        assert client.get(url).json()==app
        assert client.get('/api/applications').json()==[app]
        action={'action_id':'submit','expected_revision':app['revision'],
                'event':{'kind':'submit','artifact_unknown':True}}
        submitted=client.post(url+'/events',json=action)
        assert submitted.status_code==200,submitted.text
        assert submitted.json()['stage']=='submitted'
        assert client.post(url+'/events',json=action).json()==submitted.json()
        assert client.post(url+'/events',json={**action,'event':{'kind':'response_received','category':'favorable'}}).status_code==409
        assert client.post(url+'/events',json={'action_id':'oops','expected_revision':submitted.json()['revision'],
            'event':{'kind':'submit'}}).status_code==422
        assert calls==[]

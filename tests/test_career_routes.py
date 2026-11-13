from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_evaluation_operations import setup_evaluation


def test_private_job_and_evaluation_adapters_keep_model_work_explicit(tmp_path):
    from resume_agent.api.routers.jobs import router, evaluation_router
    runtime,job,calls=setup_evaluation(tmp_path)
    app=FastAPI()
    app.state.services=runtime
    app.include_router(router)
    app.include_router(evaluation_router)
    with TestClient(app) as client:
        created=client.post('/api/jobs',json={'text':'Python','source_key':'manual:http'}).json()
        assert client.get('/api/jobs/'+created['id']).json()['text']=='Python'
        assert len(client.get('/api/jobs').json())==2
        assert calls==[]
        response=client.post(f"/api/jobs/{created['id']}/evaluations",json={})
        assert response.status_code==200,response.text
        pending=response.json()
        assert pending['status']=='pending_model' and calls==[]
        assert client.get(f"/api/jobs/{created['id']}/evaluations").json()[0]['id']==pending['id']
        url='/api/evaluations/'+pending['id']
        complete=client.post(url+'/continue',json=None)
        assert complete.status_code==200,complete.text
        assert complete.json()['status']=='complete'
        assert client.get(url).json()['result']['fit']['lower']==100
        assert len(calls)==1
        assert client.post('/api/jobs',json={'text':'x'*48001}).status_code==422
        assert client.get('/api/jobs/not-a-job').status_code==404

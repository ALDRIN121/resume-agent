import pytest
from fastapi.testclient import TestClient

from resume_agent.contracts import RunRequest
from resume_agent.run_store import Conflict
from tests.test_evaluation_operations import setup_evaluation


@pytest.mark.asyncio
async def test_selected_job_generation_preserves_snapshot_and_requires_explicit_advisory_override(tmp_path):
    runtime,job,_=setup_evaluation(tmp_path)
    op=await runtime.evaluations.drive(runtime.evaluations.create(job.id)['id'])
    selected=runtime.create_run(RunRequest(job_input=job.text,input_type='text',job_id=job.id,evaluation_id=op['id']))
    fixed=runtime.store.input('run',selected.id)
    assert fixed['request']['job_input']==job.text
    assert fixed['request']['evaluation_id']==op['id']
    with pytest.raises(Conflict):
        runtime.create_run(RunRequest(job_input='Different posting',input_type='text',job_id=job.id,evaluation_id=op['id']))
    current=runtime.profiles.load_snapshot()
    changed=current.profile.model_copy(deep=True)
    changed.summary='New profile version.'
    runtime.profiles.save_reviewed(current.revision,changed,{})
    with pytest.raises(Conflict):
        runtime.create_run(RunRequest(job_input=job.text,input_type='text',job_id=job.id,evaluation_id=op['id']))
    override=runtime.create_run(RunRequest(job_input=job.text,input_type='text',job_id=job.id,evaluation_id=op['id'],evaluation_override=True))
    assert runtime.store.input('run',override.id)['request']['evaluation_override']


@pytest.mark.asyncio
async def test_http_jobs_and_nonprioritize_override_use_shared_service(tmp_path):
    from resume_agent.api.app import create_app
    def unknown(response,fixed):
        response['findings'][0].update(status='unknown',sources=[],rationale='Evidence not supplied.')
        return response
    runtime,job,calls=setup_evaluation(tmp_path,unknown)
    op=await runtime.evaluations.drive(runtime.evaluations.create(job.id)['id'])
    with TestClient(create_app(services=runtime),base_url='http://localhost') as client:
        assert client.get('/api/jobs').status_code==200
        assert client.get('/api/evaluations/'+op['id']).json()['result']['fit']['recommendation']=='review'
        body={'jd_text':job.text,'job_id':job.id,'evaluation_id':op['id']}
        assert client.post('/api/runs',json=body).status_code==409
        response=client.post('/api/runs',json={**body,'evaluation_override':True})
        assert response.status_code==200,response.text
        fixed=runtime.store.input('run',response.json()['id'])
        assert fixed['request']['job_id']==job.id and fixed['request']['evaluation_override']


@pytest.mark.asyncio
async def test_mismatched_job_and_evaluation_cannot_be_overridden(tmp_path):
    runtime,job,_=setup_evaluation(tmp_path)
    op=await runtime.evaluations.drive(runtime.evaluations.create(job.id)['id'])
    other=runtime.jobs.capture('Different posting')
    with pytest.raises(Conflict):
        runtime.create_run(RunRequest(job_input=other.text,input_type='text',job_id=other.id,
                                      evaluation_id=op['id'],evaluation_override=True))

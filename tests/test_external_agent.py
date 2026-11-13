import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_agent.checkpoint import read_v2_checkpoint
from resume_agent.config import FeaturesConfig, OutputConfig, ResumeAgentSettings
from resume_agent.contracts import AcceptImport, Continue, ModelResponse, PresentSuggestions, ReviewPdf, RunRequest
from resume_agent.run_store import Conflict
from tests.test_v2_workflow import PROFILE


def host_runtime(tmp_path,monkeypatch,*,profile=True,real_tools=False):
    import resume_agent.llm as module
    from resume_agent.runtime import Runtime
    calls=[]
    def forbidden(*args,**kwargs):
        calls.append('factory');raise AssertionError('Configured provider must not be constructed.')
    async def forbidden_callback(*args):
        calls.append('callback');raise AssertionError('Backend callback must not run.')
    monkeypatch.setattr(module,'get_chat_model',forbidden)
    def compiler(source,*,output_dir):
        from resume_agent.content_review import expected_display_text
        from resume_agent.schemas import RenderManifest
        from resume_agent.tools.tectonic_compile import CompileResult
        from tests.test_pdf_content_check import make_pdf
        identifier=runtime.store.run_ids()[0]
        manifest=read_v2_checkpoint(runtime.store.checkpoint_path,'run',identifier)['values']['manifest']
        pdf=make_pdf(output_dir/'resume.pdf',expected_display_text(RenderManifest.model_validate(manifest)))
        return CompileResult(True,str(pdf),[],'')
    from tests.test_approved_render import images
    runtime=Runtime(root=tmp_path,settings=ResumeAgentSettings(_env_file=None,provider='openai',openai_api_key=None,
        features=FeaturesConfig(enable_hr_review=True),output=OutputConfig(base_dir=str(tmp_path/'output'))),
        model=forbidden_callback,compile_adapter=None if real_tools else compiler,image_adapter=None if real_tools else images,
        tool_finder=shutil.which if real_tools else lambda _: '/tool')
    if profile and runtime.profiles.load_snapshot() is None:
        runtime.profiles.save_reviewed(None,PROFILE,{})
    return runtime,calls


def response(pending,result,action='host-response'):
    return ModelResponse(action_id=action,request_id=pending.request_id,input_hash=pending.input_hash,result=result)


@pytest.mark.parametrize('real_tools',[False,pytest.param(True,marks=pytest.mark.skipif(
    os.getenv('RESUME_REQUIRE_PDF_TOOLS')!='1',reason='Real PDF acceptance flag not set'))],ids=['fixture-tools','real-pdf-tools'])
async def test_host_requests_survive_restart_and_reach_exact_reviewed_export_without_backend(tmp_path,monkeypatch,real_tools):
    runtime,calls=host_runtime(tmp_path,monkeypatch,real_tools=real_tools)
    assert not runtime.readiness()['generation_ready']
    assert runtime.readiness(execution_mode='host')['generation_ready']
    run=runtime.create_run(RunRequest(job_input='Full Python role; preserve -- and +80%.',input_type='text',execution_mode='host'))
    view=await runtime.runs.drive(run.id)
    assert view.pending.kind=='model_request' and view.pending.payload['task']=='extract_jd'
    first=view.pending
    assert first.payload['schema_name']=='JobDescription' and first.payload['schema_version']==1
    assert first.payload['output_schema']['properties'] and 'Full Python role' in str(first.payload['input_payload'])
    assert first.payload['attempts_used']==0 and calls==[]
    runtime,calls2=host_runtime(tmp_path,monkeypatch,real_tools=real_tools)
    assert runtime.runs.get(run.id).pending==first
    view=await runtime.runs.drive(run.id,response(first,{'company':'Host Example','role_title':'Engineer'},'jd'))
    assert view.pending.payload['task']=='questions'
    view=await runtime.runs.drive(run.id,response(view.pending,{'questions':[]},'questions'))
    assert view.pending.payload['task']=='proposals'
    view=await runtime.runs.drive(run.id,response(view.pending,{'proposals':[]},'proposals'))
    assert view.pending.kind=='present_suggestions'
    with pytest.raises(Conflict):
        await runtime.runs.drive(run.id,response(first,{'approved_ids':[]},'model-cannot-approve-content'))
    assert runtime.profiles.load_snapshot().profile==PROFILE
    review=view.pending
    preview=runtime.workflow.content_preview(run.id,review.review_id,review.source_revision,[])
    view=await runtime.runs.drive(run.id,PresentSuggestions(action_id='human-content',review_id=review.review_id,
        source_revision=review.source_revision,approved_ids=[],content_hash=preview.manifest.content_hash))
    assert view.pending.kind=='review_pdf',view
    with pytest.raises(Conflict):
        await runtime.runs.drive(run.id,response(first,{'decision':'approve'},'model-cannot-approve-pdf'))
    assert all(a['status']=='disabled' for a in view.pending.payload['advisories'] if a['source'] in ('hr','vision'))
    pdf=runtime.release.get_preview(run.id);review=view.pending.review
    view=await runtime.runs.drive(run.id,ReviewPdf(action_id='human-pdf',decision='approve',
        **{key:getattr(review,key) for key in ('review_id','content_hash','render_hash','pdf_hash')}))
    assert view.status=='complete' and runtime.release.get_final(run.id)==pdf
    assert Path(view.release.destination).read_bytes()==pdf and calls==calls2==[]
    fixed=runtime.store.input('run',run.id)
    assert fixed['provider']=='external_agent' and fixed['model']=='host_agent'


async def test_host_import_is_a_durable_request_then_a_separate_human_review(tmp_path,monkeypatch):
    runtime,calls=host_runtime(tmp_path,monkeypatch,profile=False)
    created=runtime.imports.create(b'Complete source including Python and exact metrics.','resume.tex',execution_mode='host')
    view=await runtime.imports.drive(created['id'])
    assert view['status']=='pending_model' and runtime.profiles.load_snapshot() is None
    from resume_agent.contracts import ModelRequest
    pending=ModelRequest.model_validate(view['pending'])
    assert pending.payload['task']=='import_profile' and 'Complete source' in str(pending.payload['input_payload'])
    runtime,_=host_runtime(tmp_path,monkeypatch,profile=False)
    view=await runtime.imports.drive(created['id'],response(pending,PROFILE.model_dump(mode='json')))
    assert view['status']=='pending_review' and runtime.profiles.load_snapshot() is None
    review=view['pending']
    view=await runtime.imports.drive(created['id'],AcceptImport(action_id='human-import',
        **{key:review[key] for key in ('review_id','draft_hash','expected_profile_revision')}))
    assert view['status']=='complete' and runtime.profiles.load_snapshot().profile==PROFILE and calls==[]


async def test_stale_responses_use_no_attempts_and_two_invalid_results_exhaust_budget(tmp_path,monkeypatch):
    runtime,calls=host_runtime(tmp_path,monkeypatch)
    run=runtime.create_run(RunRequest(job_input='Python',input_type='text',execution_mode='host'))
    view=await runtime.runs.drive(run.id);pending=view.pending
    with pytest.raises(Conflict):
        await runtime.runs.drive(run.id,response(pending,{},'stale').model_copy(update={'input_hash':'f'*64}))
    record=next(iter(read_v2_checkpoint(runtime.store.checkpoint_path,'run',run.id)['values']['model_tasks'].values()))
    assert record['attempts']==0
    first=await runtime.runs.drive(run.id,response(pending,{'unexpected':'invalid'},'invalid1'))
    assert first.pending.request_id==pending.request_id and first.pending.payload['attempts_remaining']==1
    assert await runtime.runs.drive(run.id,response(pending,{'unexpected':'invalid'},'invalid1'))==first
    runtime,_=host_runtime(tmp_path,monkeypatch)
    second=await runtime.runs.drive(run.id,response(first.pending,{'unexpected':'invalid'},'invalid2'))
    assert second.status=='failed' and second.diagnostics[0].code=='invalid_output' and calls==[]
    record=next(iter(read_v2_checkpoint(runtime.store.checkpoint_path,'run',run.id)['values']['model_tasks'].values()))
    assert record['attempts']==2


@pytest.mark.parametrize('boundary',['validating','complete'])
async def test_consumed_response_validation_recovers_without_counting_twice(tmp_path,monkeypatch,boundary):
    from resume_agent.model_tasks import ModelTaskRunner
    runtime,calls=host_runtime(tmp_path,monkeypatch)
    run=runtime.create_run(RunRequest(job_input='Python',input_type='text',execution_mode='host'))
    pending=(await runtime.runs.drive(run.id)).pending
    original=ModelTaskRunner._save
    class Crash(BaseException):
        pass
    def crash(self,key,record):
        original(self,key,record)
        if record.get('response',{}).get('status')==boundary:
            raise Crash()
    monkeypatch.setattr(ModelTaskRunner,'_save',crash)
    with pytest.raises(Crash):
        await runtime.runs.drive(run.id,response(pending,{'company':'Example','role_title':'Engineer'}))
    monkeypatch.setattr(ModelTaskRunner,'_save',original)
    runtime,_=host_runtime(tmp_path,monkeypatch)
    assert runtime.runs.get(run.id).status=='interrupted'
    view=await runtime.runs.drive(run.id,Continue(action_id='recover'))
    assert view.pending.payload['task']=='questions' and calls==[]
    records=read_v2_checkpoint(runtime.store.checkpoint_path,'run',run.id)['values']['model_tasks'].values()
    assert next(r for r in records if r['stage']=='extract_jd')['attempts']==1


async def test_host_evaluation_uses_same_evidence_checks_and_request_lookup_api(tmp_path,monkeypatch):
    from tests.test_evaluation_operations import analysis
    runtime,calls=host_runtime(tmp_path,monkeypatch)
    current=runtime.profiles.load_snapshot();profile=current.profile.model_copy(update={'summary':'Python engineer.'})
    runtime.profiles.save_reviewed(current.revision,profile,{})
    job=runtime.jobs.capture('Python')
    created=runtime.evaluations.create(job.id,execution_mode='host')
    paused=await runtime.evaluations.drive(created['id'])
    assert paused['status']=='pending_model'
    pending=paused['pending'];fixed=runtime.store.input('operation',created['id'])
    from resume_agent.api.app import create_app
    body={'kind':'model_request','action_id':'evaluate','request_id':pending['request_id'],'input_hash':pending['input_hash'],'result':analysis(fixed)}
    with TestClient(create_app(services=runtime),base_url='http://localhost') as client:
        assert client.post('/api/model-tasks/'+pending['request_id']+'/respond',json=body|{'input_hash':'e'*64}).status_code==409
        result=client.post('/api/model-tasks/'+pending['request_id']+'/respond',json=body)
        assert result.status_code==200,result.text
        assert result.json()['result']['fit']['lower']==100
    invalid=runtime.evaluations.create(job.id,execution_mode='host')
    paused=await runtime.evaluations.drive(invalid['id'])
    raw=analysis(runtime.store.input('operation',invalid['id']));raw['findings'][0]['sources'][0]['input_hash']='0'*64
    from resume_agent.contracts import ModelRequest
    result=await runtime.evaluations.drive(invalid['id'],response(ModelRequest.model_validate(paused['pending']),raw))
    assert result['status']=='failed' and result['result'] is None and calls==[]


def test_json_external_mode_returns_requests_and_preserves_human_review(tmp_path,monkeypatch):
    from tests.test_cli_json import invoke
    runtime,calls=host_runtime(tmp_path,monkeypatch)
    result,started=invoke(tmp_path,monkeypatch,runtime,'start',{'job_input':'Python','input_type':'text','execution_mode':'external_agent'})
    assert result.exit_code==0 and started['next_action']['kind']=='model_request'
    resource='run:'+started['resource']['id']
    for index,value in enumerate([{'company':'Example','role_title':'Engineer'},{'questions':[]},{'proposals':[]} ]):
        pending=started['next_action']
        result,started=invoke(tmp_path,monkeypatch,runtime,'respond',{'kind':'model_request','action_id':f'host-{index}',
            'request_id':pending['request_id'],'input_hash':pending['input_hash'],'result':value},resource)
        assert result.exit_code==0,started
    assert started['next_action']['kind']=='present_suggestions' and started['data']['release'] is None and calls==[]


async def test_cached_host_task_satisfies_lifecycle_checkpoint_without_another_request(tmp_path):
    from resume_agent.contracts import DriverResult
    from resume_agent.model_tasks import ModelTaskRunner
    from tests.test_model_tasks import Answer,create,service
    async def driver(context):
        await ModelTaskRunner(context).run('extract_jd',Answer,['Complete input'])
        return DriverResult(status='interrupted')
    svc=service(tmp_path,driver);run=create(svc,'host')
    pending=(await svc.drive(run.id)).pending
    assert (await svc.drive(run.id,response(pending,{'value':'valid'}))).status=='interrupted'
    assert (await svc.drive(run.id,Continue(action_id='reuse'))).status=='interrupted'
    records=read_v2_checkpoint(svc.store.checkpoint_path,'run',run.id)['values']['model_tasks']
    assert len(records)==1 and next(iter(records.values()))['attempts']==1


async def test_request_index_window_reuses_registered_id_after_crash(tmp_path,monkeypatch):
    from resume_agent.model_tasks import ModelTaskRunner
    runtime,calls=host_runtime(tmp_path,monkeypatch)
    run=runtime.create_run(RunRequest(job_input='Python',input_type='text',execution_mode='host'))
    original=ModelTaskRunner._save
    class Crash(BaseException):
        pass
    def crash(self,key,record):
        if record.get('request_id'):
            raise Crash()
        original(self,key,record)
    monkeypatch.setattr(ModelTaskRunner,'_save',crash)
    with pytest.raises(Crash):
        await runtime.runs.drive(run.id)
    with runtime.store.connection() as conn:
        registered=conn.execute('SELECT request_id FROM external_model_requests').fetchone()[0]
    monkeypatch.setattr(ModelTaskRunner,'_save',original)
    runtime,_=host_runtime(tmp_path,monkeypatch)
    pending=(await runtime.runs.drive(run.id,Continue(action_id='resume'))).pending
    assert pending.request_id==registered and calls==[]


async def test_lookup_index_can_recover_from_checkpoint_and_cancel_stays_final(tmp_path,monkeypatch):
    runtime,calls=host_runtime(tmp_path,monkeypatch)
    run=runtime.create_run(RunRequest(job_input='Python',input_type='text',execution_mode='host'))
    pending=(await runtime.runs.drive(run.id)).pending
    with runtime.store.connection() as conn:
        conn.execute('DELETE FROM external_model_requests WHERE request_id=?',(pending.request_id,))
    next_view=await runtime.runs.drive(run.id,response(pending,{'company':'Example','role_title':'Engineer'}))
    with runtime.store.connection() as conn:
        assert conn.execute('SELECT owner_id FROM external_model_requests WHERE request_id=?',(pending.request_id,)).fetchone()[0]==run.id
    runtime.runs.cancel(run.id)
    with pytest.raises(Conflict):
        await runtime.runs.drive(run.id,response(next_view.pending,{'questions':[]},'after-cancel'))
    assert runtime.runs.get(run.id).status=='cancelled' and calls==[]


async def test_host_proposals_cannot_bypass_candidate_source_reference_validation(tmp_path,monkeypatch):
    from resume_agent.contracts import content_hash
    runtime,calls=host_runtime(tmp_path,monkeypatch)
    run=runtime.create_run(RunRequest(job_input='Python',input_type='text',execution_mode='host'))
    view=await runtime.runs.drive(run.id)
    view=await runtime.runs.drive(run.id,response(view.pending,{'company':'Example','role_title':'Engineer'},'jd'))
    view=await runtime.runs.drive(run.id,response(view.pending,{'questions':[]},'questions'))
    proposal={'id':'forged','operation':'replace','target_path':'/summary','source_revision':content_hash(PROFILE),
        'before_hash':content_hash(PROFILE.summary),'after':'An unsupported claim.',
        'source_refs':[{'kind':'profile','input_hash':'f'*64,'target_path':'/summary'}],'rationale':'Untrusted host result.'}
    view=await runtime.runs.drive(run.id,response(view.pending,{'proposals':[proposal]},'proposals'))
    assert view.status=='failed' and view.release is None
    assert view.diagnostics[0].code=='invalid_proposals' and runtime.profiles.load_snapshot().profile==PROFILE and calls==[]

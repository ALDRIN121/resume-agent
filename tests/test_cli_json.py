import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from tests.test_discovery_service import setup_discovery
from tests.test_evaluation_operations import setup_evaluation
from tests.test_v2_api import services


def invoke(tmp_path,monkeypatch,runtime,command,body=None,resource=None):
    import resume_agent.cli as module
    monkeypatch.setattr(module,'_career_runtime',lambda:runtime)
    args=['agent',command]
    if body is not None:
        source=tmp_path/'action.json';source.write_text(json.dumps(body,ensure_ascii=False))
        args+=['--input',str(source)]
    if resource:
        args+=['--resource',resource]
    result=CliRunner().invoke(module.app,args,input='')
    envelope=json.loads(result.stdout)
    assert set(envelope)=={'schema_version','ok','command','resource','data','next_action','error'}
    assert envelope['schema_version']==1 and envelope['command']==command
    return result,envelope


def test_start_inspect_preview_stale_response_and_cancel_never_prompt(tmp_path,monkeypatch):
    runtime,calls=services(tmp_path)
    marker=tmp_path/'must-not-exist'
    text=f'Python résumé role; $(touch {marker}) `echo text` & literal.'
    original=runtime.workflow.model
    async def noisy(stage,schema,messages):
        print('Model progress belongs on stderr.')
        return await original(stage,schema,messages)
    runtime.workflow.model=noisy
    result,envelope=invoke(tmp_path,monkeypatch,runtime,'start',{'job_input':text,'input_type':'text'})
    assert result.exit_code==0 and envelope['ok'],result.output
    assert 'Model progress' in result.stderr and 'Model progress' not in result.stdout
    assert envelope['next_action']['kind']=='present_suggestions'
    run_id=envelope['resource']['id'];resource='run:'+run_id
    assert runtime.store.input('run',run_id)['request']['job_input']==text and not marker.exists()
    count=len(calls)
    result,inspected=invoke(tmp_path,monkeypatch,runtime,'inspect',resource=resource)
    assert result.exit_code==0 and len(calls)==count
    pending=inspected['next_action']
    preview_body={'approved_ids':[],'review_id':pending['review_id'],'source_revision':pending['source_revision']}
    _,preview=invoke(tmp_path,monkeypatch,runtime,'inspect',preview_body,resource)
    assert preview['data']['content_preview']['manifest']['content_hash']==pending['content_hash']
    result,stale=invoke(tmp_path,monkeypatch,runtime,'respond',{'kind':'present_suggestions','action_id':'stale',
        'review_id':'stale','source_revision':pending['source_revision'],'approved_ids':[],'content_hash':pending['content_hash']},resource)
    assert result.exit_code==4 and not stale['ok']
    with runtime.store.connection() as conn:
        assert runtime.store.action('run',run_id,'stale',conn) is None and len(calls)==count
    result,cancelled=invoke(tmp_path,monkeypatch,runtime,'cancel',resource=resource)
    assert result.exit_code==0 and cancelled['data']['status']=='cancelled' and cancelled['next_action'] is None


def test_import_requires_review_and_acceptance_is_the_shared_typed_action(tmp_path,monkeypatch):
    runtime,calls=services(tmp_path)
    before=runtime.profiles.load_snapshot()
    path=tmp_path/'resume $(literal).tex';path.write_text('Casey Example\nPython engineer')
    result,envelope=invoke(tmp_path,monkeypatch,runtime,'import',{'source_path':str(path)})
    assert result.exit_code==0 and envelope['resource']['kind']=='profile_import'
    review=envelope['next_action']
    assert review['kind']=='import_review' and runtime.profiles.load_snapshot()==before
    action={key:review[key] for key in ['review_id','draft_hash','expected_profile_revision']}
    result,accepted=invoke(tmp_path,monkeypatch,runtime,'respond',{'kind':'accept_import','action_id':'accept-json',**action},
        'profile_import:'+envelope['resource']['id'])
    assert result.exit_code==0 and accepted['data']['status']=='complete'
    assert calls==['import_profile']


def test_evaluation_memory_and_application_commands_share_state(tmp_path,monkeypatch):
    runtime,job,calls=setup_evaluation(tmp_path)
    result,evaluated=invoke(tmp_path,monkeypatch,runtime,'evaluate',{'job_id':job.id})
    assert result.exit_code==0 and evaluated['resource']['kind']=='role_evaluation'
    assert evaluated['data']['result']['fit']['lower']==100 and len(calls)==1
    result,proposed=invoke(tmp_path,monkeypatch,runtime,'memory',{'op':'propose','payload':{
        'kind':'writing_rule','payload':{'instruction':'Preserve all metrics.'},'source_refs':[{'kind':'user_text','text':'My preference.'}]}})
    assert result.exit_code==0 and proposed['data']['status']=='pending'
    _,preview=invoke(tmp_path,monkeypatch,runtime,'memory',{'op':'inspect'},'memory:'+proposed['resource']['id'])
    assert preview['next_action']==proposed['next_action']
    result,accepted=invoke(tmp_path,monkeypatch,runtime,'memory',{'op':'decide','payload':{'decision':'accept',
        'expected_revision':proposed['data']['revision'],'action_id':'accept'}},'memory:'+proposed['resource']['id'])
    assert result.exit_code==0 and accepted['data']['status']=='accepted'
    result,application=invoke(tmp_path,monkeypatch,runtime,'application',{'op':'create','payload':{'job_id':job.id,'action_id':'plan'}})
    assert result.exit_code==0 and application['data']['stage']=='planned'
    result,submitted=invoke(tmp_path,monkeypatch,runtime,'application',{'op':'event','payload':{
        'expected_revision':application['data']['revision'],'action_id':'submit','event':{'kind':'submit','artifact_unknown':True,
        'evaluation_id':evaluated['resource']['id']}}},'application:'+application['resource']['id'])
    assert result.exit_code==0 and submitted['data']['submission']['evaluation']['lower_exact']==[100,1]
    assert len(calls)==1


def test_discovery_json_is_manual_and_preserves_partial_state(tmp_path,monkeypatch):
    runtime,feed,calls,configuration=setup_discovery(tmp_path)
    result,envelope=invoke(tmp_path,monkeypatch,runtime,'discover',{'op':'refresh','payload':{
        'expected_sources_revision':configuration['revision'],'action_id':'scan'}})
    assert result.exit_code==0 and envelope['data']['status']=='complete'
    feed.payload={'jobs':[{}]}
    result,partial=invoke(tmp_path,monkeypatch,runtime,'discover',{'op':'refresh','payload':{
        'expected_sources_revision':configuration['revision'],'action_id':'partial'}})
    assert result.exit_code==0 and partial['data']['status']=='partial'
    result,page=invoke(tmp_path,monkeypatch,runtime,'discover',{'op':'postings','payload':{'limit':1}})
    assert page['data']['total']==2 and page['data']['has_more'] and calls==[]
    result,cancelled=invoke(tmp_path,monkeypatch,runtime,'cancel',{'action_id':'cancel'},'discovery_sync:'+partial['resource']['id'])
    assert result.exit_code==0 and cancelled['data']['status']=='partial'


@pytest.mark.parametrize('command,body,resource,code',[
    ('unknown',None,None,1),('start',{'job_input':'x','input_type':'text','api_key':'secret'},None,1),
    ('inspect',None,'nonsense:id',1),('inspect',None,None,1),('inspect',None,'run:missing',1),
    ('respond',{'kind':'review_pdf'},'run:missing',1),
    ('start',{'job_input':'x','input_type':'text','execution_mode':'external_agent'},None,2),
    ('application',{'op':'list','payload':{'extra':'no'}},None,1),
])
def test_invalid_input_has_one_json_error_and_stable_exit(tmp_path,monkeypatch,command,body,resource,code):
    runtime,calls=services(tmp_path)
    result,envelope=invoke(tmp_path,monkeypatch,runtime,command,body,resource)
    assert result.exit_code==code and not envelope['ok'],result.output
    assert envelope['error']['code'] and calls==[]


def test_missing_prerequisites_and_bad_json_files_do_not_create_work(tmp_path,monkeypatch):
    runtime,calls=services(tmp_path)
    runtime.tool_finder=lambda _:None
    result,envelope=invoke(tmp_path,monkeypatch,runtime,'start',{'job_input':'Python','input_type':'text'})
    assert result.exit_code==2 and not envelope['ok'] and runtime.store.run_ids()==[]
    from resume_agent.cli import app
    source=tmp_path/'invalid.json';source.write_text('{bad')
    result=CliRunner().invoke(app,['agent','start','--input',str(source)],input='')
    assert result.exit_code==1 and json.loads(result.stdout)['error']['code']=='invalid_input'
    result=CliRunner().invoke(app,['agent','inspect','--unexpected'],input='')
    assert result.exit_code==1 and json.loads(result.stdout)['error']['code']=='invalid_input'


def test_real_process_with_closed_stdin_returns_json_instead_of_prompting():
    result=subprocess.run([sys.executable,'-c','from resume_agent.cli import app; app()',
        'agent','inspect','--resource','run:missing'],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=15)
    assert result.returncode==1 and json.loads(result.stdout)['ok'] is False


@pytest.mark.parametrize('arguments',[['start','--input'],['inspect','--resource'],[]])
def test_argument_errors_also_return_one_json_document(arguments):
    from resume_agent.cli import app
    result=CliRunner().invoke(app,['agent',*arguments],input='')
    assert result.exit_code==1 and json.loads(result.stdout)['error']['code']=='invalid_input'


def test_model_response_cannot_approve_content_or_create_an_action(tmp_path,monkeypatch):
    runtime,calls=services(tmp_path)
    _,created=invoke(tmp_path,monkeypatch,runtime,'start',{'job_input':'Python','input_type':'text'})
    resource=created['resource'];count=len(calls)
    result,envelope=invoke(tmp_path,monkeypatch,runtime,'respond',{'kind':'model_request','action_id':'host-result',
        'request_id':'fake','input_hash':'a'*64,'result':{'approved_ids':[]}},'run:'+resource['id'])
    assert result.exit_code==4 and envelope['error']['code']=='conflict'
    with runtime.store.connection() as conn:
        assert runtime.store.action('run',resource['id'],'host-result',conn) is None
    assert len(calls)==count


def test_execution_error_retains_created_resource_and_durable_review(tmp_path,monkeypatch):
    runtime,calls=services(tmp_path)
    original=runtime.runs.drive
    async def crash_after_pause(identifier,*args):
        await original(identifier,*args)
        raise OSError('Simulated response handoff failure.')
    monkeypatch.setattr(runtime.runs,'drive',crash_after_pause)
    result,envelope=invoke(tmp_path,monkeypatch,runtime,'start',{'job_input':'Python','input_type':'text'})
    assert result.exit_code==3 and envelope['resource']['kind']=='run'
    assert envelope['resource']['id']==runtime.store.run_ids()[0]
    assert envelope['data']['status']=='awaiting-input' and envelope['next_action']['kind']=='present_suggestions'
    count=len(calls)
    result,read=invoke(tmp_path,monkeypatch,runtime,'inspect',resource='run:'+envelope['resource']['id'])
    assert result.exit_code==0 and read['next_action']==envelope['next_action'] and len(calls)==count


def test_domain_creation_rejects_an_existing_resource_instead_of_ignoring_it(tmp_path,monkeypatch):
    runtime,job,calls=setup_evaluation(tmp_path)
    result,envelope=invoke(tmp_path,monkeypatch,runtime,'application',{'op':'create','payload':{
        'job_id':job.id,'action_id':'create'}},'memory:unrelated')
    assert result.exit_code==1 and runtime.applications.list()==[] and calls==[]


def test_saved_queued_work_can_be_executed_explicitly_without_an_approval(tmp_path,monkeypatch):
    from resume_agent.contracts import RunRequest
    runtime,calls=services(tmp_path)
    run=runtime.create_run(RunRequest(job_input='Python',input_type='text'))
    resource='run:'+run.id
    _,view=invoke(tmp_path,monkeypatch,runtime,'inspect',resource=resource)
    assert view['next_action']['kind']=='execute' and calls==[]
    result,paused=invoke(tmp_path,monkeypatch,runtime,'respond',resource=resource)
    assert result.exit_code==0 and paused['next_action']['kind']=='present_suggestions'
    result,blocked=invoke(tmp_path,monkeypatch,runtime,'respond',resource=resource)
    assert result.exit_code==4 and blocked['next_action']==paused['next_action']

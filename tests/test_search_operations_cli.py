import json

from typer.testing import CliRunner

from tests.test_discovery_service import setup_discovery


def test_discovery_and_application_cli_use_shared_state_without_prompts(tmp_path,monkeypatch):
    import resume_agent.runtime as module
    from resume_agent.cli import app
    runtime,feed,calls,configured=setup_discovery(tmp_path)
    monkeypatch.setattr(module,'Runtime',lambda **kwargs:runtime)
    cli=CliRunner()
    refresh=cli.invoke(app,['discover','refresh','--revision',configured['revision'],'--action-id','cli-refresh'],input='')
    assert refresh.exit_code==0,refresh.output
    assert 'complete' in refresh.output and len(feed.calls)==1 and calls==[]
    job=runtime.discovery.list_postings()[0]['job']
    postings=cli.invoke(app,['discover','postings'])
    assert postings.exit_code==0 and job['id'] in postings.output
    created=cli.invoke(app,['applications','create',job['id'],'--action-id','cli-plan'],input='')
    assert created.exit_code==0,created.output
    application=runtime.applications.list()[0]
    path=tmp_path/'event.json'
    path.write_text(json.dumps({'action_id':'cli-submit','expected_revision':application['revision'],
        'event':{'kind':'submit','artifact_unknown':True,'occurred_at':'2026-11-13'}}))
    recorded=cli.invoke(app,['applications','event',application['id'],'--file',str(path)],input='')
    assert recorded.exit_code==0,recorded.output
    assert runtime.applications.get(application['id'])['stage']=='submitted'
    assert cli.invoke(app,['applications','event',application['id'],'--file',str(path)]).exit_code==0
    assert len(runtime.applications.get(application['id'])['events'])==1
    path.write_text(json.dumps({'action_id':'new','expected_revision':application['revision'],'event':{'kind':'response_received','category':'favorable'}}))
    stale=cli.invoke(app,['applications','event',application['id'],'--file',str(path)])
    assert stale.exit_code==2 and len(runtime.applications.get(application['id'])['events'])==1


def test_discovery_cli_source_file_uses_revision_and_strict_schema(tmp_path,monkeypatch):
    import resume_agent.runtime as module
    from resume_agent.cli import app
    runtime,feed,calls,configured=setup_discovery(tmp_path)
    monkeypatch.setattr(module,'Runtime',lambda **kwargs:runtime)
    path=tmp_path/'sources.json'
    path.write_text(json.dumps({'sources':[{'provider':'lever','board':'fictional','region':'eu'}],
        'expected_revision':configured['revision'],'action_id':'cli-config'}))
    result=CliRunner().invoke(app,['discover','configure','--file',str(path)],input='')
    assert result.exit_code==0,result.output
    assert runtime.discovery.sources()['sources'][0]['region']=='eu'
    path.write_text(json.dumps({'sources':[],'expected_revision':runtime.discovery.sources()['revision'],'action_id':'bad','api_key':'secret'}))
    assert CliRunner().invoke(app,['discover','configure','--file',str(path)]).exit_code==2
    assert feed.calls==calls==[]

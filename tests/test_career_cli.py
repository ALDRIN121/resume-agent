from typer.testing import CliRunner

from tests.test_evaluation_operations import setup_evaluation


def test_jobs_evaluate_and_memory_cli_use_shared_services(tmp_path,monkeypatch):
    from resume_agent.cli import app
    import resume_agent.runtime as module
    runtime,job,_=setup_evaluation(tmp_path)
    monkeypatch.setattr(module,'Runtime',lambda **kwargs:runtime)
    cli=CliRunner()
    captured=cli.invoke(app,['jobs','capture','--text','Python','--source-key','manual:cli'])
    assert captured.exit_code==0,captured.output
    assert 'Job:' in captured.output
    evaluated=cli.invoke(app,['evaluate',job.id])
    assert evaluated.exit_code==0,evaluated.output
    assert '100' in evaluated.output and 'prioritize' in evaluated.output
    proposed=cli.invoke(app,['memory','propose','--kind','writing_rule','--instruction','Preserve exact metrics.',
                             '--source','My writing preference.'])
    assert proposed.exit_code==0,proposed.output
    record=runtime.memory.list()[0]
    assert record['status']=='pending'
    inspected=cli.invoke(app,['memory','inspect',record['id']])
    assert 'Preserve exact metrics.' in inspected.output and 'My writing preference.' in inspected.output
    accepted=cli.invoke(app,['memory','decide',record['id'],'--decision','accept',
                            '--revision',record['revision'],'--action-id','cli-accept'])
    assert accepted.exit_code==0,accepted.output
    assert runtime.memory.get(record['id'])['status']=='accepted'


def test_cli_tailoring_uses_selected_job_and_requires_advisory_override(tmp_path,monkeypatch):
    import asyncio
    from resume_agent.cli import app
    import resume_agent.runtime as module
    def unknown(response,fixed):
        response['findings'][0].update(status='unknown',sources=[])
        return response
    runtime,job,_=setup_evaluation(tmp_path,unknown)
    evaluation=asyncio.run(runtime.evaluations.drive(runtime.evaluations.create(job.id)['id']))
    monkeypatch.setattr(module,'Runtime',lambda **kwargs:runtime)
    cli=CliRunner()
    blocked=cli.invoke(app,['jobs','tailor',job.id,'--evaluation',evaluation['id']])
    assert blocked.exit_code==2 and runtime.store.run_ids()==[]
    pending=cli.invoke(app,['jobs','tailor',job.id,'--evaluation',evaluation['id'],'--override'])
    assert pending.exit_code==2,pending.output
    assert len(runtime.store.run_ids())==1
    fixed=runtime.store.input('run',runtime.store.run_ids()[0])
    assert fixed['request']['job_input']==job.text and fixed['request']['evaluation_override']

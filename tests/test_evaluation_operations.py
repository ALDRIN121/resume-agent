import json

import pytest

from resume_agent.contracts import Continue, content_hash
from tests.test_v2_api import services


def analysis(fixed):
    from tests.test_role_evaluation import criterion, group
    text=fixed['job']['text']
    return {'requirements':[group('g',[criterion('python',text)])],
            'findings':[{'member_id':'python','status':'supported','rationale':'Explicit profile summary.',
                'sources':[{'kind':'profile','input_hash':fixed['profile_revision'],'target_path':'/summary','quote':'Python'}]}],
            'eligibility':[]}


def setup_evaluation(tmp_path,transform=None):
    runtime,_=services(tmp_path)
    current=runtime.profiles.load_snapshot()
    profile=current.profile.model_copy(deep=True)
    profile.summary='Python engineer.'
    runtime.profiles.save_reviewed(current.revision,profile,{})
    calls=[]
    async def model(stage,schema,messages):
        fixed=json.loads(messages[-1]['content'])
        calls.append(fixed)
        response=analysis(fixed)
        return transform(response,fixed) if transform else response
    runtime.evaluations.model=model
    job=runtime.jobs.capture('Python',source_key='role:example')
    return runtime,job,calls


@pytest.mark.asyncio
async def test_evaluation_freezes_inputs_and_staleness_never_rewrites_result(tmp_path):
    runtime,job,calls=setup_evaluation(tmp_path)
    operation=runtime.evaluations.create(job.id)
    current=runtime.profiles.load_snapshot()
    updated=current.profile.model_copy(deep=True)
    updated.summary='A later manual edit.'
    runtime.profiles.save_reviewed(current.revision,updated,{})
    result=await runtime.evaluations.drive(operation['id'])
    assert result['status']=='complete'
    assert result['result']['fit']['lower']==100
    assert result['stale'] and 'profile' in result['stale_reasons']
    assert calls[0]['profile_snapshot']['summary']=='Python engineer.'
    stored=runtime.store.row('operation',operation['id'])['result_json']
    runtime.jobs.capture('Changed role',source_key='role:example')
    read=runtime.evaluations.get(operation['id'])
    assert 'job' in read['stale_reasons']
    assert runtime.store.row('operation',operation['id'])['result_json']==stored
    assert len(calls)==1


async def test_evaluation_supplies_exact_job_spans_without_changing_fixed_inputs(tmp_path):
    runtime, job, calls = setup_evaluation(tmp_path)
    operation = runtime.evaluations.create(job.id)
    before = runtime.store.input('operation', operation['id'])
    result = await runtime.evaluations.drive(operation['id'])
    assert result['status'] == 'complete'
    assert calls[0]['job_citations'] == [{'start': 0, 'end': 6, 'quote': 'Python'}]
    assert calls[0]['job']['text'] == before['job']['text']
    assert runtime.store.input('operation', operation['id']) == before


@pytest.mark.parametrize('text', [
    'Python required. Docker preferred.\nHybrid in Bengaluru.',
    '  C++ and .NET 8.0 required.\nCafé résumé review.  ',
    'Python required. Python required.',
    'One line without sentence punctuation',
])
def test_job_citation_catalog_uses_exact_unicode_offsets_and_keeps_every_word(text):
    from resume_agent.role_evaluation import job_citation_catalog

    citations = job_citation_catalog(text)
    assert citations
    assert all(text[c['start']:c['end']] == c['quote'] for c in citations)
    assert ''.join(''.join(c['quote'].split()) for c in citations) == ''.join(text.split())
    assert all(a['end'] <= b['start'] for a, b in zip(citations, citations[1:]))


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary',['after_model','after_result_checkpoint','after_result_index'])
async def test_evaluation_restart_reuses_model_and_result(tmp_path,boundary):
    from resume_agent.runtime import Runtime
    runtime,job,calls=setup_evaluation(tmp_path)
    operation=runtime.evaluations.create(job.id)
    class Crash(BaseException):
        pass
    def crash(stage):
        if stage==boundary:
            raise Crash()
    runtime.evaluations.crash_hook=crash
    with pytest.raises(Crash):
        await runtime.evaluations.drive(operation['id'])
    reopened=Runtime(root=tmp_path,settings=runtime.settings,model=runtime.evaluations.model,tool_finder=lambda _: '/tool')
    view=reopened.evaluations.get(operation['id'])
    if view['status']!='complete':
        view=await reopened.evaluations.drive(operation['id'],Continue(action_id='continue'))
    assert view['status']=='complete' and view['result']['fit']['lower']==100, view
    assert len(calls)==1
    with reopened.store.connection() as conn:
        assert conn.execute('SELECT count(*) FROM career_evaluations').fetchone()[0]==1


@pytest.mark.asyncio
@pytest.mark.parametrize('bad',['span','hash','path','missing_source','identity_eligibility','writing_rule_evidence'])
async def test_invalid_evidence_does_not_produce_a_score(tmp_path,bad):
    def transform(response,fixed):
        finding=response['findings'][0]
        if bad=='span':
            response['requirements'][0]['members'][0]['citations'][0]['end']+=1
        elif bad=='hash':
            finding['sources'][0]['input_hash']='f'*64
        elif bad=='path':
            finding['sources'][0]['target_path']='/missing'
        elif bad=='missing_source':
            finding['sources']=[]
        elif bad=='identity_eligibility':
            response['eligibility']=[{'category':'authorization','status':'fail','rationale':'Inferred from name.',
                'citation':{'start':0,'end':6,'quote':'Python'},'sources':[{
                    'kind':'profile','input_hash':fixed['profile_revision'],'target_path':'/personal/full_name','quote':'Ada'}]}]
        else:
            finding['sources']=[{'kind':'memory','input_hash':fixed['memory_revision'],
                                 'target_path':'/records/0/payload/instruction','quote':'Prefer Python'}]
        return response
    runtime,job,calls=setup_evaluation(tmp_path,transform)
    view=await runtime.evaluations.drive(runtime.evaluations.create(job.id)['id'])
    assert view['status']=='failed' and view['result'] is None
    assert view['diagnostics'][0]['code']=='invalid_evaluation_evidence'
    assert len(calls)==1


@pytest.mark.asyncio
async def test_explicit_eligibility_and_cancel_are_separate_from_fit(tmp_path):
    def transform(response,fixed):
        response['eligibility']=[{'category':'authorization','status':'fail','rationale':'Explicit sponsorship restriction.',
            'citation':{'start':0,'end':6,'quote':'Python'},'sources':[{'kind':'eligibility',
            'input_hash':content_hash(fixed['eligibility_facts']),'target_path':'/authorization','quote':'I require sponsorship.'}]}]
        return response
    runtime,job,calls=setup_evaluation(tmp_path,transform)
    op=runtime.evaluations.create(job.id,eligibility_facts={'authorization':'I require sponsorship.'})
    done=await runtime.evaluations.drive(op['id'])
    assert done['result']['fit']['lower']==100
    assert done['result']['eligibility_status']=='fail'
    assert done['result']['fit']['recommendation']=='skip'
    cancelled=runtime.evaluations.create(job.id)
    assert runtime.evaluations.cancel(cancelled['id'])['status']=='cancelled'
    assert len(calls)==1


@pytest.mark.asyncio
async def test_memory_is_frozen_for_evaluation_and_later_revocation_marks_stale(tmp_path):
    from tests.test_memory import decide,propose
    runtime,job,calls=setup_evaluation(tmp_path)
    record=decide(runtime.memory,propose(runtime.memory,'target_preference',{'preferred_locations':['Berlin']}))
    op=runtime.evaluations.create(job.id)
    frozen=runtime.store.input('operation',op['id'])
    decide(runtime.memory,record,'revoke',action='revoke')
    done=await runtime.evaluations.drive(op['id'])
    assert done['stale'] and 'memory' in done['stale_reasons']
    assert calls[0]['memory_snapshot']==frozen['memory_snapshot']
    assert frozen['memory_snapshot']['records'][0]['id']==record['id']


@pytest.mark.asyncio
async def test_cancel_during_evaluation_never_publishes_result(tmp_path):
    import asyncio
    runtime,job,calls=setup_evaluation(tmp_path)
    entered,finish=asyncio.Event(),asyncio.Event()
    original=runtime.evaluations.model
    async def model(stage,schema,messages):
        entered.set()
        await finish.wait()
        return await original(stage,schema,messages)
    runtime.evaluations.model=model
    op=runtime.evaluations.create(job.id)
    task=asyncio.create_task(runtime.evaluations.drive(op['id']))
    await entered.wait()
    runtime.evaluations.cancel(op['id'])
    finish.set()
    done=await task
    assert done['status']=='cancelled' and done['result'] is None
    with runtime.store.connection() as conn:
        assert conn.execute('SELECT count(*) FROM career_evaluations').fetchone()[0]==0


@pytest.mark.asyncio
async def test_hard_model_interruptions_preserve_two_attempt_budget(tmp_path):
    from resume_agent.runtime import Runtime
    runtime,job,calls=setup_evaluation(tmp_path)
    class Crash(BaseException):
        pass
    count=0
    async def crash(stage,schema,messages):
        nonlocal count
        count+=1
        raise Crash()
    runtime.evaluations.model=crash
    op=runtime.evaluations.create(job.id)
    for index in range(2):
        with pytest.raises(Crash):
            await runtime.evaluations.drive(op['id'],None if index==0 else Continue(action_id='again'))
        runtime=Runtime(root=tmp_path,settings=runtime.settings,model=crash)
    done=await runtime.evaluations.drive(op['id'],Continue(action_id='exhausted'))
    assert done['status']=='failed' and done['result'] is None
    assert done['diagnostics'][0]['code']=='task_budget_exhausted'
    assert count==2


def test_unicode_citations_resolve_exact_codepoint_offsets_and_missing_evidence_stays_unknown(tmp_path):
    from resume_agent.role_evaluation import validate_analysis,score_fit
    from tests.test_role_evaluation import group,criterion,finding
    runtime,job,_=setup_evaluation(tmp_path)
    unicode_job=runtime.jobs.capture('👩‍💻 Python')
    op=runtime.evaluations.create(unicode_job.id)
    fixed=runtime.store.input('operation',op['id'])
    member=criterion('a','Python')
    member['citations']=[{'start':4,'end':10,'quote':'Python'}]
    valid,eligibility,resolved=validate_analysis({'requirements':[group('g',[member])],
        'findings':[finding('a','unknown')],'eligibility':[]},fixed)
    score=score_fit(valid.requirements,valid.findings,eligibility=eligibility)
    assert score['lower']==0 and score['upper']==100 and score['coverage']==0
    assert resolved==[]

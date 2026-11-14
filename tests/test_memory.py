"""Reviewed memory uses real SQLite and canonical profile writes."""
import pytest

from resume_agent.contracts import RunRequest, content_hash
from resume_agent.run_store import Conflict
from tests.test_v2_api import services


@pytest.fixture
def memory(tmp_path):
    from resume_agent.memory import MemoryService
    runtime, _ = services(tmp_path)
    return MemoryService(runtime.store, runtime.profiles), runtime


def propose(service, kind='writing_rule', payload=None, **extra):
    return service.propose({'kind':kind,'payload':payload or {'instruction':'Use concise sentences.'},
        'source_refs':[{'kind':'user_text','text':'Please use concise sentences.'}],**extra})


def decide(service, record, decision='accept', action='decision', **extra):
    return service.decide(record['id'],decision,expected_revision=record['revision'],action_id=action,**extra)


def test_reject_keeps_profile_and_active_memory_but_retains_audit(memory):
    service, runtime = memory
    before = runtime.profiles.load_snapshot()
    snapshot = service.snapshot()
    record = propose(service)
    result = decide(service,record,'reject')
    assert result['status'] == 'rejected'
    assert service.snapshot() == snapshot
    assert runtime.profiles.load_snapshot() == before
    assert service.history(record['id'])[0]['decision'] == 'reject'


def test_accept_once_replay_conflicting_reuse_and_stale_revision(memory):
    service, _ = memory
    record = propose(service)
    accepted = decide(service,record)
    assert accepted['status'] == 'accepted'
    assert decide(service,record) == accepted
    with pytest.raises(Conflict):
        decide(service,record,'reject')
    with pytest.raises(Conflict):
        decide(service,record,action='stale')
    assert len(service.history(record['id'])) == 1
    frozen = service.snapshot()
    revoked = decide(service,accepted,'revoke',action='revoke')
    assert revoked['status'] == 'revoked' and service.snapshot()['records'] == []
    assert frozen['records'][0]['id'] == record['id']


def test_superseding_rule_keeps_old_record_and_requires_current_revision(memory):
    service, _ = memory
    old = decide(service,propose(service))
    replacement = propose(service,payload={'instruction':'Preserve exact metric wording.'},
                          supersedes={'id':old['id'],'revision':old['revision']})
    new = decide(service,replacement,action='replace')
    assert service.get(old['id'])['status'] == 'superseded'
    assert [r['id'] for r in service.snapshot()['records']] == [new['id']]


def fact(service, runtime):
    current = runtime.profiles.load_snapshot()
    return propose(service,'candidate_fact',{'operation':'replace','target_path':'/personal/full_name',
        'before_hash':content_hash('Ada'),'after':'Ada Example'},base_profile_revision=current.revision)


def test_fact_preview_and_promotion_change_only_reviewed_target(memory):
    service, runtime = memory
    before = runtime.profiles.load_snapshot()
    record = fact(service,runtime)
    preview = service.preview(record['id'])
    assert preview['before'] == 'Ada' and preview['after'] == 'Ada Example'
    assert runtime.profiles.load_snapshot() == before
    accepted = decide(service,record)
    assert accepted['status'] == 'accepted'
    expected = before.profile.model_copy(deep=True)
    expected.personal.full_name = 'Ada Example'
    current = runtime.profiles.load_snapshot()
    assert current.profile == expected and not current.review_required
    assert service.snapshot()['records'] == []
    assert service.preview(record['id'])['after'] == 'Ada Example'
    with pytest.raises(Conflict):
        decide(service,accepted,'revoke',action='undo')


@pytest.mark.parametrize('boundary',['before_profile_write','after_profile_write'])
def test_fact_crash_is_inspected_and_requires_explicit_retry_when_old(memory,boundary):
    from resume_agent.memory import MemoryService
    service, runtime = memory
    record = fact(service,runtime)

    class Crash(BaseException):
        pass

    def crash(stage):
        if stage == boundary:
            raise Crash()

    service.crash_hook = crash
    with pytest.raises(Crash):
        decide(service,record)
    reopened = MemoryService(runtime.store,runtime.profiles)
    if boundary == 'before_profile_write':
        assert runtime.profiles.load_snapshot().profile.personal.full_name == 'Ada'
        assert reopened.get(record['id'])['status'] == 'applying'
        assert decide(reopened,record)['status'] == 'accepted'
    else:
        assert reopened.get(record['id'])['status'] == 'accepted'
        assert decide(reopened,record)['status'] == 'accepted'
    assert runtime.profiles.load_snapshot().profile.personal.full_name == 'Ada Example'
    assert len(reopened.history(record['id'])) == 1


def test_unrelated_profile_change_blocks_interrupted_fact(memory):
    from resume_agent.memory import MemoryService
    service, runtime = memory
    record = fact(service,runtime)
    def crash(stage):
        if stage == 'before_profile_write':
            raise KeyboardInterrupt()
    service.crash_hook = crash
    with pytest.raises(KeyboardInterrupt):
        decide(service,record)
    current = runtime.profiles.load_snapshot()
    profile = current.profile.model_copy(deep=True)
    profile.summary = 'A separate manual correction.'
    runtime.profiles.save_reviewed(current.revision,profile,{})
    reopened = MemoryService(runtime.store,runtime.profiles)
    assert reopened.get(record['id'])['status'] == 'conflict'
    with pytest.raises(Conflict):
        decide(reopened,record)
    assert runtime.profiles.load_snapshot().profile.summary == profile.summary


@pytest.mark.parametrize('path',['/api_key','/work_preferences/work_modes','/personal/missing',''])
def test_unsupported_fact_targets_are_rejected(memory,path):
    service, runtime = memory
    with pytest.raises(ValueError):
        propose(service,'candidate_fact',{'operation':'replace','target_path':path,
            'before_hash':content_hash(None),'after':'unsafe'},
            base_profile_revision=runtime.profiles.load_snapshot().revision)


@pytest.mark.asyncio
async def test_future_runs_freeze_rules_earlier_runs_do_not_change(memory):
    service, runtime = memory
    runtime.memory = service
    first = runtime.create_run(RunRequest(job_input='Engineer',input_type='text'))
    accepted = decide(service,propose(service))
    second = runtime.create_run(RunRequest(job_input='Engineer',input_type='text'))
    fixed = runtime.store.input('run',second.id)
    assert fixed['memory_snapshot']['records'][0]['id'] == accepted['id']
    assert fixed['memory_revision'] == content_hash(fixed['memory_snapshot'])
    assert runtime.store.input('run',first.id)['memory_snapshot']['records'] == []
    decide(service,accepted,'revoke',action='revoke')
    assert runtime.store.input('run',second.id) == fixed
    calls = []
    original = runtime.workflow.model
    async def model(stage,schema,messages):
        calls.append((stage,messages))
        return await original(stage,schema,messages)
    runtime.workflow.model = model
    await runtime.runs.drive(second.id)
    proposal_messages = next(messages for stage,messages in calls if stage == 'proposals')
    assert any('Use concise sentences.' in message['content'] for message in proposal_messages)
    assert any('never candidate-fact evidence' in message['content'] for message in proposal_messages)


def test_target_preferences_keep_typed_explicit_constraints_and_detached_snapshots(memory):
    service, _ = memory
    record = propose(service,'target_preference',{'preferred_locations':['Berlin'], 'work_modes':['Remote'],
        'hard_constraints':[{'category':'authorization','value':'Needs sponsorship','text':'I need employer sponsorship.'}]})
    accepted = decide(service,record)
    snapshot = service.snapshot()
    snapshot['records'][0]['payload']['preferred_locations'].append('Changed externally')
    assert service.snapshot()['records'][0]['payload']['preferred_locations'] == ['Berlin']
    replacement = propose(service,'target_preference',{'preferred_locations':['London']},
                          supersedes={'id':accepted['id'],'revision':accepted['revision']})
    decide(service,accepted,'revoke',action='revoke')
    with pytest.raises(Conflict):
        decide(service,replacement,action='replace')
    assert service.get(replacement['id'])['status'] == 'pending'


def test_memory_snapshot_hash_and_schema_are_validated(memory):
    from resume_agent.contracts import FixedRunInput
    service, runtime = memory
    decide(service,propose(service))
    run = runtime.create_run(RunRequest(job_input='Engineer',input_type='text'))
    fixed = runtime.store.input('run',run.id)
    FixedRunInput.model_validate(fixed)
    fixed['memory_snapshot']['records'][0]['payload']['instruction'] = 'Changed'
    with pytest.raises(ValueError):
        FixedRunInput.model_validate(fixed)
    fixed['memory_snapshot']['schema_version'] = 99
    fixed['memory_revision'] = content_hash(fixed['memory_snapshot'])
    with pytest.raises(ValueError):
        FixedRunInput.model_validate(fixed)


def test_pending_fact_keeps_original_review_values_when_current_profile_drifts(memory):
    service, runtime = memory
    record = fact(service,runtime)
    current = runtime.profiles.load_snapshot()
    changed = current.profile.model_copy(deep=True)
    changed.personal.full_name = 'A separate correction'
    runtime.profiles.save_reviewed(current.revision,changed,{})
    preview = service.preview(record['id'])
    assert preview['before'] == 'Ada' and preview['after'] == 'Ada Example'
    assert preview['stale']
    with pytest.raises(Conflict):
        decide(service,record)
    assert runtime.profiles.load_snapshot().profile == changed
    assert service.history(record['id']) == []


def test_fact_origin_is_retained_in_future_run_provenance(memory):
    service, runtime = memory
    record = fact(service,runtime)
    decide(service,record)
    run = runtime.create_run(RunRequest(job_input='Engineer',input_type='text'))
    assert runtime.store.input('run',run.id)['profile_provenance']['memory_id'] == record['id']


def test_startup_can_inspect_memory_while_another_process_owns_decisions(memory):
    from resume_agent.memory import MemoryService
    service, runtime = memory
    with runtime.store.ownership('operation','memory-decisions'):
        other = MemoryService(runtime.store,runtime.profiles)
        assert other.snapshot() == service.snapshot()


def test_fact_append_validates_complete_profile_and_stale_profile_never_writes(memory):
    service, runtime = memory
    current = runtime.profiles.load_snapshot()
    record = propose(service,'candidate_fact',{'operation':'append','target_path':'/experience',
        'before_hash':content_hash([]),'after':{'company':'Example','title':'Engineer','start':'2023',
        'end':None,'location':None,'bullets':['Built the tool.'],'tech':[]}},base_profile_revision=current.revision)
    decide(service,record)
    assert runtime.profiles.load_snapshot().profile.experience[0].company == 'Example'
    with pytest.raises(Conflict):
        propose(service,'candidate_fact',{'operation':'replace','target_path':'/summary',
            'before_hash':content_hash(current.profile.summary),'after':'A stale edit.'},
            base_profile_revision=current.revision)


def test_version_one_database_gains_memory_without_rewriting_legacy_input(tmp_path):
    from resume_agent.migrations import MIGRATIONS, migrate
    from resume_agent.run_service import RunService
    from resume_agent.run_store import RunStore
    from tests.test_v2_workflow import PROFILE
    import sqlite3
    path = tmp_path/'library.sqlite'
    migrate(path,migrations=MIGRATIONS[:1])
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO migration_meta VALUES ('preserved','legacy-value')")
    store = RunStore(path,tmp_path/'state.sqlite')
    run = RunService(store).create(RunRequest(job_input='Engineer',input_type='text'),profile_snapshot=PROFILE)
    assert store.input('run',run.id)['memory_snapshot'] == {}
    with store.connection() as conn:
        assert conn.execute("SELECT value FROM migration_meta WHERE key='preserved'").fetchone()[0] == 'legacy-value'
        assert conn.execute('SELECT count(*) FROM memory_records').fetchone()[0] == 0
    assert path.with_suffix('.sqlite.pre-v2.bak').exists()

"""Explicit applications and append-only correction history in real SQLite."""
from pathlib import Path

import pytest

from resume_agent.run_store import Conflict
from tests.test_evaluation_operations import setup_evaluation
from tests.test_release_service import setup as released_setup, release  # noqa: F401


def event(service,view,payload,action='event'):
    return service.append(view['id'],payload,expected_revision=view['revision'],action_id=action)


def planned(runtime,job,action='plan'):
    return runtime.applications.create(job.id,action_id=action)


def test_creation_is_planned_and_submission_is_always_explicit(tmp_path):
    runtime,job,_=setup_evaluation(tmp_path)
    assert runtime.applications.list()==[]
    view=planned(runtime,job)
    assert view['stage']=='planned' and view['submission'] is None
    assert planned(runtime,job)==view
    submitted=event(runtime.applications,view,{'kind':'submit','artifact_unknown':True})
    assert submitted['stage']=='submitted'
    assert submitted['submission']['artifact_unknown']
    assert submitted['submission']['evaluation'] is None
    assert submitted['events'][0]['payload']['occurred_at'] is None
    assert submitted['events'][0]['recorded_at']
    assert event(runtime.applications,view,{'kind':'submit','artifact_unknown':True})==submitted
    with pytest.raises(Conflict):
        event(runtime.applications,view,{'kind':'response_received','category':'acknowledgment'})
    with pytest.raises(Conflict):
        event(runtime.applications,view,{'kind':'submit','artifact_unknown':True},action='stale')
    with pytest.raises(Conflict):
        event(runtime.applications,submitted,{'kind':'submit','artifact_unknown':True},action='duplicate-submit')


def test_forward_progress_unknown_dates_and_explicit_reopen(tmp_path):
    runtime,job,_=setup_evaluation(tmp_path)
    view=planned(runtime,job)
    advanced=event(runtime.applications,view,{'kind':'stage_change','stage':'interviewing'})
    assert advanced['stage']=='interviewing' and advanced['submission'] is None
    assert advanced['events'][0]['payload']['occurred_at'] is None
    with pytest.raises(Conflict):
        event(runtime.applications,advanced,{'kind':'stage_change','stage':'screening'},action='backward')
    submitted=event(runtime.applications,advanced,{'kind':'submit','artifact_unknown':True,'occurred_at':'2026-01-02'},action='record-missing-submit')
    assert submitted['stage']=='interviewing'
    assert submitted['submission']['occurred_at']=='2026-01-02'
    rejected=event(runtime.applications,submitted,{'kind':'stage_change','stage':'rejected'},action='rejected')
    with pytest.raises(Conflict):
        event(runtime.applications,rejected,{'kind':'stage_change','stage':'interviewing'},action='resurrection')
    reopened=event(runtime.applications,rejected,{'kind':'reopen','stage':'screening','reason':'Recruiter reopened the process.'},action='reopen')
    assert reopened['stage']=='screening' and reopened['submission']==submitted['submission']


def test_corrections_preserve_original_events_and_can_invalidate_wrong_positive(tmp_path):
    runtime,job,_=setup_evaluation(tmp_path)
    view=event(runtime.applications,planned(runtime,job),{'kind':'submit','artifact_unknown':True})
    favorable=event(runtime.applications,view,{'kind':'response_received','category':'favorable'},action='reply')
    rejected=event(runtime.applications,favorable,{'kind':'stage_change','stage':'rejected'},action='reject')
    assert any(e['payload'].get('category')=='favorable' for e in rejected['effective_events'])
    corrected=event(runtime.applications,rejected,{'kind':'correction','target_event_id':favorable['events'][-1]['id'],
        'reason':'The message was only an automated acknowledgment.','replacement':{'kind':'response_received','category':'acknowledgment'}},action='correct')
    assert len(corrected['events'])==4
    assert corrected['events'][1]['payload']['category']=='favorable'
    assert not any(e['payload'].get('category')=='favorable' for e in corrected['effective_events'])
    assert corrected['stage']=='rejected'
    with pytest.raises(Conflict):
        event(runtime.applications,corrected,{'kind':'correction','target_event_id':corrected['events'][-1]['id'],
            'reason':'Cannot target a correction.'},action='invalid-correction')


@pytest.mark.asyncio
async def test_submission_freezes_chosen_artifact_and_score_even_after_file_loss(tmp_path,released_setup):
    runtime,job,_=setup_evaluation(tmp_path)
    complete=release(released_setup)
    assert runtime.applications.list()==[]
    evaluation=await runtime.evaluations.drive(runtime.evaluations.create(job.id)['id'])
    submitted=event(runtime.applications,planned(runtime,job),{'kind':'submit','artifact_run_id':complete.id,
        'evaluation_id':evaluation['id']})
    evidence=submitted['submission']
    assert evidence['artifact']['pdf_hash']==complete.release.pdf_hash
    assert evidence['evaluation']['lower_exact']==[100,1]
    assert evidence['artifact']['available']
    current=runtime.profiles.load_snapshot()
    changed=current.profile.model_copy(deep=True)
    changed.summary='A later profile.'
    runtime.profiles.save_reviewed(current.revision,changed,{})
    Path(complete.release.canonical_pdf_path).unlink()
    missing=runtime.applications.get(submitted['id'])
    assert not missing['submission']['artifact']['available']
    assert missing['submission']['artifact']['pdf_hash']==complete.release.pdf_hash
    assert missing['submission']['evaluation']==evidence['evaluation']
    assert missing['revision']==submitted['revision']


def test_artifact_choice_and_response_category_are_required(tmp_path):
    runtime,job,_=setup_evaluation(tmp_path)
    view=planned(runtime,job)
    for payload in [{'kind':'submit'},{'kind':'submit','artifact_unknown':True,'artifact_run_id':'other'},
                    {'kind':'response_received'},{'kind':'stage_change','stage':'submitted'},
                    {'kind':'stage_change','stage':'closed','occurred_at':'not-a-date'},
                    {'kind':'reopen','stage':'planned','reason':'   '}]:
        with pytest.raises(ValueError):
            event(runtime.applications,view,payload)
    assert runtime.applications.get(view['id'])['events']==[]


def test_company_with_job_is_retained_after_last_legacy_resume_is_deleted(tmp_path):
    from resume_agent import library
    runtime,job,_=setup_evaluation(tmp_path)
    runtime.jobs.capture('Python role',company='Retained Company')
    library.upsert_resume(thread_id='legacy',company='Retained Company',status='failed',library_path=runtime.store.library_path)
    assert library.delete_resume('legacy',library_path=runtime.store.library_path)
    with runtime.store.connection() as conn:
        assert conn.execute("SELECT name FROM companies WHERE name='Retained Company'").fetchone()


def test_application_confirmed_company_is_retained_without_resumes(tmp_path):
    from resume_agent import library
    runtime,job,_=setup_evaluation(tmp_path)
    runtime.applications.create(job.id,action_id='plan',company='User Confirmed Company')
    library.upsert_resume(thread_id='legacy',company='User Confirmed Company',status='failed',library_path=runtime.store.library_path)
    library.delete_resume('legacy',library_path=runtime.store.library_path)
    with runtime.store.connection() as conn:
        assert conn.execute("SELECT name FROM companies WHERE name='User Confirmed Company'").fetchone()


def test_event_and_replay_intent_roll_back_together_on_persistence_failure(tmp_path):
    import sqlite3
    runtime,job,_=setup_evaluation(tmp_path)
    view=planned(runtime,job)
    with runtime.store.connection() as conn:
        conn.execute("CREATE TRIGGER block_event BEFORE INSERT ON application_events BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    with pytest.raises(sqlite3.Error):
        event(runtime.applications,view,{'kind':'submit','artifact_unknown':True})
    assert runtime.applications.get(view['id'])==view
    with runtime.store.connection() as conn:
        assert runtime.store.action('application_event',view['id'],'event',conn) is None
        conn.execute('DROP TRIGGER block_event')
    assert event(runtime.applications,view,{'kind':'submit','artifact_unknown':True})['stage']=='submitted'


def test_correction_is_scoped_and_can_remove_false_submission_without_deleting_audit(tmp_path):
    runtime,job,_=setup_evaluation(tmp_path)
    first=event(runtime.applications,planned(runtime,job),{'kind':'submit','artifact_unknown':True})
    second=planned(runtime,job,action='second-attempt')
    payload={'kind':'correction','target_event_id':first['events'][0]['id'],'reason':'This never happened.'}
    with pytest.raises(Conflict):
        event(runtime.applications,second,payload)
    corrected=event(runtime.applications,first,payload,action='correct')
    assert corrected['stage']=='planned' and corrected['submission'] is None
    assert len(corrected['events'])==2 and corrected['events'][0]['payload']['kind']=='submit'

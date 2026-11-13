"""Descriptive rates use explicit effective events and frozen unrounded scores."""
from fractions import Fraction

import pytest

from tests.test_applications import event,planned
from tests.test_evaluation_operations import setup_evaluation


def application(score=75,*,stage='submitted',events=None,submitted=True,rubric='fit-v1'):
    lower=Fraction(score) if score is not None else None
    return {'id':'fixture','stage':stage,'effective_events':[{'payload':p} for p in events or []],
            'submission':{'evaluation':{'lower_exact':list(lower.as_integer_ratio()) if lower is not None else None,
                                        'rubric_version':rubric}} if submitted else None}


def test_small_samples_and_pending_withdrawals_do_not_inflate_denominators():
    from resume_agent.outcomes import make_report
    positive={'kind':'response_received','category':'favorable'}
    negative={'kind':'stage_change','stage':'rejected'}
    apps=[application(events=[positive]) for _ in range(8)]+[application(stage='rejected',events=[negative])]
    apps += [application(),application(stage='withdrawn'),application(stage='closed')]
    report=make_report(apps)
    high=report['bands'][2]
    assert high['resolved']==9 and high['positive_rate'] is None
    assert high['pending']==1 and high['withdrawn']==1 and high['closed_unclassified']==1
    report=make_report(apps+[application(stage='rejected',events=[negative])])
    high=report['bands'][2]
    assert high['resolved']==10 and high['positive_rate']==80
    assert report['unique_excluded']==3


@pytest.mark.parametrize('score,band',[(Fraction(399999,10000),0),(40,1),(Fraction(699999,10000),1),(70,2),(100,2)])
def test_band_boundaries_use_frozen_exact_lower(score,band):
    from resume_agent.outcomes import make_report
    report=make_report([application(score,events=[{'kind':'response_received','category':'favorable'}])])
    assert report['bands'][band]['positive']==1
    assert sum(b['positive'] for b in report['bands'])==1


def test_unknown_score_unsupported_rubric_and_missing_submission_remain_explicit():
    from resume_agent.outcomes import make_report
    apps=[application(None),application(80,rubric='fit-future'),application(submitted=False)]
    report=make_report(apps)
    assert report['counts']['submitted']==2
    assert report['counts']['unknown_score']==1
    assert report['exclusions']['without_submission']==1
    assert report['exclusions']['unsupported_rubric']==1
    assert report['unique_excluded']==3
    assert sum(row['resolved'] for row in report['bands'])==0


@pytest.mark.parametrize('category',['acknowledgment','other'])
def test_generic_responses_never_count_as_positive(category):
    from resume_agent.outcomes import make_report
    report=make_report([application(events=[{'kind':'response_received','category':category}])])
    assert report['counts']['positive']==0 and report['counts']['pending']==1


def test_historical_positive_survives_rejection_and_only_linked_correction_invalidates(tmp_path):
    from resume_agent.outcomes import make_report
    runtime,job,_=setup_evaluation(tmp_path)
    view=event(runtime.applications,planned(runtime,job),{'kind':'submit','artifact_unknown':True})
    view=event(runtime.applications,view,{'kind':'stage_change','stage':'interviewing'},action='interview')
    positive_id=view['events'][-1]['id']
    view=event(runtime.applications,view,{'kind':'stage_change','stage':'rejected'},action='reject')
    report=make_report([view])
    assert report['counts']['positive']==1 and report['counts']['negative']==0
    corrected=event(runtime.applications,view,{'kind':'correction','target_event_id':positive_id,
        'reason':'Interview entry was for another application.'},action='correct')
    report=make_report([corrected])
    assert report['counts']['positive']==0 and report['counts']['negative']==1


def test_closure_is_negative_only_after_explicit_confirmation():
    from resume_agent.outcomes import make_report
    report=make_report([application(stage='closed',events=[{'kind':'stage_change','stage':'closed','closure_without_response':False}])])
    assert report['counts']['negative']==0 and report['counts']['closed_unclassified']==1
    report=make_report([application(stage='closed',events=[{'kind':'stage_change','stage':'closed','closure_without_response':True}])])
    assert report['counts']['negative']==1


def test_withdrawal_excludes_only_attempts_without_an_observed_outcome():
    from resume_agent.outcomes import make_report
    report=make_report([application(stage='withdrawn',events=[{'kind':'stage_change','stage':'screening'}]),
                        application(stage='withdrawn',events=[{'kind':'response_received','category':'rejection'}]),
                        application(stage='withdrawn')])
    assert report['counts']['positive']==1 and report['counts']['negative']==1 and report['counts']['withdrawn']==1
    assert report['bands'][2]['resolved']==2


def test_company_counts_keep_document_job_and_application_state_separate():
    from resume_agent.outcomes import company_metrics
    app=application(submitted=False)
    app.update(id='application',company='Example',created_at='2026-11-13T00:00:00+00:00')
    report=company_metrics([{'id':'run','company':'Example','status':'complete','created_at':1}],
                          [{'id':'job','company':'Example','captured_at':'2026-11-13T00:00:00+00:00'}],[app])
    company=report[0]
    assert company['total']==company['jobs']==company['applications']==1
    assert company['submitted']==company['positive']==company['responses']==0
    assert company['generation_health']['percent']==100


def test_generation_health_excludes_cancellation_and_pending_and_never_creates_submissions():
    from resume_agent.outcomes import generation_health,make_report
    runs=[{'status':s} for s in ['complete','failed','cancelled','cancelled','queued','awaiting-input','interrupted']]
    health=generation_health(runs)
    assert health['percent']==50 and health['denominator']==2 and health['cancelled']==2
    assert generation_health([])['percent'] is None
    assert make_report([])['counts']['submitted']==0


@pytest.mark.asyncio
async def test_report_never_reloads_current_evaluation_score(tmp_path):
    from resume_agent.outcomes import make_report
    runtime,job,_=setup_evaluation(tmp_path)
    evaluated=await runtime.evaluations.drive(runtime.evaluations.create(job.id)['id'])
    view=event(runtime.applications,planned(runtime,job),{'kind':'submit','artifact_unknown':True,'evaluation_id':evaluated['id']})
    view=event(runtime.applications,view,{'kind':'response_received','category':'favorable'},action='reply')
    current=runtime.profiles.load_snapshot()
    changed=current.profile.model_copy(deep=True)
    changed.summary='Later profile changed.'
    runtime.profiles.save_reviewed(current.revision,changed,{})
    assert make_report(runtime.applications.list())['bands'][2]['positive']==1
    assert runtime.applications.get(view['id'])['submission']['evaluation']['lower_exact']==[100,1]

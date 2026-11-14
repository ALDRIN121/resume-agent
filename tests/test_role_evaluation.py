"""Exact product-default fit arithmetic, independent of model prose."""
from fractions import Fraction

import pytest


def criterion(member_id,text=None):
    text=text or member_id
    return {'id':member_id,'text':text,'citations':[{'start':0,'end':len(text),'quote':text}]}


def group(group_id,members=None,dimension='required_skills',operator='single'):
    return {'id':group_id,'dimension':dimension,'operator':operator,'members':members or [criterion(group_id)]}


def finding(member_id,status):
    return {'member_id':member_id,'status':status,'sources':[],'rationale':'Test evidence.'}


@pytest.mark.parametrize('statuses,expected',[
    (['supported','unknown'],(50,100,50)),(['supported','transferable'],(75,75,100)),
    (['contradicted','supported'],(50,50,100)),(['unknown','unknown'],(0,100,0)),
])
def test_exact_interval_and_coverage(statuses,expected):
    from resume_agent.role_evaluation import score_fit
    result=score_fit([group('a'),group('b')],[finding(i,s) for i,s in zip(['a','b'],statuses)])
    assert (result['lower'],result['upper'],result['coverage'])==expected
    assert Fraction(*result['exact']['lower'])==Fraction(expected[0],1)


@pytest.mark.parametrize('operator,statuses,expected',[
    ('all',['supported','unknown'],'unknown'),('all',['unknown','contradicted'],'contradicted'),
    ('all',['supported','transferable'],'transferable'),('all',['supported','supported'],'supported'),
    ('any',['unknown','supported'],'supported'),('any',['unknown','transferable'],'transferable'),
    ('any',['contradicted','unknown'],'unknown'),('any',['contradicted','contradicted'],'contradicted'),
])
def test_group_truth_tables(operator,statuses,expected):
    from resume_agent.role_evaluation import score_fit
    result=score_fit([group('g',[criterion('a'),criterion('b')],operator=operator)],
                     [finding(i,s) for i,s in zip(['a','b'],statuses)])
    assert result['groups'][0]['status']==expected


def test_weights_renormalize_only_active_dimensions_and_zero_criteria_is_null():
    from resume_agent.role_evaluation import score_fit
    result=score_fit([group('a'),group('b',dimension='additional_skills')],
                     [finding('a','supported'),finding('b','unknown')])
    assert result['lower']==87.5 and result['upper']==100 and result['coverage']==87.5
    assert result['recommendation']=='prioritize'
    empty=score_fit([],[])
    assert empty['lower'] is empty['upper'] is empty['coverage'] is None
    assert empty['recommendation']=='review'


def test_conservative_normalization_dedup_preserves_punctuation_and_citations():
    from resume_agent.role_evaluation import score_fit
    groups=[group('a',[criterion('a','  PYTHON  ')]),group('b',[criterion('b','python')]),
            group('c',[criterion('c','C++')]),group('d',[criterion('d','C#')])]
    findings=[finding('a','supported'),finding('b','supported'),finding('c','unknown'),finding('d','contradicted')]
    result=score_fit(groups,findings)
    assert len(result['groups'])==3
    assert Fraction(*result['exact']['lower'])==Fraction(100,3)
    assert len(result['groups'][0]['members'][0]['citations'])==2
    reversed_result=score_fit(list(reversed(groups)),list(reversed(findings)))
    assert result['exact']==reversed_result['exact']
    assert result['lower']==33.33 and result['upper']==66.67 and result['coverage']==66.66


def test_eligibility_and_rounding_do_not_manufacture_prioritize():
    from resume_agent.role_evaluation import score_fit
    groups=[group(str(i)) for i in range(7)]
    findings=[finding(str(i),'supported' if i<5 else 'unknown') for i in range(7)]
    assert score_fit(groups,findings)['recommendation']=='review'
    all_known=[finding(str(i),'supported') for i in range(7)]
    assert score_fit(groups,all_known,eligibility='fail')['recommendation']=='skip'
    assert score_fit(groups,all_known,eligibility='unknown')['recommendation']=='review'
    with pytest.raises(ValueError):
        score_fit(groups,all_known,rubric_version='invented')


def test_conflicting_duplicate_findings_are_rejected_instead_of_choosing_score():
    from resume_agent.role_evaluation import score_fit
    with pytest.raises(ValueError):
        score_fit([group('a',[criterion('a','Python')]),group('b',[criterion('b','python')])],
                  [finding('a','supported'),finding('b','contradicted')])


def test_duplicate_groups_cannot_hide_conflicting_atomic_findings_with_same_group_status():
    from resume_agent.role_evaluation import score_fit
    requirements=[group('a',[criterion('a1','Python'),criterion('a2','Go')],operator='all'),
                  group('b',[criterion('b1','python'),criterion('b2','go')],operator='all')]
    with pytest.raises(ValueError):
        score_fit(requirements,[finding('a1','supported'),finding('a2','unknown'),
                                finding('b1','unknown'),finding('b2','supported')])

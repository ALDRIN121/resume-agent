"""The v2 review is atomic, revision-bound, and addressed by source index."""
import copy

import pytest

from resume_agent.content_review import build_content_preview, validate_proposals
from resume_agent.contracts import content_hash
from resume_agent.schemas import ContentSnapshot, EditProposal, SourceRef, UserResume


@pytest.fixture
def snapshot():
    profile = UserResume.model_validate({
        'personal': {'full_name': 'Mira Rao', 'email': 'mira@example.test'},
        'summary': 'Engineer — exact punctuation.',
        'experience': [
            {'company': 'Alpha', 'title': 'Engineer', 'start': '2022',
             'bullets': ['Reduced latency 450ms-to90ms; helper scope.', 'Same.', 'Same.']},
            {'company': 'Beta', 'title': 'Developer', 'start': '2020', 'end': '2022',
             'bullets': ['Same.']},
        ],
        'projects': [{'name': 'Atlas', 'description': 'Atlas description.', 'bullets': ['Built café ☕.']}],
        'skills': {'Tools': ['Git'], 'A/B~C': ['One'], 'Languages': ['Python', 'Go']},
    }).model_dump(mode='json')
    return ContentSnapshot(profile=profile, source_revision=content_hash(profile),
                           answers={'q1': 'I built café ☕.'}, user_text={'u1': 'I used Rust.'})


def proposal(snapshot, id='p1', target='/experience/0/bullets/1', operation='replace',
             after='Reworded.', **kwargs):
    from resume_agent.content_review import resolve_pointer
    return EditProposal(id=id, operation=operation, target_path=target,
        source_revision=snapshot.source_revision, before_hash=content_hash(resolve_pointer(snapshot.profile, target)),
        after=after, source_refs=[SourceRef(kind='profile', input_hash=snapshot.source_revision,
                                          target_path=target)], rationale='Clarify wording.', **kwargs)


def with_proposals(snapshot, *proposals):
    return snapshot.model_copy(update={'proposals': list(proposals)})


def test_reject_all_exact_copy(snapshot):
    original = copy.deepcopy(snapshot.profile)
    preview = build_content_preview(with_proposals(snapshot, proposal(snapshot)), [])
    assert preview.projected_profile == original
    assert preview.projected_profile is not snapshot.profile
    assert preview.results == []
    preview.projected_profile['experience'][0]['bullets'][0] = 'Changed outside'
    assert snapshot.profile == original


def test_index_target_preserves_identical_bullets(snapshot):
    preview = build_content_preview(with_proposals(snapshot, proposal(snapshot)), ['p1'])
    assert preview.projected_profile['experience'][0]['bullets'] == [
        'Reduced latency 450ms-to90ms; helper scope.', 'Reworded.', 'Same.']
    assert preview.projected_profile['experience'][1]['bullets'] == ['Same.']
    assert preview.results[0].status == 'applied'


@pytest.mark.parametrize('changes', [
    {'source_revision': '0' * 64}, {'before_hash': '0' * 64},
    {'target_path': '/experience/0/title'}, {'target_path': '/skills/A~2B/0'},
    {'target_path': '/experience/0/bullets/-'}, {'target_path': '/experience/00/bullets/0'},
])
def test_invalid_edit_is_atomic(snapshot, changes):
    bad = proposal(snapshot, id='bad').model_copy(update=changes)
    preview = build_content_preview(with_proposals(snapshot, proposal(snapshot), bad), ['p1', 'bad'])
    assert preview.projected_profile is None and preview.manifest is None
    assert len(preview.results) == 2
    assert all(r.status != 'applied' for r in preview.results)


@pytest.mark.parametrize('ids', [['unknown'], ['p1', 'p1']])
def test_unknown_and_duplicate_selection(snapshot, ids):
    preview = build_content_preview(with_proposals(snapshot, proposal(snapshot)), ids)
    assert preview.manifest is None
    assert len(preview.results) == len(ids)


def test_duplicate_proposal_ids_rejected(snapshot):
    with pytest.raises(ValueError, match='duplicate'):
        ContentSnapshot.model_validate({**snapshot.model_dump(), 'proposals': [proposal(snapshot), proposal(snapshot)]})


@pytest.mark.parametrize('operation', ['replace', 'omit_from_display'])
def test_overlapping_target_conflicts(snapshot, operation):
    p2 = proposal(snapshot, id='p2', operation=operation, after=None if operation == 'omit_from_display' else 'Other.')
    preview = build_content_preview(with_proposals(snapshot, proposal(snapshot), p2), ['p1', 'p2'])
    assert preview.manifest is None
    assert [r.status for r in preview.results] == ['conflict', 'conflict']


def test_appends_follow_display_order_after_replacements(snapshot):
    ref = SourceRef(kind='answer', answer_id='q1', input_hash=content_hash(snapshot.answers['q1']),
                    start=0, end=len(snapshot.answers['q1']), quote=snapshot.answers['q1'])
    a = proposal(snapshot, id='a', operation='append', target='/experience/0/bullets', after='First.')
    b = proposal(snapshot, id='b', operation='append', target='/experience/0/bullets', after='Second.')
    a = a.model_copy(update={'source_refs': [ref]})
    b = b.model_copy(update={'source_refs': [ref]})
    preview = build_content_preview(with_proposals(snapshot, a, proposal(snapshot), b), ['b', 'p1', 'a'])
    assert preview.projected_profile['experience'][0]['bullets'][-2:] == ['First.', 'Second.']
    assert preview.manifest.approved_proposal_ids == ['a', 'p1', 'b']


def test_append_needs_explicit_evidence(snapshot):
    p = proposal(snapshot, operation='append', target='/skills/Languages', after='Rust')
    assert build_content_preview(with_proposals(snapshot, p), ['p1']).manifest is None


def test_escaped_category_pointer(snapshot):
    p = proposal(snapshot, target='/skills/A~1B~0C/0', after='Two')
    preview = build_content_preview(with_proposals(snapshot, p), ['p1'])
    assert preview.projected_profile['skills']['A/B~C'] == ['Two']


@pytest.mark.parametrize('changes', [
    {'start': 9, 'end': 13, 'quote': 'café'}, {'input_hash': '0' * 64},
    {'answer_id': 'missing'}, {'start': 0, 'end': 99, 'quote': 'I'},
])
def test_invalid_evidence_rejected(snapshot, changes):
    ref = SourceRef(kind='answer', answer_id='q1', input_hash=content_hash(snapshot.answers['q1']),
                    start=8, end=12, quote='café').model_copy(update=changes)
    p = proposal(snapshot).model_copy(update={'source_refs': [ref]})
    assert build_content_preview(with_proposals(snapshot, p), ['p1']).manifest is None


def test_unicode_quote_and_profile_span(snapshot):
    ref = SourceRef(kind='answer', answer_id='q1', input_hash=content_hash(snapshot.answers['q1']),
                    start=8, end=14, quote='café ☕')
    p = proposal(snapshot).model_copy(update={'source_refs': [ref]})
    assert build_content_preview(with_proposals(snapshot, p), ['p1']).manifest is not None
    pref = SourceRef(kind='profile', input_hash=snapshot.source_revision,
                     target_path='/projects/0/bullets/0', start=6, end=12, quote='café ☕')
    assert validate_proposals(with_proposals(snapshot, p.model_copy(update={'source_refs': [pref]})))


@pytest.mark.parametrize('update', [{'after': 4}, {'after': None}, {'operation': 'omit_from_display', 'after': 'x'}, {'source_refs': []}])
def test_strict_proposal_types(snapshot, update):
    with pytest.raises(ValueError):
        EditProposal.model_validate({**proposal(snapshot).model_dump(), **update})


def test_snapshot_stale_and_unknown_evidence_kind(snapshot):
    with pytest.raises(ValueError):
        ContentSnapshot.model_validate({**snapshot.model_dump(), 'source_revision': '0' * 64})
    with pytest.raises(ValueError):
        SourceRef(kind='jd', input_hash='0' * 64)


@pytest.mark.parametrize('target', ['/personal/full_name', '/experience/0/company', '/experience/0/start', '/work_preferences', '/skills/New', '/projects/0/name', '/experience/0/tech/0'])
def test_immutable_and_nonexisting_targets_rejected(snapshot, target):
    p = proposal(snapshot).model_copy(update={'target_path': target})
    assert build_content_preview(with_proposals(snapshot, p), ['p1']).manifest is None


@pytest.mark.parametrize('target', ['/summary', '/projects/0/description', '/projects/0/bullets/0', '/skills/Languages/0'])
def test_all_allowed_scalar_targets(snapshot, target):
    p = proposal(snapshot, target=target, after='Exact approved text.')
    preview = build_content_preview(with_proposals(snapshot, p), ['p1'])
    assert preview.manifest is not None
    assert any(f.source_path == target and f.text == 'Exact approved text.' for f in preview.manifest.display_fields)


def test_user_text_hash_bound_append(snapshot):
    ref = SourceRef(kind='user_text', answer_id='u1', input_hash=content_hash(snapshot.user_text['u1']))
    p = proposal(snapshot, operation='append', target='/skills/Languages', after='Rust').model_copy(update={'source_refs': [ref]})
    preview = build_content_preview(with_proposals(snapshot, p), ['p1'])
    assert preview.projected_profile['skills']['Languages'] == ['Python', 'Go', 'Rust']
    assert snapshot.profile['skills']['Languages'] == ['Python', 'Go']
    changed = with_proposals(snapshot, p).model_copy(update={'user_text': {'u1': 'Different'}})
    assert build_content_preview(changed, ['p1']).manifest is None


def test_duplicate_append_text_is_conflict(snapshot):
    ref = SourceRef(kind='user_text', answer_id='u1', input_hash=content_hash(snapshot.user_text['u1']))
    a = proposal(snapshot, id='a', operation='append', target='/skills/Languages', after='Rust').model_copy(update={'source_refs': [ref]})
    b = a.model_copy(update={'id': 'b'})
    preview = build_content_preview(with_proposals(snapshot, a, b), ['a', 'b'])
    assert preview.manifest is None
    assert [r.status for r in preview.results] == ['conflict', 'conflict']


def test_preview_presenter_uses_identical_pure_projection(snapshot):
    from resume_agent.agents.suggestion_presenter import preview_suggestions_v2
    before = snapshot.model_dump()
    assert preview_suggestions_v2(snapshot, []) == build_content_preview(snapshot, [])
    assert snapshot.model_dump() == before

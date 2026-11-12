"""Approved manifest contains every visible fact without rewriting punctuation."""
import pytest

from resume_agent.agents.resume_generator import _guard_structure, _render_template
from resume_agent.content_review import (
    build_content_preview,
    expected_display_text,
    expected_display_tokens,
    recompute_manifest,
    verify_manifest,
)
from resume_agent.contracts import content_hash
from resume_agent.schemas import (
    ContentSnapshot,
    EditProposal,
    PersonalInfo,
    Project,
    Role,
    SourceRef,
    UserResume,
)


def fixed_profile():
    profile = UserResume.model_validate({
        'personal': {'full_name': 'Mira Rao', 'email': 'mira@example.test', 'phone': '+91 123',
                     'location': 'Delhi', 'headline': 'Engineer', 'linkedin': 'mira-rao',
                     'github': 'mira', 'website': 'https://example.test', 'portfolio': '/portfolio'},
        'summary': 'Summary; exact.',
        'experience': [{'company': 'Alpha', 'title': 'Engineer', 'start': '2022',
                        'location': 'Pune', 'tech': ['Python'],
                        'bullets': ['Reduced latency 450ms-to90ms; helper scope.', 'Same.', 'Same.']}],
        'projects': [{'name': 'Atlas', 'description': 'Same.', 'bullets': ['Same.'],
                      'tech': ['SQL'], 'url': 'https://atlas.test'}],
        'education': [{'institution': 'Institute', 'degree': 'BSc', 'field': 'CS',
                       'graduation': '2020', 'gpa': '9.0', 'notes': ['Honors.']}],
        'certifications': [{'name': 'Certification', 'issuer': 'Issuer', 'date': '2021', 'url': 'https://cert.test'}],
        'skills': {'Zulu': ['Z'], 'Tools': ['Git'], 'Languages': ['Python', 'Go'], 'Alpha': ['A']},
        'publications': ['My paper.'], 'work_preferences': {'preferred_locations': ['Remote']},
    }).model_dump(mode='json')
    return ContentSnapshot(profile=profile, source_revision=content_hash(profile))


def test_manifest_complete_ordered_and_exact():
    snapshot = fixed_profile()
    manifest = build_content_preview(snapshot, []).manifest
    text = expected_display_text(manifest)
    assert '450ms-to90ms; helper scope.' in text
    assert text.count('Same.') == 4
    assert 'Present' in expected_display_tokens(manifest)
    assert [f.order for f in manifest.display_fields] == list(range(len(manifest.display_fields)))
    assert [f.text for f in manifest.display_fields if f.kind == 'heading'] == [
        'Summary', 'Experience', 'Projects', 'Education', 'Skills', 'Languages', 'Tools',
        'Alpha', 'Zulu', 'Publications', 'Certifications']
    # Every populated scalar leaf is either displayed at its stable pointer or explicitly omitted.
    def leaves(value, path=''):
        if isinstance(value, dict):
            for k, v in value.items():
                yield from leaves(v, path + '/' + k.replace('~', '~0').replace('/', '~1'))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                yield from leaves(v, f'{path}/{i}')
        elif value is not None:
            yield path, value
    visible = {f.source_path: f.text for f in manifest.display_fields if f.source_path is not None}
    omissions = {o.source_path for o in manifest.omissions}
    for path, value in leaves(snapshot.profile):
        assert visible.get(path) == value or any(path == o or path.startswith(o + '/') for o in omissions)
    assert '/work_preferences' in omissions
    assert '/provenance' in omissions
    assert verify_manifest(manifest)


def test_omission_only_changes_display_and_keeps_source_indices():
    snapshot = fixed_profile()
    path = '/experience/0/bullets/1'
    p = EditProposal(id='omit', operation='omit_from_display', target_path=path,
        source_revision=snapshot.source_revision, before_hash=content_hash('Same.'), after=None,
        source_refs=[SourceRef(kind='profile', input_hash=snapshot.source_revision, target_path=path)], rationale='Omit')
    snapshot = snapshot.model_copy(update={'proposals': [p]})
    preview = build_content_preview(snapshot, ['omit'])
    assert preview.projected_profile == snapshot.profile
    assert any(o.source_path == path and o.reason == 'approved omit_from_display' for o in preview.manifest.omissions)
    assert any(f.source_path == '/experience/0/bullets/2' for f in preview.manifest.display_fields)
    assert expected_display_text(preview.manifest).count('Same.') == 3


def test_content_identity_excludes_layout_template_but_detects_display_tampering():
    snapshot = fixed_profile()
    standard = build_content_preview(snapshot, []).manifest
    compact = build_content_preview(snapshot, [], template_version='v9', layout_id='compact').manifest
    assert standard.content_hash == compact.content_hash
    assert verify_manifest(compact)
    changed = standard.model_copy(update={'display_fields': [standard.display_fields[0].model_copy(update={'text': 'Different'})] + standard.display_fields[1:]})
    assert not verify_manifest(changed)
    assert recompute_manifest(changed) != standard.content_hash
    with pytest.raises(ValueError, match='invalid render manifest'):
        expected_display_text(changed)
    assert not verify_manifest(standard.model_copy(update={'display_fields': list(reversed(standard.display_fields))}))


# Legacy v1 fidelity behavior stays covered until T09 activation.
@pytest.fixture
def draft():
    return _render_template(UserResume(
        personal=PersonalInfo(full_name="Test Candidate", email="test@example.com"),
        experience=[Role(company="Example", title="Engineer", start="2024", bullets=[
            "Build Python automation for operations.", "Reduced latency from 450ms to 90ms.",
        ])],
    ))


def test_rejects_new_unconfirmed_numeric_claim(draft):
    candidate = draft.replace("Build Python automation for operations.",
                              r"Build Python automation for operations, saving 30\% of processing time.")
    assert _guard_structure(candidate, fallback=draft) == draft


def test_rejects_removed_numeric_facts(draft):
    candidate = draft.replace("from 450ms to 90ms", "to 90ms")
    assert _guard_structure(candidate, fallback=draft) == draft


def test_allows_wording_changes_with_same_numeric_facts(draft):
    candidate = draft.replace("Build Python automation", "Develop Python automation")
    assert _guard_structure(candidate, fallback=draft) == candidate


def test_allows_body_spacing_changes_without_changing_facts(draft):
    candidate = draft.replace(r"\vspace{4pt}", r"\vspace{6pt}")
    assert _guard_structure(candidate, fallback=draft) == candidate


def test_avoids_description_that_repeats_project_bullet():
    resume = UserResume(personal=PersonalInfo(full_name="Test", email="test@example.com"), projects=[
        Project(name="Example tool", description="Installable analytics application integrating five agents.",
                bullets=["Shipped an installable analytics application integrating five agents; added regression tests."]),
        Project(name="Example library", description="Open-source contributions to Example library.",
                bullets=["Fixed serialization failures and added regression tests."]),
    ])
    result = _render_template(resume)
    assert r"\resumeItem{Installable analytics application integrating five agents.}" not in result
    assert "Open-source contributions to Example library." not in result
    assert "Shipped an installable analytics" in result
    assert "Fixed serialization failures" in result


def test_preserves_distinct_project_description():
    resume = UserResume(personal=PersonalInfo(full_name="Test", email="test@example.com"), projects=[
        Project(name="Example", description="Tool serving public health researchers.",
                bullets=["Built an asynchronous import pipeline."]),
    ])
    assert "Tool serving public health researchers." in _render_template(resume)


def test_rejects_added_claim_reusing_existing_number(draft):
    candidate = draft.replace("Build Python automation for operations.",
                              "Build Python automation for operations, saving 90ms.")
    assert _guard_structure(candidate, fallback=draft) == draft


def test_rejects_removed_repeated_numeric_fact(draft):
    repeated = draft.replace("Build Python automation for operations.",
                             "Build Python automation serving 90 users.")
    candidate = repeated.replace("Build Python automation serving 90 users.",
                                 "Build Python automation for operations.")
    assert _guard_structure(candidate, fallback=repeated) == repeated

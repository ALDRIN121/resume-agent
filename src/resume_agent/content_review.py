"""Pure, atomic v2 proposal validation and approved display projection.

The manifest's field list is the complete renderer input. Wording, labels, list
order, and omissions are decided here, before content approval.
"""
from __future__ import annotations

import copy
import re

from .contracts import content_hash
from .schemas import (
    ContentPreview,
    ContentSnapshot,
    DisplayField,
    DisplayOmission,
    EditProposal,
    PatchResult,
    RenderManifest,
)

SKILL_PRIORITY = ('Languages', 'Frameworks', 'Cloud', 'GenAI', 'MLOps', 'Tools')


def pointer_parts(path: str) -> list[str]:
    if not path.startswith('/'):
        raise ValueError('JSON pointer must start with /')
    parts = path[1:].split('/')
    if any(re.search(r'~(?![01])', part) for part in parts):
        raise ValueError('invalid JSON pointer escape')
    return [part.replace('~1', '/').replace('~0', '~') for part in parts]


def _escape(value: str) -> str:
    return value.replace('~', '~0').replace('/', '~1')


def _index(part: str) -> int:
    if not re.fullmatch(r'0|[1-9][0-9]*', part):
        raise ValueError('invalid list index')
    return int(part)


def resolve_pointer(profile: dict, path: str):
    value = profile
    try:
        for part in pointer_parts(path):
            value = value[_index(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('unknown source pointer') from exc
    return value


def _allowed(profile: dict, proposal: EditProposal):
    parts = pointer_parts(proposal.target_path)
    value = resolve_pointer(profile, proposal.target_path)
    list_target = False
    scalar_target = parts == ['summary']
    if len(parts) >= 3 and parts[0] in ('experience', 'projects'):
        _index(parts[1])
        if parts[2] == 'bullets':
            list_target = len(parts) == 3
            scalar_target = len(parts) == 4
            if scalar_target:
                _index(parts[3])
        elif parts[0] == 'projects' and parts[2] == 'description':
            scalar_target = len(parts) == 3
    elif len(parts) >= 2 and parts[0] == 'skills':
        list_target = len(parts) == 2
        scalar_target = len(parts) == 3
        if scalar_target:
            _index(parts[2])
    if proposal.operation == 'append':
        if not list_target or not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError('unsupported append target')
    elif not scalar_target or not (isinstance(value, str) or parts == ['summary'] and value is None):
        raise ValueError('unsupported text target')
    return value


def _validate_edit(snapshot: ContentSnapshot, proposal: EditProposal) -> None:
    # Revalidate copied/deserialized wire data, including model_copy updates.
    proposal = EditProposal.model_validate(proposal.model_dump())
    if proposal.source_revision != snapshot.source_revision:
        raise ValueError('stale source revision')
    before = _allowed(snapshot.profile, proposal)
    if content_hash(before) != proposal.before_hash:
        raise ValueError('stale before hash')
    explicit_evidence = False
    for ref in proposal.source_refs:
        if ref.kind == 'profile':
            if ref.input_hash != snapshot.source_revision:
                raise ValueError('stale profile evidence')
            source = resolve_pointer(snapshot.profile, ref.target_path)
        else:
            sources = snapshot.answers if ref.kind == 'answer' else snapshot.user_text
            if ref.answer_id not in sources:
                raise ValueError('unknown evidence ID')
            source = sources[ref.answer_id]
            if content_hash(source) != ref.input_hash:
                raise ValueError('stale evidence hash')
            explicit_evidence = bool(source.strip()) or explicit_evidence
        if ref.quote is not None:
            if not isinstance(source, str) or ref.end > len(source) or source[ref.start:ref.end] != ref.quote:
                raise ValueError('invalid evidence quote span')
    if (proposal.operation == 'append' or proposal.operation == 'replace' and before in (None, '')) and not explicit_evidence:
        raise ValueError('addition requires explicit answer or user_text evidence')


def validate_proposals(snapshot: ContentSnapshot) -> list[EditProposal]:
    """Validate each model proposal before presentation; never skip bad output."""
    snapshot = ContentSnapshot.model_validate(snapshot.model_dump())
    for proposal in snapshot.proposals:
        _validate_edit(snapshot, proposal)
    return snapshot.proposals


def recompute_manifest(manifest: RenderManifest) -> str:
    """Content identity excludes all template/layout choices."""
    data = manifest.model_dump(mode='json')
    for key in ('content_hash', 'template_version', 'layout_id'):
        data.pop(key)
    return content_hash(data)


def verify_manifest(manifest: RenderManifest) -> bool:
    try:
        manifest = RenderManifest.model_validate(manifest.model_dump())
        return ([f.order for f in manifest.display_fields] == list(range(len(manifest.display_fields)))
                and len(manifest.approved_proposal_ids) == len(set(manifest.approved_proposal_ids))
                and recompute_manifest(manifest) == manifest.content_hash)
    except ValueError:
        return False


def expected_display_tokens(manifest: RenderManifest) -> list[str]:
    """Exact visible strings, in stream order, including generated visible labels."""
    if not verify_manifest(manifest):
        raise ValueError('invalid render manifest')
    tokens = []
    for field in manifest.display_fields:
        if field.visible_label is not None:
            tokens.append(field.visible_label)
        tokens.append(field.text)
    return tokens


def expected_display_text(manifest: RenderManifest) -> str:
    return '\n'.join(expected_display_tokens(manifest))


def _manifest(profile: dict, snapshot: ContentSnapshot, selected: list[EditProposal],
              omitted: set[str], template_version: str, layout_id: str) -> RenderManifest:
    fields = []
    omissions = []

    def add(path, text, kind, section, group, label=None):
        if path in omitted:
            omissions.append(DisplayOmission(source_path=path, reason='approved omit_from_display'))
        elif text is None or text == '' or text == []:
            if path is not None:
                omissions.append(DisplayOmission(source_path=path, reason='empty optional field'))
        else:
            fields.append(DisplayField(order=len(fields), source_path=path, text=text,
                          kind=kind, section=section, group=group, visible_label=label))

    def heading(text, section):
        add(None, text, 'heading', section, section)

    def scalar(data, key, path, section, group, kind='field', label=None):
        add(path + '/' + _escape(key), data[key], kind, section, group, label)

    def strings(values, path, section, group, kind='field'):
        if not values:
            omissions.append(DisplayOmission(source_path=path, reason='empty optional list'))
        for i, text in enumerate(values):
            add(f'{path}/{i}', text, kind, section, group)

    personal = profile['personal']
    scalar(personal, 'full_name', '/personal', 'personal', 'personal', 'name')
    for key in ('headline', 'email', 'phone', 'location', 'linkedin', 'github', 'website', 'portfolio'):
        # Separate visible lines avoid introducing hidden separators or URL rewriting.
        scalar(personal, key, '/personal', 'personal', 'personal')
    if profile['summary'] and '/summary' not in omitted:
        heading('Summary', 'summary')
    add('/summary', profile['summary'], 'field', 'summary', 'summary')
    for section, label in (('experience', 'Experience'), ('projects', 'Projects'), ('education', 'Education')):
        if profile[section]:
            heading(label, section)
        else:
            omissions.append(DisplayOmission(source_path='/' + section, reason='empty optional list'))
        for i, item in enumerate(profile[section]):
            path = f'/{section}/{i}'
            if section == 'experience':
                for key in ('company', 'title', 'location', 'start'):
                    scalar(item, key, path, section, path)
                if item['end'] is None:
                    add(path + '/end', 'Present', 'field', section, path)
                else:
                    scalar(item, 'end', path, section, path)
                strings(item['bullets'], path + '/bullets', section, path, 'bullet')
                strings(item['tech'], path + '/tech', section, path)
            elif section == 'projects':
                scalar(item, 'name', path, section, path)
                scalar(item, 'description', path, section, path)
                strings(item['bullets'], path + '/bullets', section, path, 'bullet')
                strings(item['tech'], path + '/tech', section, path)
                scalar(item, 'url', path, section, path)
            else:
                for key in ('institution', 'degree', 'field', 'graduation', 'gpa'):
                    scalar(item, key, path, section, path)
                strings(item['notes'], path + '/notes', section, path, 'bullet')
    if profile['skills']:
        heading('Skills', 'skills')
    else:
        omissions.append(DisplayOmission(source_path='/skills', reason='empty optional mapping'))
    categories = [c for c in SKILL_PRIORITY if c in profile['skills']]
    categories += sorted(c for c in profile['skills'] if c not in SKILL_PRIORITY)
    for category in categories:
        path = '/skills/' + _escape(category)
        visible = any(f'{path}/{i}' not in omitted for i in range(len(profile['skills'][category])))
        if visible:
            add(None, category, 'heading', 'skills', path)
        strings(profile['skills'][category], path, 'skills', path)
    if profile['publications']:
        heading('Publications', 'publications')
    strings(profile['publications'], '/publications', 'publications', 'publications')
    if profile['certifications']:
        heading('Certifications', 'certifications')
    else:
        omissions.append(DisplayOmission(source_path='/certifications', reason='empty optional list'))
    for i, item in enumerate(profile['certifications']):
        path = f'/certifications/{i}'
        for key in ('name', 'issuer', 'date', 'url'):
            scalar(item, key, path, 'certifications', path)
    omissions.extend([
        DisplayOmission(source_path='/work_preferences', reason='non-display targeting preferences'),
        DisplayOmission(source_path='/provenance', reason='non-display run evidence and source metadata'),
    ])
    manifest = RenderManifest(source_revision=snapshot.source_revision,
        approved_proposal_ids=[p.id for p in selected], display_fields=fields, omissions=omissions,
        template_version=template_version, layout_id=layout_id, content_hash='0' * 64)
    return manifest.model_copy(update={'content_hash': recompute_manifest(manifest)})


def build_content_preview(snapshot: ContentSnapshot, selected_ids: list[str], *,
                          template_version: str = 'v2', layout_id: str = 'standard') -> ContentPreview:
    """Validate against the original snapshot, then atomically project selected edits.

    Invalid/conflicting selections return one result per submitted ID and no
    profile/manifest. Accepted IDs and edits use displayed proposal order.
    Omissions change display only; source lists and source index pointers survive.
    """
    snapshot = ContentSnapshot.model_validate(snapshot.model_dump())
    if not isinstance(selected_ids, list) or any(not isinstance(v, str) for v in selected_ids):
        raise ValueError('selected_ids must be a list of strings')
    by_id = {p.id: p for p in snapshot.proposals}
    errors = {}
    conflicts = set()
    targets = {}
    appends = {}
    for id in selected_ids:
        if id not in by_id:
            errors[id] = 'unknown proposal ID'
        elif selected_ids.count(id) > 1:
            errors[id] = 'duplicate selected ID'
        else:
            p = by_id[id]
            try:
                _validate_edit(snapshot, p)
            except ValueError as exc:
                errors[id] = str(exc)
            if p.operation != 'append':
                if p.target_path in targets:
                    conflicts.update((id, targets[p.target_path]))
                targets[p.target_path] = id
            else:
                append_key = (p.target_path, p.after)
                if append_key in appends:
                    conflicts.update((id, appends[append_key]))
                appends[append_key] = id
    if errors or conflicts:
        results = [PatchResult(proposal_id=id,
                   status='conflict' if id in conflicts else 'invalid',
                   reason=errors.get(id, 'overlapping selected target' if id in conflicts else 'atomic selection rejected'))
                   for id in selected_ids]
        return ContentPreview(projected_profile=None, results=results, manifest=None)
    selected_set = set(selected_ids)
    selected = [p for p in snapshot.proposals if p.id in selected_set]
    profile = copy.deepcopy(snapshot.profile)
    omitted = set()
    for p in selected:
        if p.operation == 'omit_from_display':
            omitted.add(p.target_path)
        elif p.operation == 'replace':
            parts = pointer_parts(p.target_path)
            parent = resolve_pointer(profile, '/' + '/'.join(_escape(x) for x in parts[:-1])) if len(parts) > 1 else profile
            key = _index(parts[-1]) if isinstance(parent, list) else parts[-1]
            parent[key] = p.after
    for p in selected:
        if p.operation == 'append':
            resolve_pointer(profile, p.target_path).append(p.after)
    return ContentPreview(projected_profile=profile,
        results=[PatchResult(proposal_id=p.id, status='applied') for p in selected],
        manifest=_manifest(profile, snapshot, selected, omitted, template_version, layout_id))

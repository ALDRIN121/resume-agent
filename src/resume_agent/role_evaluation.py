"""Evidence fit uses exact rational arithmetic, never model-generated scores."""
from __future__ import annotations

import unicodedata
from fractions import Fraction

from .career_schemas import RequirementFinding, RoleAnalysis, RoleEvaluation, RoleRequirement
from .content_review import pointer_parts, resolve_pointer
from .contracts import DriverResult, OperationRequest, canonical_json, content_hash
from .model_tasks import ModelTaskRunner
from .operation_service import OperationService
from .provider_errors import ModelTaskError
from .run_service import DriverFailureError
from .run_store import Conflict

WEIGHTS = {'required_skills': 35, 'responsibilities': 25, 'scope_seniority': 15,
           'domain_experience': 10, 'candidate_preferences': 10, 'additional_skills': 5}


def normalize(text):
    return ' '.join(unicodedata.normalize('NFC', text).split()).casefold()


def group_status(operator, statuses):
    if operator == 'single':
        return statuses[0]
    if operator == 'all':
        return next((s for s in ('contradicted', 'unknown', 'transferable') if s in statuses), 'supported')
    return next((s for s in ('supported', 'transferable', 'unknown') if s in statuses), 'contradicted')


def _groups(requirements, findings):
    findings = [RequirementFinding.model_validate(f) for f in findings]
    by_id = {f.member_id: f for f in findings}
    if len(by_id) != len(findings):
        raise ValueError('duplicate_finding_id')
    result, member_ids, group_ids = {}, set(), set()
    for raw in requirements:
        group = RoleRequirement.model_validate(raw)
        if group.id in group_ids:
            raise ValueError('duplicate_requirement_id')
        group_ids.add(group.id)
        members = {}
        for member in group.members:
            if member.id in member_ids:
                raise ValueError('duplicate_member_id')
            member_ids.add(member.id)
            if member.id not in by_id:
                raise ValueError('missing_member_finding')
            key = normalize(member.text)
            status = by_id[member.id].status
            item = members.setdefault(key, {'ids': [], 'text': member.text, 'citations': [], 'status': status})
            if item['status'] != status:
                raise ValueError('conflicting_duplicate_findings')
            item['ids'].append(member.id)
            item['citations'].extend(c.model_dump(mode='json') for c in member.citations)
        key = (group.dimension, group.operator, tuple(sorted(members)))
        status = 'unknown' if group.needs_review else group_status(group.operator, [m['status'] for m in members.values()])
        if key not in result:
            result[key] = {'id': content_hash(['requirements-v1', *key]), 'ids': [group.id], 'dimension': group.dimension,
                           'operator': group.operator, 'members': list(members.values()), 'status': status,
                           'needs_review': group.needs_review}
        else:
            old = result[key]
            if old['status'] != status or old['needs_review'] != group.needs_review:
                raise ValueError('conflicting_duplicate_findings')
            old['ids'].append(group.id)
            # Preserve all exact citations after conservative matching.
            existing = {normalize(m['text']): m for m in old['members']}
            for normalized, member in members.items():
                if existing[normalized]['status'] != member['status']:
                    raise ValueError('conflicting_duplicate_findings')
                existing[normalized]['ids'].extend(member['ids'])
                existing[normalized]['citations'].extend(member['citations'])
    if set(by_id) != member_ids:
        raise ValueError('unknown_member_finding')
    return list(result.values())


def _display(value, *, ceiling=False):
    numerator, denominator = (value * 100).as_integer_ratio()
    scaled = -(-numerator // denominator) if ceiling else numerator // denominator
    return scaled / 100


def score_fit(requirements, findings, *, rubric_version='fit-v1', eligibility='pass'):
    if rubric_version != 'fit-v1' or eligibility not in ('pass', 'fail', 'unknown'):
        raise ValueError('unsupported_rubric_or_eligibility')
    groups = _groups(requirements, findings)
    if not groups:
        return dict(lower=None, upper=None, coverage=None, exact=None, recommendation='skip' if eligibility == 'fail' else 'review', groups=[])
    active = {g['dimension'] for g in groups}
    total = sum(WEIGHTS[d] for d in active)
    counts = {d: sum(g['dimension'] == d for g in groups) for d in active}
    lower = upper = known = Fraction(0)
    for group in groups:
        weight = Fraction(100 * WEIGHTS[group['dimension']], total * counts[group['dimension']])
        group['weight'] = list(weight.as_integer_ratio())
        status = group['status']
        lo, hi = {'supported': (1, 1), 'transferable': (Fraction(1, 2), Fraction(1, 2)),
                  'contradicted': (0, 0), 'unknown': (0, 1)}[status]
        lower += weight * lo
        upper += weight * hi
        if status != 'unknown':
            known += weight
    recommendation = ('skip' if eligibility == 'fail' else 'prioritize' if eligibility == 'pass'
                      and known >= 80 and lower >= 70 and not any(g['needs_review'] for g in groups) else 'review')
    return dict(lower=_display(lower), upper=_display(upper, ceiling=True), coverage=_display(known),
                exact={key: list(value.as_integer_ratio()) for key, value in [('lower', lower), ('upper', upper), ('coverage', known)]},
                recommendation=recommendation, groups=groups)


def _citation(citation, text):
    if not (0 <= citation.start < citation.end <= len(text)) or text[citation.start:citation.end] != citation.quote:
        raise ValueError('invalid_jd_citation')


def _source(source, fixed, *, dimension=None, eligibility_category=None):
    origins = {'profile': ('profile_snapshot', 'profile_revision'), 'memory': ('memory_snapshot', 'memory_revision'),
               'answer': ('answers', None), 'user_text': ('user_text', None), 'eligibility': ('eligibility_facts', None)}
    data_key, hash_key = origins[source.kind]
    data = fixed[data_key]
    expected = fixed[hash_key] if hash_key else content_hash(data)
    if source.input_hash != expected:
        raise ValueError('candidate_source_hash_mismatch')
    value = resolve_pointer(data, source.target_path)
    text = value if isinstance(value, str) else canonical_json(value)
    if source.quote not in text:
        raise ValueError('candidate_source_quote_mismatch')
    parts = pointer_parts(source.target_path)
    if source.kind == 'memory':
        if len(parts) < 4 or parts[0] != 'records' or parts[2] != 'payload':
            raise ValueError('memory_payload_source_required')
        record = data['records'][int(parts[1])]
        if record['kind'] != 'target_preference':
            raise ValueError('writing_rules_are_not_candidate_evidence')
        if dimension is not None and dimension != 'candidate_preferences':
            raise ValueError('preferences_are_not_skill_evidence')
    if source.kind == 'profile' and parts[0] == 'work_preferences' and dimension != 'candidate_preferences':
        raise ValueError('preferences_are_not_skill_evidence')
    if eligibility_category:
        if source.kind == 'eligibility':
            if len(parts) != 1 or parts[0] != eligibility_category:
                raise ValueError('explicit_typed_eligibility_source_required')
        elif source.kind == 'memory':
            if len(parts) != 6 or parts[3] != 'hard_constraints' or parts[5] not in ('value', 'text'):
                raise ValueError('explicit_hard_constraint_required')
            constraint = data['records'][int(parts[1])]['payload']['hard_constraints'][int(parts[4])]
            if eligibility_category != 'user_hard_constraint' and constraint['category'] != eligibility_category:
                raise ValueError('eligibility_category_mismatch')
        else:
            raise ValueError('identity_and_preferences_do_not_prove_eligibility')
    return source.model_dump(mode='json') | {'value': value}


def validate_analysis(analysis, fixed):
    analysis = RoleAnalysis.model_validate(analysis)
    dimensions, resolved = {}, []
    for requirement in analysis.requirements:
        for member in requirement.members:
            if member.id in dimensions:
                raise ValueError('duplicate_member_id')
            dimensions[member.id] = requirement.dimension
            for citation in member.citations:
                _citation(citation, fixed['job']['text'])
    for finding in analysis.findings:
        if finding.member_id not in dimensions:
            raise ValueError('unknown_member_finding')
        if finding.status != 'unknown' and (not finding.sources or not finding.rationale.strip()):
            raise ValueError('known_findings_require_source_and_justification')
        resolved.extend(_source(source, fixed, dimension=dimensions[finding.member_id]) for source in finding.sources)
    for finding in analysis.eligibility:
        _citation(finding.citation, fixed['job']['text'])
        if finding.status != 'unknown' and (not finding.sources or not finding.rationale.strip()):
            raise ValueError('eligibility_requires_explicit_source')
        resolved.extend(_source(source, fixed, eligibility_category=finding.category) for source in finding.sources)
    eligibility = ('fail' if any(f.status == 'fail' for f in analysis.eligibility) else
                   'unknown' if any(f.status == 'unknown' for f in analysis.eligibility) else 'pass')
    return analysis, eligibility, resolved


_SYSTEM = '''Analyze the full immutable job and candidate inputs below. Return requirements, findings and eligibility only; never generate a score.
Each requirement has an id, one of the six dimensions, explicit single/all/any operator, members with unique IDs, exact JD citations (Unicode code-point start/end offsets and quote), and needs_review if the operator is unclear. Preserve C/C++/C#, versions, signs and units.
Every member has exactly one finding: supported, justified transferable, contradicted or unknown. Missing profile evidence is unknown, never contradiction. Known findings require exact resolving source references with kind, input_hash, target_path JSON pointer, quote, and rationale. Include all source restrictions and unknowns. Never infer authorization, clearance or required presence from personal identity, home address or general location preferences.
Eligibility sources must be explicitly typed eligibility_facts or memory target-preference hard_constraints. Use category authorization, clearance, presence or user_hard_constraint, status pass/fail/unknown, exact JD citation, sources and rationale. Unknown restrictions require no invented facts. Ordinary confirmed answers/user_text can support fit findings but cannot establish eligibility. Writing rules are not candidate evidence. Preferences can support only candidate_preferences. Do not treat these product-default dimensions as hiring probabilities.
Input hashes: profile uses profile_revision; memory uses memory_revision; answer/user_text/eligibility use their declared hashes. Use the exact full supplied values, with no invented evidence.'''


class EvaluationService:
    def __init__(self, store, jobs, profiles, memory, *, settings, model=None, crash_hook=None):
        self.store, self.jobs, self.profiles, self.memory = store, jobs, profiles, memory
        self.settings, self.model, self.crash_hook = settings, model, crash_hook
        self.operations = OperationService(store, driver=self._driver)

    def _boundary(self, stage):
        if self.crash_hook:
            self.crash_hook(stage)

    def create(self, job_id, *, answers=None, user_text=None, eligibility_facts=None, execution_mode='app'):
        if execution_mode not in ('app', 'host'):
            raise ValueError('invalid_execution_mode')
        profile = self.profiles.load_snapshot()
        if profile is None or profile.review_required:
            raise Conflict('profile_review_required')
        for data in (answers or {}, user_text or {}, eligibility_facts or {}):
            if not isinstance(data, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in data.items()):
                raise ValueError('confirmed_text_must_be_string_mapping')
        if set(eligibility_facts or {}) - {'authorization', 'clearance', 'presence', 'user_hard_constraint'}:
            raise ValueError('unknown_eligibility_category')
        job = self.jobs.get(job_id)
        memory = self.memory.snapshot()
        current = self.settings()
        fixed = {'job': job.model_dump(mode='json'), 'profile_snapshot': profile.profile.model_dump(mode='json'),
                 'profile_revision': profile.revision, 'memory_snapshot': memory, 'memory_revision': content_hash(memory),
                 'rubric_version': 'fit-v1', 'provider': current.provider, 'model': current.model.default,
                 'request': {'execution_mode': execution_mode}, 'answers': answers or {}, 'user_text': user_text or {},
                 'eligibility_facts': eligibility_facts or {}}
        fixed.update({name + '_hash': content_hash(fixed[name]) for name in ('answers', 'user_text', 'eligibility_facts')})
        operation = self.operations.create(OperationRequest(kind='role_evaluation', input=fixed))
        return self.get(operation.id)

    def get(self, operation_id):
        view = self.operations.get(operation_id)
        if view.kind != 'role_evaluation':
            raise KeyError(operation_id)
        fixed = self.store.input('operation', operation_id)
        reasons = []
        try:
            profile = self.profiles.load_snapshot()
        except (ValueError, OSError):
            profile = None
        if profile is None or profile.review_required or profile.revision != fixed['profile_revision']:
            reasons.append('profile')
        if content_hash(self.memory.snapshot()) != fixed['memory_revision']:
            reasons.append('memory')
        if self.jobs.current(fixed['job']['logical_id']).id != fixed['job']['id']:
            reasons.append('job')
        if fixed['rubric_version'] != 'fit-v1':
            reasons.append('rubric')
        return view.model_dump(mode='json') | {'stale': bool(reasons), 'stale_reasons': reasons,
            'job_id': fixed['job']['id'], 'fixed_identities': {'profile': fixed['profile_revision'],
                'memory': fixed['memory_revision'], 'jd': fixed['job']['content_hash'], 'rubric': fixed['rubric_version']}}

    async def drive(self, operation_id, action=None):
        # Ensure the caller cannot dispatch a profile-import operation through this driver.
        self.get(operation_id)
        await self.operations.drive(operation_id, action)
        return self.get(operation_id)

    def cancel(self, operation_id):
        self.get(operation_id)
        self.operations.cancel(operation_id)
        return self.get(operation_id)

    def list_for_job(self, job_id):
        self.jobs.get(job_id)
        with self.store.connection() as conn:
            rows = conn.execute("SELECT id,input_json FROM operations WHERE kind='role_evaluation' ORDER BY created_at DESC").fetchall()
        import json
        return [self.get(row['id']) for row in rows if json.loads(row['input_json'])['job']['id'] == job_id]

    async def _driver(self, context):
        fixed, values = context.fixed_inputs, context.checkpoint
        if 'evaluation_result' in values:
            result = RoleEvaluation.model_validate(values['evaluation_result'])
            context.control.checkpoint({'evaluation_result': result.model_dump(mode='json')})
        else:
            invoke = None
            if self.model is not None:
                async def invoke(messages):
                    return await self.model('role_evaluation', RoleAnalysis, messages)
            try:
                raw = await ModelTaskRunner(context).run('role_evaluation', RoleAnalysis,
                    [{'role': 'system', 'content': _SYSTEM}, {'role': 'user', 'content': canonical_json(fixed)}],
                    invoke, settings=self.settings(), credentials_available=True if invoke else None)
            except ModelTaskError as exc:
                raise DriverFailureError(exc.code, exc.stage) from None
            self._boundary('after_model')
            try:
                analysis, eligibility, sources = validate_analysis(raw, fixed)
                fit = score_fit(analysis.requirements, analysis.findings, rubric_version=fixed['rubric_version'], eligibility=eligibility)
            except (ValueError, KeyError, IndexError, TypeError):
                raise DriverFailureError('invalid_evaluation_evidence', 'role_evaluation') from None
            result = RoleEvaluation(operation_id=context.owner_id, job_id=fixed['job']['id'],
                rubric_version=fixed['rubric_version'], profile_revision=fixed['profile_revision'], memory_revision=fixed['memory_revision'],
                jd_revision=fixed['job']['content_hash'], provider=fixed['provider'], model=fixed['model'],
                analysis=analysis, fit=fit, eligibility_status=eligibility, resolved_sources=sources)
            context.control.checkpoint({'evaluation_result': result.model_dump(mode='json')})
            self._boundary('after_result_checkpoint')
        context.control.check_cancelled()
        serialized = canonical_json(result)
        with self.store.connection(immediate=True) as conn:
            conn.execute('INSERT INTO career_evaluations VALUES (?,?,?) ON CONFLICT(operation_id) DO NOTHING',
                         (context.owner_id, fixed['job']['id'], serialized))
            stored = conn.execute('SELECT result_json FROM career_evaluations WHERE operation_id=?', (context.owner_id,)).fetchone()[0]
            if stored != serialized:
                raise DriverFailureError('evaluation_result_conflict', 'role_evaluation')
        self._boundary('after_result_index')
        return DriverResult(status='complete', result=result.model_dump(mode='json'))

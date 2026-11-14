"""The reviewed workflow against real lifecycle storage and artifact bytes."""
import json

import pytest

from resume_agent.checkpoint import read_v2_checkpoint
from resume_agent.contracts import (
    AskMissing,
    PresentSuggestions,
    ReviewPdf,
    RunRequest,
    content_hash,
)
from resume_agent.run_service import RunService
from resume_agent.run_store import Conflict, RunStore
from resume_agent.schemas import UserResume

PROFILE = UserResume(personal={'full_name': 'Ada', 'email': 'ada@example.test'}, summary='Original summary.')


def build(tmp_path, calls, *, questions=True):
    from resume_agent.workflow import Workflow

    async def model(stage, schema, messages):
        calls.append((stage, messages))
        if stage == 'extract_jd':
            return {'company': 'Example', 'role_title': 'Engineer'}
        if stage == 'questions':
            return {'questions': [{'id': 'q1', 'prompt': 'Any leadership?', 'why_asking': 'Role needs it.'}] if questions else []}
        snapshot = json.loads(messages[0]['content'].split('FIXED_INPUTS:\n')[1])
        assert snapshot['answers'] == ({'q1': 'Led a team.'} if questions else {})
        return {'proposals': [{'id': 'p1', 'operation': 'replace', 'target_path': '/summary',
            'source_revision': snapshot['source_revision'], 'before_hash': content_hash('Original summary.'),
            'after': 'Selected summary.', 'source_refs': [{'kind': 'profile',
                'input_hash': snapshot['source_revision'], 'target_path': '/summary'}], 'rationale': 'Clearer.'}]}

    def compiler(source, *, output_dir):
        from resume_agent.content_review import expected_display_text
        from resume_agent.tools.tectonic_compile import CompileResult
        from tests.test_pdf_content_check import make_pdf
        manifest = read_v2_checkpoint(tmp_path / 'state.sqlite', 'run', run_id[0])['values']['manifest']
        from resume_agent.schemas import RenderManifest
        path = make_pdf(output_dir / 'resume.pdf', expected_display_text(RenderManifest.model_validate(manifest)))
        return CompileResult(True, str(path), [], '')

    from tests.test_approved_render import images
    store = RunStore(tmp_path / 'library.sqlite', tmp_path / 'state.sqlite')
    workflow = Workflow(store, artifacts_root=tmp_path / 'runs', output_dir=tmp_path / 'output',
                        model=model, compile_adapter=compiler, image_adapter=images)
    service = RunService(store, driver=workflow.drive, action_validator=workflow.validate_action)
    run_id = []
    return service, workflow, run_id


@pytest.mark.asyncio
async def test_question_answer_selection_pdf_release_survives_every_pause(tmp_path):
    calls = []
    service, workflow, run_id = build(tmp_path, calls)
    created = service.create(RunRequest(job_input='Full job description', input_type='text'), profile_snapshot=PROFILE,
                             provider='openai', model='fixture')
    run_id.append(created.id)
    view = await service.drive(created.id)
    assert view.pending.kind == 'ask_missing'
    service, workflow, _ = build(tmp_path, calls)
    view = await service.drive(created.id, AskMissing(action_id='answers', request_id=view.pending.request_id,
                                                    answers={'q1': 'Led a team.'}))
    assert view.pending.kind == 'present_suggestions'
    review = view.pending
    assert review.payload['reject_all']['projected_profile']['summary'] == 'Original summary.'
    preview = workflow.content_preview(created.id, review.review_id, review.source_revision, ['p1'])
    assert preview.projected_profile['summary'] == 'Selected summary.'
    # Test only substitutes external tools; storage, projection, render, guard and release are real.
    service, workflow, current_id = build(tmp_path, calls)
    current_id.append(created.id)
    view = await service.drive(created.id, PresentSuggestions(action_id='content', review_id=review.review_id,
        source_revision=review.source_revision, approved_ids=['p1'], content_hash=preview.manifest.content_hash))
    assert view.pending is not None, view
    assert view.pending.kind == 'review_pdf'
    pdf_review = view.pending.review
    assert len(calls) == 3
    from resume_agent.release_service import ReleaseService
    draft = ReleaseService(service.store).get_preview(created.id)
    service, workflow, _ = build(tmp_path, calls)
    view = await service.drive(created.id, ReviewPdf(action_id='release', decision='approve',
        **{k: getattr(pdf_review, k) for k in ('review_id', 'content_hash', 'render_hash', 'pdf_hash')}))
    assert view.status == 'complete'
    assert ReleaseService(service.store).get_final(created.id) == draft
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_stale_selected_hash_conflicts_before_render(tmp_path):
    calls = []
    service, workflow, run_id = build(tmp_path, calls, questions=False)
    created = service.create(RunRequest(job_input='Engineer', input_type='text'), profile_snapshot=PROFILE)
    run_id.append(created.id)
    pending = (await service.drive(created.id)).pending
    assert pending.kind == 'present_suggestions'
    with pytest.raises(Conflict):
        await service.drive(created.id, PresentSuggestions(action_id='stale', review_id=pending.review_id,
            source_revision=pending.source_revision, approved_ids=['p1'], content_hash=pending.content_hash))
    assert len(calls) == 3
    assert not (tmp_path / 'output').exists()
    assert not list((tmp_path / 'runs').rglob('*.pdf'))


@pytest.mark.asyncio
async def test_runtime_import_uses_durable_model_task_and_never_autosaves(tmp_path):
    from resume_agent.config import ResumeAgentSettings
    from resume_agent.runtime import Runtime
    calls = []

    async def model(stage, schema, messages):
        calls.append(stage)
        return PROFILE.model_dump(mode='json')

    runtime = Runtime(root=tmp_path, settings=ResumeAgentSettings(provider='openai'),
                      model=model, tool_finder=lambda _: '/local')
    created = runtime.imports.create(b'Complete source text', 'resume.tex')
    draft = await runtime.imports.drive(created['id'])
    assert draft['status'] == 'pending_review'
    assert calls == ['import_profile']
    checkpoint = read_v2_checkpoint(tmp_path / 'state.sqlite', 'operation', created['id'])
    tasks = checkpoint['values']['model_tasks']
    assert len(tasks) == 1 and next(iter(tasks.values()))['attempts'] == 1
    assert runtime.profiles.load_snapshot() is None
    reopened = Runtime(root=tmp_path, settings=ResumeAgentSettings(provider='ollama'), model=model)
    assert reopened.imports.get(created['id'])['draft'] == draft['draft']
    assert calls == ['import_profile']


@pytest.mark.asyncio
async def test_accepted_pdf_approval_recovers_same_export_without_model_work(tmp_path):
    from resume_agent.contracts import Continue
    calls = []
    service, workflow, run_id = build(tmp_path, calls, questions=False)
    run = service.create(RunRequest(job_input='Engineer', input_type='text'), profile_snapshot=PROFILE)
    run_id.append(run.id)
    pending = (await service.drive(run.id)).pending
    preview = workflow.content_preview(run.id, pending.review_id, pending.source_revision, [])
    view = await service.drive(run.id, PresentSuggestions(action_id='content', review_id=pending.review_id,
        source_revision=pending.source_revision, approved_ids=[], content_hash=preview.manifest.content_hash))
    review = view.pending.review
    class Crash(BaseException):
        pass
    def crash(stage):
        if stage == 'after_copy':
            raise Crash()
    workflow.release._crash_hook = crash
    with pytest.raises(Crash):
        await service.drive(run.id, ReviewPdf(action_id='approval', review_id=review.review_id,
            content_hash=review.content_hash, render_hash=review.render_hash, pdf_hash=review.pdf_hash, decision='approve'))
    reopened, _, _ = build(tmp_path, calls, questions=False)
    assert reopened.get(run.id).status == 'interrupted'
    completed = await reopened.drive(run.id, Continue(action_id='recover'))
    assert completed.status == 'complete', completed
    assert completed.release.pdf_hash == review.pdf_hash
    assert len(calls) == 3


def test_run_captures_allowlisted_review_provenance_as_detached_fixed_input(tmp_path):
    from resume_agent.config import ResumeAgentSettings
    from resume_agent.runtime import Runtime
    runtime = Runtime(root=tmp_path, settings=ResumeAgentSettings(provider='openai', openai_api_key='secret'),
                      tool_finder=lambda _: '/local')
    runtime.profiles.save_reviewed(None, PROFILE, {'import_id': 'import-one', 'arbitrary_secret': 'never-persist'})
    run = runtime.create_run(RunRequest(job_input='Full JD', input_type='text'))
    fixed = runtime.store.input('run', run.id)
    assert fixed['profile_provenance']['import_id'] == 'import-one'
    assert fixed['profile_provenance']['reviewed_revision'] == fixed['profile_revision']
    assert 'never-persist' not in str(fixed)
    fixed['profile_provenance']['import_id'] = 'mutated'
    reopened = RunStore(runtime.store.library_path, runtime.store.checkpoint_path)
    assert reopened.input('run', run.id)['profile_provenance']['import_id'] == 'import-one'


@pytest.mark.asyncio
async def test_cancelled_inflight_model_never_presents_or_exports_result(tmp_path):
    import asyncio

    from resume_agent.workflow import Workflow
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = []
    async def model(stage, schema, messages):
        calls.append(stage)
        entered.set()
        await finish.wait()
        return {'company': 'Example', 'role_title': 'Engineer'}
    store = RunStore(tmp_path / 'library.sqlite', tmp_path / 'state.sqlite')
    workflow = Workflow(store, artifacts_root=tmp_path / 'runs', output_dir=tmp_path / 'output', model=model)
    runs = RunService(store, driver=workflow.drive, action_validator=workflow.validate_action)
    run = runs.create(RunRequest(job_input='Full JD', input_type='text'), profile_snapshot=PROFILE)
    task = asyncio.create_task(runs.drive(run.id))
    await entered.wait()
    runs.cancel(run.id)
    finish.set()
    view = await task
    assert view.status == 'cancelled' and view.pending is None
    assert calls == ['extract_jd']
    assert not (tmp_path / 'output').exists()


@pytest.mark.asyncio
async def test_zero_proposals_still_requires_content_then_pdf_review(tmp_path):
    from resume_agent.content_review import expected_display_text
    from resume_agent.schemas import RenderManifest
    from resume_agent.tools.tectonic_compile import CompileResult
    from resume_agent.workflow import Workflow
    from tests.test_approved_render import images
    from tests.test_pdf_content_check import make_pdf
    calls = []
    async def model(stage, schema, messages):
        calls.append(stage)
        return ({'company': 'Example', 'role_title': 'Engineer'} if stage == 'extract_jd'
                else {'questions': []} if stage == 'questions' else {'proposals': []})
    store = RunStore(tmp_path / 'library.sqlite', tmp_path / 'state.sqlite')
    run_id = []
    def compiler(source, *, output_dir):
        values = read_v2_checkpoint(store.checkpoint_path, 'run', run_id[0])['values']
        pdf = make_pdf(output_dir / 'resume.pdf', expected_display_text(RenderManifest.model_validate(values['manifest'])))
        return CompileResult(True, str(pdf), [], '')
    workflow = Workflow(store, artifacts_root=tmp_path / 'runs', output_dir=tmp_path / 'output', model=model,
                        compile_adapter=compiler, image_adapter=images)
    runs = RunService(store, driver=workflow.drive, action_validator=workflow.validate_action)
    run = runs.create(RunRequest(job_input='Complete JD', input_type='text'), profile_snapshot=PROFILE)
    run_id.append(run.id)
    pending = (await runs.drive(run.id)).pending
    assert pending.kind == 'present_suggestions' and pending.proposal_ids == []
    assert not list((tmp_path / 'runs').rglob('*.pdf'))
    view = await runs.drive(run.id, PresentSuggestions(action_id='reject-all-content', review_id=pending.review_id,
        source_revision=pending.source_revision, approved_ids=[], content_hash=pending.content_hash))
    assert view.pending.kind == 'review_pdf'
    from pypdf import PdfReader
    draft_pdf = next((tmp_path / 'runs').rglob('resume.pdf'))
    assert 'Original summary.' in PdfReader(draft_pdf).pages[0].extract_text()
    review = view.pending.review
    view = await runs.drive(run.id, ReviewPdf(action_id='reject-pdf', decision='reject', review_id=review.review_id,
        content_hash=review.content_hash, render_hash=review.render_hash, pdf_hash=review.pdf_hash))
    assert view.status == 'cancelled'
    assert list((tmp_path / 'runs').rglob('resume.pdf'))
    assert not (tmp_path / 'output').exists()


@pytest.mark.asyncio
async def test_question_boundary_rejects_candidate_rewrite_fields(tmp_path):
    from resume_agent.workflow import Workflow
    calls = []
    async def model(stage, schema, messages):
        calls.append(stage)
        if stage == 'extract_jd':
            return {'company': 'Example', 'role_title': 'Engineer'}
        return {'questions': [{'id': 'q1', 'prompt': 'Question?', 'why_asking': 'Evidence',
                               'rewritten_profile': PROFILE.model_dump(mode='json')}]}
    store = RunStore(tmp_path / 'library.sqlite', tmp_path / 'state.sqlite')
    driver = Workflow(store, artifacts_root=tmp_path / 'runs', output_dir=tmp_path / 'output', model=model)
    service = RunService(store, driver=driver.drive, action_validator=driver.validate_action)
    run = service.create(RunRequest(job_input='Full JD', input_type='text'), profile_snapshot=PROFILE)
    view = await service.drive(run.id)
    assert view.status == 'failed'
    assert view.diagnostics[0].code == 'invalid_output'
    assert calls == ['extract_jd', 'questions', 'questions']


@pytest.mark.asyncio
async def test_enabled_hr_failure_is_durable_advisory_and_cannot_rewrite(tmp_path):
    from resume_agent.config import ResumeAgentSettings
    calls = []
    service, workflow, run_id = build(tmp_path, calls, questions=False)
    original = workflow.model
    async def model(stage, schema, messages):
        if stage == 'hr_advisory':
            calls.append((stage, messages))
            raise RuntimeError('SECRET provider message')
        return await original(stage, schema, messages)
    workflow.model, workflow.settings = model, ResumeAgentSettings()
    run = service.create(RunRequest(job_input='Engineer', input_type='text'), profile_snapshot=PROFILE)
    run_id.append(run.id)
    pending = (await service.drive(run.id)).pending
    view = await service.drive(run.id, PresentSuggestions(action_id='content', review_id=pending.review_id,
        source_revision=pending.source_revision, approved_ids=[], content_hash=pending.content_hash))
    assert view.pending.kind == 'review_pdf'
    hr = next(a for a in view.pending.payload['advisories'] if a['source'] == 'hr')
    assert hr['status'] == 'unavailable'
    assert hr['diagnostics'] == ['provider_unknown']
    assert 'SECRET' not in str(view)
    tasks = read_v2_checkpoint(service.store.checkpoint_path, 'run', run.id)['values']['model_tasks']
    assert any(t['stage'] == 'hr_advisory' and t['attempts'] == 1 for t in tasks.values())


@pytest.mark.asyncio
async def test_tampered_draft_approval_conflicts_before_command_acceptance(tmp_path):
    calls = []
    service, workflow, run_id = build(tmp_path, calls, questions=False)
    run = service.create(RunRequest(job_input='Full JD', input_type='text'), profile_snapshot=PROFILE)
    run_id.append(run.id)
    pending = (await service.drive(run.id)).pending
    view = await service.drive(run.id, PresentSuggestions(action_id='content', review_id=pending.review_id,
        source_revision=pending.source_revision, approved_ids=[], content_hash=pending.content_hash))
    review = view.pending.review
    pdf = next((tmp_path / 'runs').rglob('resume.pdf'))
    original = pdf.read_bytes()
    pdf.write_bytes(b'replaced bytes')
    approval = ReviewPdf(action_id='approve-tampered', decision='approve', review_id=review.review_id,
        content_hash=review.content_hash, render_hash=review.render_hash, pdf_hash=review.pdf_hash)
    with pytest.raises(Conflict):
        await service.drive(run.id, approval)
    assert service.get(run.id).pending == view.pending
    with service.store.connection() as conn:
        assert service.store.action('run', run.id, approval.action_id, conn) is None
    pdf.write_bytes(original)
    assert (await service.drive(run.id, approval)).status == 'complete'


@pytest.mark.asyncio
async def test_layout_failure_preserves_page_counts_and_review_remedies(tmp_path):
    from tests.test_approved_render import Compiler
    calls = []
    service, workflow, run_id = build(tmp_path, calls, questions=False)
    workflow.compile_adapter = Compiler([(3, ''), (3, '')])
    run = service.create(RunRequest(job_input='Full JD', input_type='text'), profile_snapshot=PROFILE)
    run_id.append(run.id)
    pending = (await service.drive(run.id)).pending
    result = await service.drive(run.id, PresentSuggestions(action_id='content', review_id=pending.review_id,
        source_revision=pending.source_revision, approved_ids=[], content_hash=pending.content_hash))
    assert result.status == 'failed' and result.diagnostics[0].code == 'layout_limit_exceeded'
    values = read_v2_checkpoint(service.store.checkpoint_path, 'run', run.id)['values']
    assert [candidate['page_count'] for candidate in values['render_failure']['candidates']] == [3, 3]
    assert values['render_failure']['remedies']
    assert service.store.release(run.id) is None

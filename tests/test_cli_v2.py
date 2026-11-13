"""Interactive clients review the same durable service data."""
import pytest

from resume_agent.contracts import RunRequest
from tests.test_v2_api import services


@pytest.mark.asyncio
async def test_noninteractive_cli_preserves_durable_pending_without_prompt(tmp_path):
    from resume_agent.cli import _review_v2_run
    runtime, calls = services(tmp_path)
    run = runtime.create_run(RunRequest(job_input='Complete job', input_type='text'))
    pending = await runtime.runs.drive(run.id)
    def forbidden(*args):
        raise AssertionError('noninteractive mode must not prompt')
    result = await _review_v2_run(runtime, run.id, interactive=False, ask=forbidden)
    assert result.id == run.id
    assert result.pending == pending.pending
    assert calls == ['extract_jd', 'questions', 'proposals']


@pytest.mark.asyncio
async def test_empty_input_does_not_approve_content_or_call_renderer(tmp_path):
    from resume_agent.cli import _review_v2_run
    runtime, calls = services(tmp_path)
    run = runtime.create_run(RunRequest(job_input='Complete job', input_type='text'))
    pending = await runtime.runs.drive(run.id)
    result = await _review_v2_run(runtime, run.id, interactive=True, ask=lambda _: '')
    assert result.pending == pending.pending
    assert result.status == 'awaiting-input'
    assert runtime.store.release(run.id) is None
    assert not list((tmp_path / 'runs').rglob('*.pdf'))


@pytest.mark.asyncio
async def test_import_blank_input_deliberately_rejects_without_profile_save(tmp_path):
    from resume_agent.cli import _review_v2_import
    runtime, calls = services(tmp_path)
    before = runtime.profiles.load_snapshot().revision
    operation = runtime.imports.create(b'Complete source.', 'resume.tex')
    draft = await runtime.imports.drive(operation['id'])
    result = await _review_v2_import(runtime, draft['id'], interactive=True, ask=lambda _: '')
    assert result['status'] == 'cancelled'
    assert result['source']['text'] == 'Complete source.'
    assert runtime.profiles.load_snapshot().revision == before


@pytest.mark.asyncio
async def test_cli_displays_full_content_then_explicit_pdf_rejection(tmp_path):
    from resume_agent.checkpoint import read_v2_checkpoint
    from resume_agent.cli import _review_v2_run
    from resume_agent.content_review import expected_display_text
    from resume_agent.schemas import RenderManifest
    from resume_agent.tools.tectonic_compile import CompileResult
    from tests.test_approved_render import images
    from tests.test_pdf_content_check import make_pdf
    runtime, calls = services(tmp_path)
    runtime.workflow.output_dir = tmp_path / 'output'
    run = runtime.create_run(RunRequest(job_input='Full job', input_type='text'))
    def compiler(source, *, output_dir):
        manifest = read_v2_checkpoint(runtime.store.checkpoint_path, 'run', run.id)['values']['manifest']
        pdf = make_pdf(output_dir / 'resume.pdf', expected_display_text(RenderManifest.model_validate(manifest)))
        return CompileResult(True, str(pdf), [], '')
    runtime.workflow.compile_adapter, runtime.workflow.image_adapter = compiler, images
    await runtime.runs.drive(run.id)
    inputs = iter(['', 'approve', 'reject'])
    prompts = []
    def ask(message):
        prompts.append(message)
        return next(inputs)
    result = await _review_v2_run(runtime, run.id, interactive=True, ask=ask)
    assert result.status == 'cancelled'
    assert any('hash' in message for message in prompts)
    assert any('exact PDF' in message for message in prompts)
    assert not (tmp_path / 'output').exists()
    assert calls == ['extract_jd', 'questions', 'proposals']


def test_generate_command_uses_durable_runtime_and_non_tty_reports_id(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import resume_agent.runtime as module
    from resume_agent.cli import app
    runtime, calls = services(tmp_path)
    monkeypatch.setattr(module, 'Runtime', lambda **kwargs: runtime)
    result = CliRunner().invoke(app, ['generate', '--jd-text', 'Complete JD'])
    assert result.exit_code == 2, result.output
    assert calls == ['extract_jd', 'questions', 'proposals']
    run_id = runtime.store.run_ids()[0]
    assert run_id in result.output
    assert runtime.runs.get(run_id).pending.kind == 'present_suggestions'


@pytest.mark.asyncio
async def test_interactive_import_resume_continues_durable_attempt_then_reviews(tmp_path):
    from resume_agent.cli import _review_v2_import
    from resume_agent.config import ResumeAgentSettings
    from resume_agent.runtime import Runtime
    from tests.test_v2_workflow import PROFILE
    calls = []
    class Crash(BaseException):
        pass
    async def model(stage, schema, messages):
        calls.append(stage)
        if len(calls) == 1:
            raise Crash()
        return PROFILE
    runtime = Runtime(root=tmp_path, settings=ResumeAgentSettings(), model=model)
    operation = runtime.imports.create(b'Full original source', 'resume.tex')
    with pytest.raises(Crash):
        await runtime.imports.drive(operation['id'])
    assert runtime.imports.get(operation['id'])['status'] == 'interrupted'
    inputs = iter(['continue', ''])
    view = await _review_v2_import(runtime, operation['id'], interactive=True, ask=lambda _: next(inputs))
    assert view['status'] == 'cancelled'
    assert calls == ['import_profile', 'import_profile']
    assert runtime.profiles.load_snapshot() is None

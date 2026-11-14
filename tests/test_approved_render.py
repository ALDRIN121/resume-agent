"""Approved rendering preserves content and owns every external attempt."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from pypdf import PdfWriter

from resume_agent.artifacts import RunArtifacts, hash_file
from resume_agent.content_review import recompute_manifest
from resume_agent.schemas import DisplayField, DisplayOmission, RenderManifest
from resume_agent.tools.tectonic_compile import CompileResult


def manifest():
    result = RenderManifest(
        source_revision='a' * 64, approved_proposal_ids=['approved-1'],
        display_fields=[
            DisplayField(order=0, source_path='/personal/full_name', text='A & B',
                         kind='name', section='personal', group='personal'),
            DisplayField(order=1, source_path=None, text='Experience',
                         kind='heading', section='experience', group='experience'),
            DisplayField(order=2, source_path='/experience/0/bullets/0',
                         text='Helped cut p_95 from 450ms to 90ms (+80%-gain).',
                         kind='bullet', section='experience', group='0'),
            DisplayField(order=3, source_path='/projects/0/url',
                         text='https://example.com/a_b', visible_label='Link:',
                         kind='field', section='projects', group='0'),
            DisplayField(order=4, source_path='/projects/0/description',
                         text='Helped cut p_95 from 450ms to 90ms (+80%-gain).',
                         kind='field', section='projects', group='0'),
        ], omissions=[DisplayOmission(source_path='/summary', reason='approved omission')],
        template_version='approved-v2', layout_id='standard', content_hash='0' * 64,
    )
    return result.model_copy(update={'content_hash': recompute_manifest(result)})


def run(tmp_path):
    return RunArtifacts.create(str(uuid4()), tmp_path / 'runs')


class Compiler:
    """External compiler substitute; real files, PDF structure, and diagnostics."""
    def __init__(self, outcomes=((1, ''),)):
        self.outcomes = iter(outcomes)
        self.sources = []

    def __call__(self, source, *, output_dir):
        self.sources.append(source)
        pages, log = next(self.outcomes)
        if isinstance(pages, str):
            return CompileResult(False, None, ['external failure'], log, error_code=pages)
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=612, height=792)
        pdf = output_dir / 'resume.pdf'
        with pdf.open('xb') as stream:
            writer.write(stream)
        # Deliberately wrong page_count: orchestration must inspect actual PDF.
        return CompileResult(True, str(pdf), [], log, page_count=999)


def images(pdf_path, *, output_dir):
    path = output_dir / 'page_1.png'
    with path.open('xb') as stream:
        Image.new('RGB', (10, 10), 'white').save(stream, 'PNG')
    return [str(path)]


@pytest.mark.parametrize('damage', ['missing_page', 'duplicate_page'])
async def test_reopened_record_requires_distinct_image_for_every_page(tmp_path, damage):
    from dataclasses import replace

    from pypdf import PdfReader

    from resume_agent.approved_render import RenderError

    def all_images(pdf_path, *, output_dir):
        paths = []
        for index in range(len(PdfReader(pdf_path).pages)):
            path = output_dir / f'page_{index + 1}.png'
            Image.new('RGB', (10, 10), 'white').save(path, 'PNG')
            paths.append(str(path))
        return paths

    artifacts = run(tmp_path)
    record = await render(tmp_path, Compiler([(2, '')]), artifacts=artifacts,
                          image_adapter=all_images)
    if damage == 'missing_page':
        damaged = replace(record, image_paths=record.image_paths[:1],
                          image_hashes=record.image_hashes[:1])
    else:
        damaged = replace(record, image_paths=(record.image_paths[0],) * 2,
                          image_hashes=(record.image_hashes[0],) * 2)
    with pytest.raises(RenderError) as error:
        await render(tmp_path, artifacts=artifacts, resume_record=damaged)
    assert error.value.code == 'artifact_hash_mismatch'


async def test_reopened_record_rejects_nonimage_even_with_matching_hash(tmp_path):
    from dataclasses import replace

    from resume_agent.approved_render import RenderError

    artifacts = run(tmp_path)
    record = await render(tmp_path, artifacts=artifacts)
    damaged = replace(record, image_paths=(record.pdf_path,), image_hashes=(record.pdf_hash,))
    with pytest.raises(RenderError) as error:
        await render(tmp_path, artifacts=artifacts, resume_record=damaged)
    assert error.value.code == 'artifact_hash_mismatch'


async def render(tmp_path, compiler=None, **kwargs):
    from resume_agent.approved_render import render_approved
    return await render_approved(manifest(), kwargs.pop('artifacts', run(tmp_path)),
                                 compile_adapter=compiler or Compiler(),
                                 image_adapter=kwargs.pop('image_adapter', images), **kwargs)


def test_source_is_exact_ordered_and_escaped_without_rewrite():
    from resume_agent.approved_render import STANDARD, render_source
    approved = manifest()
    before = approved.model_dump()
    source = render_source(approved, STANDARD)
    assert source.index(r'A \& B') < source.index('Experience')
    exact = r'Helped cut p\_95 from 450ms to 90ms (+80\%-gain).'
    assert source.count(exact) == 2  # no duplicate-description suppression
    assert source.index('Link:') < source.index(r'https://example.com/a\_b')
    assert r'\bullet' not in source
    assert r'\small' not in source and r'\footnotesize' not in source
    assert r'\documentclass[10pt' in source and 'margin=0.65in' in source
    assert r'\hyphenpenalty=10000' in source and r'\exhyphenpenalty=10000' in source
    assert approved.model_dump() == before


@pytest.mark.asyncio
async def test_standard_record_uses_real_pdf_and_hashes(tmp_path):
    from resume_agent.approved_render import RenderRecord
    record = await render(tmp_path)
    assert record.layout_id == 'standard'
    assert record.page_count == 1 and not record.overflow
    assert record.pdf_hash == hash_file(record.pdf_path)
    assert record.content_hash == manifest().content_hash
    assert record.layout_params['font_size_pt'] == 10
    assert record.layout_params['margin_in'] == 0.65
    assert Path(record.log_path).exists() and Path(record.image_paths[0]).exists()
    assert RenderRecord.from_dict(record.to_dict()) == record


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', [(3, ''), (1, r'Overfull \hbox (2.0pt too wide)'),
                                   (1, r'Overfull \vbox (3pt too high)')])
async def test_constraint_failure_tries_compact_without_changing_text(tmp_path, outcome):
    compiler = Compiler([outcome, (1, '')])
    record = await render(tmp_path, compiler)
    assert record.layout_id == 'compact' and record.attempt_number == 2
    assert record.layout_params['font_size_pt'] == 10
    assert record.layout_params['margin_in'] == 0.5
    assert record.content_hash == manifest().content_hash
    for source in compiler.sources:
        assert r'450ms to 90ms (+80\%-gain)' in source
        assert source.count('Helped') == 2


@pytest.mark.asyncio
async def test_two_layouts_fail_with_remedies_and_keep_both_pdfs(tmp_path):
    from resume_agent.approved_render import RenderError
    artifacts = run(tmp_path)
    with pytest.raises(RenderError) as error:
        await render(tmp_path, Compiler([(3, ''), (2, r'Overfull \hbox')]),
                     artifacts=artifacts, max_pages=1)
    assert error.value.code == 'layout_limit_exceeded'
    assert len(error.value.details['candidates']) == 2
    assert error.value.details['remedies']
    assert artifacts.attempt(1).pdf_path.exists() and artifacts.attempt(2).pdf_path.exists()


@pytest.mark.asyncio
async def test_timeout_retries_identical_source_and_preserves_all_logs(tmp_path):
    artifacts = run(tmp_path)
    compiler = Compiler([('compile_timeout', 'timeout 1'), ('compile_timeout', 'timeout 2'),
                         (1, 'success')])
    record = await render(tmp_path, compiler, artifacts=artifacts)
    assert record.attempt_number == 3
    assert len(set(compiler.sources)) == 1
    assert [artifacts.attempt(i).log_path.read_text() for i in (1, 2, 3)] == [
        'timeout 1', 'timeout 2', 'success']


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['compiler_unavailable', 'compile_syntax', 'compile_environment'])
async def test_nonretryable_compile_failure_stops_immediately(tmp_path, code):
    from resume_agent.approved_render import RenderError
    artifacts = run(tmp_path)
    with pytest.raises(RenderError) as error:
        await render(tmp_path, Compiler([(code, code)]), artifacts=artifacts)
    assert error.value.code == code
    assert not (artifacts.run_dir / 'attempts' / '2').exists()


@pytest.mark.asyncio
async def test_timeout_budget_does_not_restart_on_reopen(tmp_path):
    from resume_agent.approved_render import RenderError
    artifacts = run(tmp_path)
    with pytest.raises(RenderError) as first:
        await render(tmp_path, Compiler([('compile_timeout', '1')] * 3), artifacts=artifacts)
    assert first.value.code == 'compile_timeout'
    with pytest.raises(RenderError) as second:
        await render(tmp_path, Compiler([]), artifacts=artifacts)
    assert second.value.code == 'compile_timeout'
    assert not (artifacts.run_dir / 'attempts' / '4').exists()


@pytest.mark.asyncio
async def test_completed_render_reopens_exact_bytes_and_rejects_tamper(tmp_path):
    from resume_agent.approved_render import RenderError
    artifacts = run(tmp_path)
    first = await render(tmp_path, artifacts=artifacts)
    second = await render(tmp_path, Compiler([]), artifacts=artifacts)
    assert second == first
    Path(first.pdf_path).write_bytes(b'changed')
    with pytest.raises(RenderError) as error:
        await render(tmp_path, Compiler([]), artifacts=artifacts)
    assert error.value.code == 'artifact_hash_mismatch'


@pytest.mark.asyncio
async def test_invalid_manifest_never_starts_attempt(tmp_path):
    from resume_agent.approved_render import RenderError, render_approved
    approved = manifest()
    approved = approved.model_copy(update={'display_fields': [
        *approved.display_fields[:2],
        approved.display_fields[2].model_copy(update={'text': 'Led 90ms to 450ms'}),
        *approved.display_fields[3:]]})
    artifacts = run(tmp_path)
    with pytest.raises(RenderError) as error:
        await render_approved(approved, artifacts, compile_adapter=Compiler([]))
    assert error.value.code == 'invalid_manifest'
    assert not list((artifacts.run_dir / 'attempts').iterdir())


@pytest.mark.asyncio
async def test_cancel_after_compile_never_renders_images(tmp_path):
    from resume_agent.approved_render import RenderError
    cancelled = False
    def checkpoint(event):
        nonlocal cancelled
        if event['stage'] == 'compile' and event['phase'] == 'after':
            cancelled = True
    with pytest.raises(RenderError) as error:
        await render(tmp_path, checkpoint=checkpoint, check_cancelled=lambda: cancelled,
                     image_adapter=lambda *a, **k: pytest.fail('images after cancellation'))
    assert error.value.code == 'cancelled'


@pytest.mark.asyncio
async def test_pending_attempt_requires_explicit_recovery_and_is_not_overwritten(tmp_path):
    from resume_agent.approved_render import RenderError
    artifacts = run(tmp_path)
    artifacts.attempt(1).source_path.write_text('interrupted source')
    with pytest.raises(RenderError) as error:
        await render(tmp_path, artifacts=artifacts)
    assert error.value.code == 'recovery_required'
    record = await render(tmp_path, artifacts=artifacts, recover_pending=True)
    assert record.attempt_number == 2
    assert artifacts.attempt(1).source_path.read_text() == 'interrupted source'


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['missing', 'malformed', 'empty', 'encrypted'])
async def test_invalid_pdf_is_typed_failure(tmp_path, mode):
    from resume_agent.approved_render import RenderError
    def compile_bad(source, *, output_dir):
        pdf = output_dir / 'resume.pdf'
        if mode == 'malformed':
            pdf.write_bytes(b'not a PDF')
        elif mode != 'missing':
            writer = PdfWriter()
            if mode == 'encrypted':
                writer.add_blank_page(width=612, height=792)
                writer.encrypt('secret')
            with pdf.open('xb') as stream:
                writer.write(stream)
        return CompileResult(True, str(pdf), [], '')
    with pytest.raises(RenderError) as error:
        await render(tmp_path, compile_bad)
    assert error.value.code == 'invalid_pdf'


@pytest.mark.asyncio
async def test_no_images_is_typed_failure(tmp_path):
    from resume_agent.approved_render import RenderError
    with pytest.raises(RenderError) as error:
        await render(tmp_path, image_adapter=lambda *a, **k: [])
    assert error.value.code == 'images_unavailable'


@pytest.mark.asyncio
async def test_checkpoint_has_hashes_paths_and_external_boundaries(tmp_path):
    events = []
    record = await render(tmp_path, checkpoint=events.append)
    assert [(e['stage'], e['phase']) for e in events] == [
        ('compile', 'before'), ('compile', 'after'), ('images', 'before'), ('images', 'after')]
    assert all(e['content_hash'] == record.content_hash for e in events)
    assert all(e['attempt_number'] == 1 for e in events)
    stored = json.loads(Path(record.pdf_path).with_name('manifest.json').read_text())
    assert stored['record']['pdf_hash'] == record.pdf_hash


@pytest.mark.asyncio
async def test_v2_entry_and_advisories_never_use_writer_or_repair(tmp_path, monkeypatch):
    from resume_agent.agents.hr_review import hr_review_approved
    from resume_agent.agents.pdf_validator import review_approved_images
    from resume_agent.agents.resume_generator import generate_approved_resume
    from resume_agent.approved_render import lint_approved
    def forbidden(*args, **kwargs):
        pytest.fail('writer/repair must not be invoked to change Helped or reverse 450ms/90ms')
    monkeypatch.setattr('resume_agent.agents.resume_generator.get_chat_model', forbidden)
    approved = manifest()
    frozen = approved.model_dump_json()
    record = await generate_approved_resume(approved, run(tmp_path),
                                            compile_adapter=Compiler(), image_adapter=images)
    def advice(_):
        return {'status': 'warning', 'diagnostics': ['Prefer Led and 90ms to 450ms'],
                'latex_source': 'Led 90ms to 450ms', 'validation_passed': False}
    hr = await hr_review_approved(approved, reviewer=advice)
    vision = await review_approved_images(record, reviewer=advice)
    lint = lint_approved(approved)
    assert hr.status == 'warning' and vision.status == 'warning'
    assert 'Prefer Led and 90ms to 450ms' in hr.diagnostics
    assert 'validation_passed' not in hr.to_dict()
    assert lint.source == 'lint'
    assert approved.model_dump_json() == frozen
    assert 'Helped' in Path(record.source_path).read_text()


@pytest.mark.asyncio
async def test_advisory_errors_remain_visible_and_do_not_mutate(tmp_path):
    from resume_agent.agents.hr_review import hr_review_approved
    from resume_agent.agents.pdf_validator import review_approved_images
    def unavailable(_):
        raise RuntimeError('unavailable')
    approved = manifest()
    record = await render(tmp_path)
    assert (await hr_review_approved(approved)).status == 'disabled'
    failed = await hr_review_approved(approved, reviewer=unavailable)
    assert failed.status == 'unavailable' and failed.diagnostics
    failed_vision = await review_approved_images(record, reviewer=unavailable)
    assert failed_vision.status == 'unavailable' and failed_vision.diagnostics


@pytest.mark.asyncio
async def test_recover_compiled_pdf_reuses_bytes_after_image_interruption(tmp_path):
    from resume_agent.approved_render import RenderError
    artifacts = run(tmp_path)
    def interrupted(pdf_path, *, output_dir):
        (output_dir / 'partial.png').write_bytes(b'partial')
        raise RuntimeError('interrupted image tool')
    with pytest.raises(RenderError):
        await render(tmp_path, artifacts=artifacts, image_adapter=interrupted)
    pdf_hash = hash_file(artifacts.attempt(1).pdf_path)
    with pytest.raises(RenderError) as error:
        await render(tmp_path, Compiler([]), artifacts=artifacts)
    assert error.value.code == 'recovery_required'
    record = await render(tmp_path, Compiler([]), artifacts=artifacts, recover_pending=True)
    assert record.attempt_number == 1 and record.pdf_hash == pdf_hash
    assert (artifacts.attempt(1).images_dir / '1' / 'partial.png').read_bytes() == b'partial'


@pytest.mark.asyncio
async def test_lint_reports_duplicate_without_suppressing_it():
    from resume_agent.approved_render import lint_approved
    approved = manifest()
    result = lint_approved(approved)
    assert result.status == 'warning'
    assert any('Repeated' in warning for warning in result.diagnostics)
    assert len(approved.display_fields) == 5


@pytest.mark.asyncio
async def test_image_count_covers_each_pdf_page(tmp_path):
    from resume_agent.approved_render import RenderError
    with pytest.raises(RenderError) as error:
        await render(tmp_path, Compiler([(2, '')]))
    assert error.value.code == 'images_unavailable'


@pytest.mark.asyncio
async def test_driver_callbacks_run_on_callers_thread(tmp_path):
    import threading
    caller_thread = threading.get_ident()
    def checkpoint(event):
        assert threading.get_ident() == caller_thread
    def check_cancelled():
        assert threading.get_ident() == caller_thread
        return False
    await render(tmp_path, checkpoint=checkpoint, check_cancelled=check_cancelled)


@pytest.mark.asyncio
async def test_interrupted_calls_consume_persisted_attempt_budget(tmp_path):
    from resume_agent.approved_render import RenderError
    artifacts = run(tmp_path)
    class Interrupted(BaseException):
        pass
    def interruption(source, *, output_dir):
        raise Interrupted('process interruption')
    for number in (1, 2, 3):
        # BaseException reproduces a hard interruption past source/budget persistence.
        with pytest.raises(Interrupted):
            await render(tmp_path, interruption, artifacts=artifacts, recover_pending=True)
        assert artifacts.attempt(number).source_path.exists()
    with pytest.raises(RenderError) as error:
        await render(tmp_path, Compiler([]), artifacts=artifacts, recover_pending=True)
    assert error.value.code == 'compile_interrupted'
    assert not (artifacts.run_dir / 'attempts' / '4').exists()


@pytest.mark.asyncio
async def test_image_adapter_cannot_change_source_after_compile(tmp_path):
    from resume_agent.approved_render import RenderError
    def change_source(pdf_path, *, output_dir):
        Path(pdf_path).with_name('source.tex').write_text('Led 90ms to 450ms')
        return images(pdf_path, output_dir=output_dir)
    with pytest.raises(RenderError) as error:
        await render(tmp_path, image_adapter=change_source)
    assert error.value.code == 'artifact_hash_mismatch'


@pytest.mark.asyncio
async def test_invalid_pdf_outcome_is_durable_and_not_recompiled(tmp_path):
    from resume_agent.approved_render import RenderError
    artifacts = run(tmp_path)
    def malformed(source, *, output_dir):
        path = output_dir / 'resume.pdf'
        path.write_bytes(b'bad PDF')
        return CompileResult(True, str(path), [], 'compiler returned bad PDF')
    with pytest.raises(RenderError) as first:
        await render(tmp_path, malformed, artifacts=artifacts)
    assert first.value.code == 'invalid_pdf'
    with pytest.raises(RenderError) as second:
        await render(tmp_path, Compiler([]), artifacts=artifacts, recover_pending=True)
    assert second.value.code == 'invalid_pdf'
    assert not (artifacts.run_dir / 'attempts' / '2').exists()


@pytest.mark.asyncio
async def test_nonimage_renderer_output_is_rejected(tmp_path):
    from resume_agent.approved_render import RenderError
    def invalid_images(pdf_path, *, output_dir):
        path = output_dir / 'page.png'
        path.write_text('not an image')
        return [str(path)]
    with pytest.raises(RenderError) as error:
        await render(tmp_path, image_adapter=invalid_images)
    assert error.value.code == 'images_unavailable'


@pytest.mark.asyncio
async def test_invalid_resume_record_has_typed_failure(tmp_path):
    from resume_agent.approved_render import RenderError
    with pytest.raises(RenderError) as error:
        await render(tmp_path, resume_record={'pdf_hash': 'wrong'})
    assert error.value.code == 'artifact_hash_mismatch'


@pytest.mark.asyncio
async def test_repeated_async_cancellation_waits_for_external_side_effects(tmp_path):
    import asyncio
    import threading
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    artifacts = run(tmp_path)
    def blocked(source, *, output_dir):
        started.set()
        release.wait(5)
        try:
            return Compiler()(source, output_dir=output_dir)
        finally:
            finished.set()
    task = asyncio.create_task(render(tmp_path, blocked, artifacts=artifacts))
    while not started.is_set():
        await asyncio.sleep(0.001)
    try:
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done(), 'Cancellation returned while compiler could still write PDF bytes'
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert finished.is_set()
    assert not list(artifacts.attempt(1).images_dir.iterdir())

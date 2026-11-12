"""Restart and legacy recovery use real SQLite, LangGraph and local bytes."""
from __future__ import annotations

import hashlib
import multiprocessing
from pathlib import Path

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite import SqliteSaver

from resume_agent.checkpoint import read_v2_checkpoint, write_v2_checkpoint
from resume_agent.contracts import (
    AskMissingRequest,
    Continue,
    DriverResult,
    PdfReview,
    PdfReviewRequest,
    RunRequest,
    SuggestionReviewRequest,
    content_hash,
)
from resume_agent.run_service import RunService
from resume_agent.run_store import RunStore

# Real canonical PDF/manifest setup.
from tests.test_release_service import Crash, release, reopen
from tests.test_release_service import setup as setup

PROFILE = {"personal": {"full_name": "Original Candidate", "email": "old@example.test"}}


def make_service(root, driver=None):
    return RunService(RunStore(root / 'library.sqlite', root / 'state.sqlite'), driver=driver)


def v1(root, values=None, run_id='legacy/../paused'):
    values = values if values is not None else {
        'schema_version': 1, 'raw_input': 'The entire original job description', 'input_type': 'text',
        'base_resume': PROFILE, 'hitl_answers': {'old-q': 'Saved evidence'},
        'approved_suggestion_ids': ['old-approval'], 'tailored_resume': PROFILE,
        'latex_source': 'old latex', 'pdf_path': '/old.pdf', 'generator_retries': 8,
        'validation_passed': True,
    }
    with SqliteSaver.from_conn_string(str(root / 'state.sqlite')) as saver:
        checkpoint = empty_checkpoint()
        checkpoint['channel_values'] = values
        checkpoint['channel_versions'] = {key: 1 for key in values}
        saver.put({'configurable': {'thread_id': run_id, 'checkpoint_ns': ''}}, checkpoint,
                  {'source': 'update', 'step': 1}, checkpoint['channel_versions'])
    return run_id


def child_recover(root, ready, output):
    ready.wait(15)
    try:
        output.put(('ok', make_service(Path(root)).recover_legacy('legacy/../paused').id))
    except BaseException as exc:
        output.put(('error', str(exc)))


def test_safe_v1_inspection_does_not_mutate_original_database(tmp_path):
    from resume_agent.checkpoint import inspect_v1_checkpoint
    run_id = v1(tmp_path)
    path = tmp_path / 'state.sqlite'
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    saved = inspect_v1_checkpoint(path, run_id)
    assert saved['raw_input'] == 'The entire original job description'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert inspect_v1_checkpoint(path, 'unknown') is None
    assert not (tmp_path / 'absent.sqlite').exists()
    assert inspect_v1_checkpoint(tmp_path / 'absent.sqlite', run_id) is None


def test_legacy_child_fixed_source_fresh_reviews_and_restart_idempotency(tmp_path):
    from resume_agent.checkpoint import inspect_v1_checkpoint
    run_id = v1(tmp_path)
    original = inspect_v1_checkpoint(tmp_path / 'state.sqlite', run_id)
    svc = make_service(tmp_path)
    recovered = svc.recover_legacy(run_id, provider='selected', model='new-model')
    assert recovered.status == 'queued' and recovered.pending is None
    assert recovered.id != run_id
    fixed = svc.store.input('run', recovered.id)
    assert fixed['request']['parent_run_id'] == run_id
    assert fixed['request']['job_input'] == original['raw_input']
    assert fixed['profile_snapshot']['personal']['full_name'] == 'Original Candidate'
    assert (fixed['provider'], fixed['model']) == ('selected', 'new-model')
    values = read_v2_checkpoint(svc.store.checkpoint_path, 'run', recovered.id)['values']
    assert values == {'legacy_parent': run_id, 'legacy_evidence_answers': {'old-q': 'Saved evidence'}}
    assert make_service(tmp_path).recover_legacy(run_id).id == recovered.id
    assert inspect_v1_checkpoint(svc.store.checkpoint_path, run_id) == original
    with svc.store.connection() as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM actions').fetchone()[0] == 0
        assert conn.execute('SELECT value FROM migration_meta WHERE key=?', ('legacy_recovery:' + run_id,)).fetchone()[0] == recovered.id
    assert not (tmp_path / 'paused').exists()


@pytest.mark.parametrize('missing', ['base_resume', 'raw_input', 'input_type'])
def test_legacy_missing_original_source_fails_explicitly(tmp_path, missing):
    values = {'schema_version': 1, 'base_resume': PROFILE, 'raw_input': 'full job', 'input_type': 'text'}
    del values[missing]
    run_id = v1(tmp_path, values)
    with pytest.raises(ValueError, match='legacy_source_missing'):
        make_service(tmp_path).recover_legacy(run_id)


def test_two_processes_recover_exactly_one_child(tmp_path):
    v1(tmp_path)
    make_service(tmp_path)
    context = multiprocessing.get_context('spawn')
    ready, output = context.Event(), context.Queue()
    children = [context.Process(target=child_recover, args=(str(tmp_path), ready, output)) for _ in range(2)]
    for child in children:
        child.start()
    ready.set()
    results = [output.get(timeout=25) for _ in children]
    for child in children:
        child.join(10)
        assert child.exitcode == 0
    assert all(result[0] == 'ok' for result in results), results
    assert len({result[1] for result in results}) == 1


@pytest.mark.parametrize('pending', [
    AskMissingRequest(request_id='original-q', question_ids=['one']),
    SuggestionReviewRequest(review_id='original-content', source_revision=content_hash('source'), content_hash=content_hash('content'), proposal_ids=['proposal']),
    PdfReviewRequest(review=PdfReview(review_id='original-pdf', content_hash=content_hash('content'),
        render_hash=content_hash('render'), pdf_hash=content_hash('pdf'), template_version='v', layout_id='standard')),
])
async def test_restart_reconstructs_identical_human_pause_without_external_work(tmp_path, pending):
    calls = []
    async def driver(ctx):
        calls.append(1)
        ctx.control.checkpoint({'attempts': 2})
        return DriverResult(status='awaiting-input', pending=pending)
    svc = make_service(tmp_path, driver)
    run = svc.create(RunRequest(job_input='full job', input_type='text'), profile_snapshot=PROFILE)
    paused = await svc.drive(run.id)
    with svc.store.connection() as conn:
        svc.store.update('run', run.id, status='running', pending=None, conn=conn)
    views = make_service(tmp_path, driver).reconcile_startup()
    assert views[0].pending == paused.pending
    assert len(calls) == 1


@pytest.mark.parametrize('stage', ['model', 'compile'])
async def test_interrupted_stage_requires_explicit_continue_and_retains_budget(tmp_path, stage):
    calls = []
    async def driver(ctx):
        calls.append(ctx.checkpoint.copy())
        ctx.control.checkpoint({'attempts': ctx.checkpoint['attempts'] + 1})
        return DriverResult(status='awaiting-input', pending=AskMissingRequest(request_id='fresh', question_ids=[]))
    svc = make_service(tmp_path, driver)
    run = svc.create(RunRequest(job_input='job', input_type='text'), profile_snapshot=PROFILE)
    write_v2_checkpoint(svc.store.checkpoint_path, 'run', run.id, {'schema_version': 2,
        'values': {'stage': stage, 'attempts': 2, 'applied_action_ids': ['applied']},
        'index': {'status': 'running'}, 'inflight_action_ids': []})
    with svc.store.connection() as conn:
        svc.store.update('run', run.id, status='running', pending=None, conn=conn)
    reopened = make_service(tmp_path, driver)
    assert reopened.reconcile_startup()[0].status == 'interrupted'
    assert calls == []
    assert (await reopened.drive(run.id, Continue(action_id='continue'))).status == 'awaiting-input'
    assert calls == [{'stage': stage, 'attempts': 2, 'applied_action_ids': ['applied']}]


async def test_boot_completes_queued_cancellation_without_driver(tmp_path):
    svc = make_service(tmp_path)
    run = svc.create(RunRequest(job_input='job', input_type='text'), profile_snapshot=PROFILE)
    with svc.store.connection() as conn:
        svc.store.update('run', run.id, status='running', pending=None, conn=conn)
    svc.store.cancel('run', run.id)
    assert make_service(tmp_path).reconcile_startup()[0].status == 'cancelled'


@pytest.mark.parametrize('status', ['complete', 'cancelled', 'failed'])
def test_terminal_legacy_history_cannot_be_recovered(tmp_path, status):
    from resume_agent import library
    library.init_db(library_path=tmp_path / 'library.sqlite')
    run_id = v1(tmp_path)
    library.upsert_resume(thread_id=run_id, company='Original', status=status,
                          library_path=tmp_path / 'library.sqlite')
    with pytest.raises(ValueError, match='legacy_recovery_not_allowed'):
        make_service(tmp_path).recover_legacy(run_id)


def test_malformed_checkpoint_and_missing_checkpoint_fail_explicitly(tmp_path):
    svc = make_service(tmp_path)
    with pytest.raises(ValueError, match='legacy_checkpoint_missing'):
        svc.recover_legacy('absent')
    svc.store.checkpoint_path.write_bytes(b'not sqlite')
    with pytest.raises(ValueError, match='legacy_checkpoint_invalid'):
        svc.recover_legacy('malformed')


def test_failed_evidence_checkpoint_rolls_back_child_and_link(tmp_path, monkeypatch):
    import resume_agent.checkpoint as checkpoint
    v1(tmp_path)
    svc = make_service(tmp_path)
    def fail(*args, **kwargs):
        raise OSError('cannot persist evidence')
    monkeypatch.setattr(checkpoint, 'write_v2_checkpoint', fail)
    with pytest.raises(OSError, match='cannot persist evidence'):
        svc.recover_legacy('legacy/../paused')
    assert svc.store.legacy_child('legacy/../paused') is None
    assert svc.store.run_ids() == []


def test_boot_finishes_release_cancellation_cleanup_without_copy(setup):
    def crash(stage):
        if stage == 'after_copy':
            raise Crash(stage)
    with pytest.raises(Crash):
        release(setup, reopen(setup, crash))
    store, _, run_id, record, _, _ = setup
    plan = reopen(setup).inspect(run_id).plan
    store.cancel('run', run_id)
    views = RunService(RunStore(store.library_path, store.checkpoint_path)).reconcile_startup()
    assert views[0].status == 'cancelled'
    assert not plan.destination.exists()
    assert not plan.temporary_path.exists()
    assert Path(record.pdf_path).exists()


def test_released_checkpoint_gap_and_separate_artifact_availability(setup):
    from resume_agent import library
    store, _, run_id, record, _, _ = setup
    completed = release(setup)
    library.init_db(library_path=store.library_path)
    library.upsert_resume(thread_id=run_id, company='Example', status='complete',
                          pdf_path=completed.release.destination, library_path=store.library_path)
    with store.connection() as conn:
        store.update('run', run_id, status='running', pending=None, conn=conn)
    Path(completed.release.destination).unlink()
    svc = RunService(RunStore(store.library_path, store.checkpoint_path))
    assert svc.reconcile_startup()[0].status == 'complete'
    availability = library.artifact_availability(run_id, library_path=store.library_path)
    assert availability == {'artifact_status': 'available', 'canonical_available': True, 'export_available': False}
    assert library.get_resume(run_id, library_path=store.library_path)['pdf_url']
    Path(record.pdf_path).unlink()
    availability = library.artifact_availability(run_id, library_path=store.library_path)
    assert availability == {'artifact_status': 'missing', 'canonical_available': False, 'export_available': False}
    assert svc.get(run_id).status == 'complete'


def reexport(setup, service=None, *, action_id='export-again', expected_hash=None, recover=False):
    _, original, run_id, record, _, output = setup
    return (service or original).reexport(run_id, action_id, expected_hash or record.pdf_hash,
        base_dir=output, company_name='Example', user_full_name='Ada', recover=recover)


def test_reexport_uses_canonical_hash_and_preserves_original_release_and_replays(setup):
    from resume_agent.run_store import Conflict
    store, _, run_id, record, _, output = setup
    original = release(setup)
    released_row = store.release(run_id)
    Path(original.release.destination).unlink()
    result = reexport(setup)
    assert result['status'] == 'complete'
    assert Path(result['destination']).read_bytes() == Path(record.pdf_path).read_bytes()
    assert store.release(run_id) == released_row
    assert reexport(setup, reopen(setup)) == result
    assert len(list(output.rglob('*.pdf'))) == 1
    with pytest.raises(Conflict, match='action_payload_conflict'):
        reexport(setup, expected_hash='e' * 64)
    with pytest.raises(Conflict, match='canonical_pdf_mismatch'):
        reexport(setup, action_id='wrong-hash', expected_hash='e' * 64)
    Path(record.pdf_path).write_bytes(b'changed bytes')
    with pytest.raises(Conflict, match='canonical_pdf_mismatch'):
        reexport(setup, action_id='changed-canonical')


@pytest.mark.parametrize('boundary', ['reexport_after_reservation', 'reexport_after_plan', 'reexport_after_copy', 'reexport_after_rename', 'reexport_after_commit'])
def test_reexport_crash_requires_explicit_recovery_and_reuses_one_destination(setup, boundary):
    from resume_agent.run_store import Conflict
    release(setup)
    def crash(stage):
        if stage == boundary:
            raise Crash(stage)
    with pytest.raises(Crash):
        reexport(setup, reopen(setup, crash))
    store, _, run_id, _, _, output = setup
    before = {str(path) for path in output.rglob('*.pdf')}
    service = reopen(setup)
    if boundary != 'reexport_after_commit':
        with pytest.raises(Conflict, match='explicit_recovery_required'):
            reexport(setup, service)
    result = reexport(setup, service, recover=True)
    assert result['status'] == 'complete'
    assert before == {str(path) for path in output.rglob('*.pdf')}
    assert len(before) == 2
    assert not list(output.rglob('.*.owner.json'))
    assert store.release(run_id)['status'] == 'released'
    assert reexport(setup, reopen(setup)) == result


def test_reexport_recovery_preserves_unexpected_destination(setup):
    from resume_agent.run_store import Conflict
    release(setup)
    def crash(stage):
        if stage == 'reexport_after_copy':
            raise Crash(stage)
    with pytest.raises(Crash):
        reexport(setup, reopen(setup, crash))
    store, _, run_id, _, _, _ = setup
    binding = read_v2_checkpoint(store.checkpoint_path, 'reexport', run_id + ':export-again')
    path = Path(binding['plan']['destination'])
    path.write_bytes(b'unrelated user file')
    with pytest.raises(Conflict, match='export_ownership_conflict'):
        reexport(setup, reopen(setup), recover=True)
    assert path.read_bytes() == b'unrelated user file'


def test_reexport_rename_sql_failure_remains_recoverable_without_second_copy(setup):
    import sqlite3
    release(setup)
    store, _, run_id, _, _, output = setup
    with store.connection() as conn:
        conn.execute("CREATE TRIGGER deny_reexport BEFORE UPDATE ON actions "
            "WHEN OLD.owner_kind='run_reexport' BEGIN SELECT RAISE(ABORT, 'required write failed'); END")
    with pytest.raises(sqlite3.IntegrityError, match='required write failed'):
        reexport(setup)
    paths = {str(path) for path in output.rglob('*.pdf')}
    with store.connection() as conn:
        action = store.action('run_reexport', run_id, 'export-again', conn)
        assert action['status'] == 'accepted' and action['result_json'] is None
        conn.execute('DROP TRIGGER deny_reexport')
    assert reexport(setup, reopen(setup), recover=True)['status'] == 'complete'
    assert paths == {str(path) for path in output.rglob('*.pdf')}
    assert len(paths) == 2


async def test_reexport_obeys_real_cross_process_run_lock(setup):
    import asyncio

    from resume_agent.run_store import Conflict
    from tests.test_run_service import hold_lock
    release(setup)
    store, _, run_id, _, _, _ = setup
    context = multiprocessing.get_context('spawn')
    ready, finish = context.Event(), context.Event()
    child = context.Process(target=hold_lock, args=(str(store.lock_path('run', run_id)), ready, finish))
    child.start()
    try:
        assert await asyncio.to_thread(ready.wait, 10)
        with pytest.raises(Conflict, match='owner_busy'):
            reexport(setup)
    finally:
        finish.set()
        child.join(10)
        assert child.exitcode == 0
    assert reexport(setup)['status'] == 'complete'

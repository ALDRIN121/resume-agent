"""Transactional release against real SQLite, canonical PDFs, and export files."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from resume_agent.approved_render import STANDARD, RenderRecord, render_identity
from resume_agent.artifacts import RunArtifacts, hash_file
from resume_agent.contracts import ReviewPdf, RunRequest
from resume_agent.run_service import RunService
from resume_agent.run_store import Conflict, RunStore
from tests.test_pdf_content_check import make_manifest, make_pdf


class Crash(BaseException):
    pass


@pytest.fixture
def setup(tmp_path):
    from resume_agent.release_service import ReleaseService
    store = RunStore(tmp_path / 'library.sqlite', tmp_path / 'state.sqlite')
    run = RunService(store).create(RunRequest(job_input='Engineer', input_type='text'),
        profile_snapshot={'personal': {'full_name': 'Ada', 'email': 'ada@example.test'}})
    artifacts = RunArtifacts.create(run.artifact_id, tmp_path / 'runs')
    attempt = artifacts.attempt(1)
    pdf = make_pdf(attempt.pdf_path, 'Cut 450ms to 90ms (+80%-gain).')
    record = RenderRecord(run.artifact_id, 1, make_manifest().content_hash, 'approved-v2', 'b' * 64,
        STANDARD, render_identity(make_manifest().content_hash, 'b' * 64, STANDARD),
        str(attempt.source_path), 'c' * 64, str(pdf), hash_file(pdf), str(attempt.log_path),
        'd' * 64, (), (), 1, False, ())
    service = ReleaseService(store)
    review = service.create_review(run.id, make_manifest(), record)
    action = ReviewPdf(action_id='approve-one', review_id=review.review_id,
        content_hash=review.content_hash, render_hash=review.render_hash,
        pdf_hash=review.pdf_hash, decision='approve')
    return store, service, run.id, record, action, tmp_path / 'output'


def release(setup, service=None, action=None):
    _, default, run_id, _, original, output = setup
    return (service or default).release(run_id, action or original, base_dir=output,
        company_name='Example', user_full_name='Ada')


def reopen(setup, hook=None):
    from resume_agent.release_service import ReleaseService
    store = setup[0]
    return ReleaseService(RunStore(store.library_path, store.checkpoint_path), crash_hook=hook)


def test_released_bytes_and_action_replay_are_authoritative(setup):
    store, service, run_id, record, action, output = setup
    assert service.get_preview(run_id) == Path(record.pdf_path).read_bytes()
    with pytest.raises(Conflict):
        service.get_final(run_id)
    result = release(setup)
    assert result.status == 'complete'
    assert store.release(run_id)['status'] == 'released'
    assert service.get_final(run_id) == Path(record.pdf_path).read_bytes()
    destination = Path(result.release.destination)
    assert hash_file(destination) == record.pdf_hash
    assert release(setup, reopen(setup)) == result
    assert [p for p in output.rglob('*.pdf')] == [destination]
    changed = action.model_copy(update={'decision': 'reject'})
    with pytest.raises(Conflict):
        release(setup, action=changed)


@pytest.mark.parametrize('field', ['review_id', 'content_hash', 'render_hash', 'pdf_hash'])
def test_every_stale_review_identity_conflicts_before_reservation(setup, field):
    action = setup[4].model_copy(update={field: 'z' if field == 'review_id' else 'e' * 64})
    with pytest.raises(Conflict):
        release(setup, action=action)
    assert setup[0].release(setup[2]) is None
    assert not setup[5].exists()


def test_canonical_tampering_blocks_preview_and_approval(setup):
    Path(setup[3].pdf_path).write_bytes(b'replaced')
    for work in [lambda: setup[1].get_preview(setup[2]), lambda: release(setup)]:
        with pytest.raises(Conflict):
            work()
    assert setup[0].release(setup[2]) is None


def test_reject_retains_draft_records_cancellation_and_replays(setup):
    action = setup[4].model_copy(update={'decision': 'reject'})
    result = release(setup, action=action)
    assert result.status == 'cancelled'
    assert setup[0].cancellation('run', setup[2])
    assert Path(setup[3].pdf_path).exists()
    assert setup[0].release(setup[2]) is None
    assert release(setup, reopen(setup), action) == result


@pytest.mark.parametrize('boundary', ['after_approval', 'before_copy', 'after_copy', 'after_rename', 'after_commit'])
def test_crash_reopens_and_explicit_continue_reuses_identical_plan(setup, boundary):
    def crash(stage):
        if stage == boundary:
            raise Crash(stage)
    with pytest.raises(Crash):
        release(setup, reopen(setup, crash))
    stored = setup[0].release(setup[2])
    destination = stored['destination']
    service = reopen(setup)
    inspection = service.inspect(setup[2])
    assert inspection.status == ('complete' if boundary == 'after_commit' else 'interrupted')
    if boundary != 'after_commit':
        assert setup[0].row('run', setup[2])['status'] != 'complete'
        assert Path(inspection.plan.ownership_path).exists()
    result = service.recover_unfinished(setup[2], continue_export=True)
    assert result.status == 'complete' and result.release.destination == destination
    assert release(setup, service) == result


@pytest.mark.parametrize('boundary', ['after_approval', 'after_copy', 'after_rename'])
def test_cancel_after_crash_removes_only_owned_uncommitted_export(setup, boundary):
    def crash(stage):
        if stage == boundary:
            raise Crash(stage)
    with pytest.raises(Crash):
        release(setup, reopen(setup, crash))
    plan = reopen(setup).inspect(setup[2]).plan
    setup[0].cancel('run', setup[2])
    result = reopen(setup).recover_unfinished(setup[2], cancel=True)
    assert result.status == 'cancelled'
    assert not plan.destination.exists() and not plan.temporary_path.exists()
    assert Path(setup[3].pdf_path).exists()


def test_after_copy_cancellation_wins_before_rename(setup):
    def cancel(stage):
        if stage == 'after_copy':
            setup[0].cancel('run', setup[2])
    result = release(setup, reopen(setup, cancel))
    assert result.status == 'cancelled'
    assert not Path(setup[0].release(setup[2])['destination']).exists()


def test_cancel_after_release_returns_complete_and_preserves_export(setup):
    result = release(setup)
    setup[0].cancel('run', setup[2])
    assert reopen(setup).recover_unfinished(setup[2], cancel=True) == result
    assert Path(result.release.destination).exists()
    assert not setup[0].cancellation('run', setup[2])


def test_unexpected_destination_is_preserved_during_recovery_and_cancel(setup):
    def crash(stage):
        if stage == 'after_rename':
            raise Crash(stage)
    with pytest.raises(Crash):
        release(setup, reopen(setup, crash))
    plan = reopen(setup).inspect(setup[2]).plan
    plan.destination.unlink()
    plan.destination.write_bytes(b'unexpected replacement')
    for cancel in [False, True]:
        with pytest.raises(Conflict):
            reopen(setup).recover_unfinished(setup[2], continue_export=not cancel, cancel=cancel)
        assert plan.destination.read_bytes() == b'unexpected replacement'
        assert plan.ownership_path.exists()


def test_failed_copy_leaves_approved_plan_for_explicit_recovery(setup):
    def fail(stage):
        if stage == 'before_copy':
            raise OSError('copy unavailable')
    with pytest.raises(OSError):
        release(setup, reopen(setup, fail))
    assert reopen(setup).inspect(setup[2]).status == 'interrupted'
    assert reopen(setup).recover_unfinished(setup[2], continue_export=True).status == 'complete'


def test_page_count_and_invalid_render_identity_block_review(setup):
    _, service, run_id, record, _, _ = setup
    for changed in [replace(record, page_count=2), replace(record, render_hash='f' * 64),
                    replace(record, overflow=True)]:
        with pytest.raises(Conflict):
            service.create_review(run_id, make_manifest(), changed)


def test_partial_owned_temporary_is_reprepared_on_explicit_continue(setup):
    def crash(stage):
        if stage == 'after_copy':
            plan = reopen(setup).inspect(setup[2]).plan
            with plan.temporary_path.open('r+b') as stream:
                stream.truncate(40)
            raise Crash(stage)
    with pytest.raises(Crash):
        release(setup, reopen(setup, crash))
    before = reopen(setup).inspect(setup[2]).plan
    assert before.temporary_path.stat().st_size == 40
    result = reopen(setup).recover_unfinished(setup[2], continue_export=True)
    assert result.release.destination == str(before.destination)
    assert hash_file(before.destination) == setup[3].pdf_hash


def test_unexpected_temp_is_never_removed_or_overwritten(setup):
    def crash(stage):
        if stage == 'after_copy':
            raise Crash(stage)
    with pytest.raises(Crash):
        release(setup, reopen(setup, crash))
    plan = reopen(setup).inspect(setup[2]).plan
    plan.temporary_path.unlink()
    plan.temporary_path.write_bytes(b'foreign bytes')
    for cancel in [False, True]:
        with pytest.raises(Conflict):
            reopen(setup).recover_unfinished(setup[2], continue_export=not cancel, cancel=cancel)
        assert plan.temporary_path.read_bytes() == b'foreign bytes'
        assert plan.destination.exists() and plan.ownership_path.exists()


def test_approval_database_error_rolls_back_action_and_cleans_reservation(setup):
    import sqlite3
    with setup[0].connection() as conn:
        conn.execute("CREATE TRIGGER fail_approval BEFORE INSERT ON release_records BEGIN SELECT RAISE(FAIL,'injected persistence failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='injected persistence failure'):
        release(setup)
    assert setup[0].release(setup[2]) is None
    with setup[0].connection() as conn:
        assert setup[0].action('run', setup[2], setup[4].action_id, conn) is None
        conn.execute('DROP TRIGGER fail_approval')
    assert not list(setup[5].rglob('*.pdf'))
    assert not list(setup[5].rglob('.*.owner.json'))
    assert release(setup).status == 'complete'


def test_checkpoint_persistence_error_surfaces_before_reservation(setup):
    import sqlite3
    with sqlite3.connect(setup[0].checkpoint_path) as conn:
        conn.execute("CREATE TRIGGER fail_checkpoint BEFORE INSERT ON checkpoints BEGIN SELECT RAISE(FAIL,'checkpoint failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='checkpoint failure'):
        release(setup)
    assert not setup[5].exists()
    assert setup[0].release(setup[2]) is None


def test_approval_persists_full_plan_and_action_before_copy(setup):
    def crash(stage):
        if stage == 'after_approval':
            stored = setup[0].release(setup[2])
            assert stored['status'] == 'approved'
            plan = reopen(setup).inspect(setup[2]).plan
            sidecar = json.loads(plan.ownership_path.read_text())
            assert sidecar['plan'] == plan.to_dict()
            assert not plan.temporary_path.exists()
            with setup[0].connection() as conn:
                action = setup[0].action('run', setup[2], setup[4].action_id, conn)
                assert action['status'] == 'accepted' and action['result_json'] is None
            raise Crash(stage)
    with pytest.raises(Crash):
        release(setup, reopen(setup, crash))


def test_reservation_before_approval_is_discoverable_and_explicitly_cleaned(setup):
    from resume_agent.artifacts import prepare_export
    from resume_agent.checkpoint import read_v2_checkpoint, write_v2_checkpoint
    store, _, run_id, record, _, output = setup
    binding = read_v2_checkpoint(store.checkpoint_path, 'release', run_id)
    binding['intent'] = {'base_dir': str(output.resolve())}
    write_v2_checkpoint(store.checkpoint_path, 'release', run_id, binding)
    plan = prepare_export(record.artifact_id, record.pdf_path, record.pdf_hash, output, 'Example', 'Ada')
    inspection = reopen(setup).inspect(run_id)
    assert inspection.status == 'interrupted' and inspection.orphan_plans == (plan,)
    assert plan.destination.exists()  # inspection cannot act as approval
    with pytest.raises(Conflict, match='review_action_required'):
        reopen(setup).recover_unfinished(run_id, continue_export=True)
    assert not plan.destination.exists()
    assert store.release(run_id) is None
    assert release(setup).status == 'complete'


def test_repeated_cancel_recovery_is_idempotent(setup):
    def crash(stage):
        if stage == 'after_rename':
            raise Crash(stage)
    with pytest.raises(Crash):
        release(setup, reopen(setup, crash))
    first = reopen(setup).recover_unfinished(setup[2], cancel=True)
    assert reopen(setup).inspect(setup[2]).status == 'cancelled'
    assert reopen(setup).recover_unfinished(setup[2], cancel=True) == first


def test_cleanup_failure_after_commit_keeps_authoritative_success(setup):
    def replace_sidecar(stage):
        if stage == 'after_commit':
            row = setup[0].release(setup[2])
            owner = Path(row['destination']).with_name(
                f".{Path(row['destination']).name}.{row['ownership_token']}.owner.json")
            owner.write_text('{}')
    result = release(setup, reopen(setup, replace_sidecar))
    assert result.status == 'complete'
    assert release(setup, reopen(setup)) == result
    assert reopen(setup).inspect(setup[2]).cleanup_pending
    assert reopen(setup).recover_unfinished(setup[2], continue_export=True) == result
    assert Path(result.release.destination).exists()


def test_missing_friendly_export_keeps_canonical_download_authority(setup):
    result = release(setup)
    Path(result.release.destination).unlink()
    assert reopen(setup).get_final(setup[2]) == Path(setup[3].pdf_path).read_bytes()
    assert reopen(setup).inspect(setup[2]).status == 'complete'


def test_new_render_replaces_review_and_old_action_conflicts(setup):
    _, service, run_id, record, old, _ = setup
    changed = replace(record, template_hash='c' * 64,
        render_hash=render_identity(record.content_hash, 'c' * 64, STANDARD))
    new = service.create_review(run_id, make_manifest(), changed)
    assert new.review_id != old.review_id
    with pytest.raises(Conflict):
        release(setup, action=old)


def test_cancel_cleanup_then_database_failure_can_be_recovered_without_sidecar(setup):
    import sqlite3
    def crash(stage):
        if stage == 'after_copy':
            raise Crash(stage)
    with pytest.raises(Crash):
        release(setup, reopen(setup, crash))
    plan = reopen(setup).inspect(setup[2]).plan
    with setup[0].connection() as conn:
        conn.execute("CREATE TRIGGER fail_cancel BEFORE UPDATE ON actions BEGIN SELECT RAISE(FAIL,'cancel commit failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='cancel commit failure'):
        reopen(setup).recover_unfinished(setup[2], cancel=True)
    assert not plan.ownership_path.exists()
    with setup[0].connection() as conn:
        conn.execute('DROP TRIGGER fail_cancel')
    assert reopen(setup).recover_unfinished(setup[2], cancel=True).status == 'cancelled'


def _cancel_in_process(library, checkpoint, started, done, results):
    try:
        store = RunStore(Path(library), Path(checkpoint))
        with store.connection() as conn:
            run_id = conn.execute('SELECT id FROM runs').fetchone()[0]
        started.set()
        store.cancel('run', run_id)
        results.put((store.row('run', run_id)['status'], store.cancellation('run', run_id)))
    finally:
        done.set()


@pytest.mark.parametrize('stage,expected', [('after_copy', 'cancelled'), ('after_rename', 'complete')])
def test_cross_process_cancel_serializes_with_release_transaction(setup, stage, expected):
    import multiprocessing
    context = multiprocessing.get_context('spawn')
    started, done, results = context.Event(), context.Event(), context.Queue()
    child = context.Process(target=_cancel_in_process,
        args=(str(setup[0].library_path), str(setup[0].checkpoint_path), started, done, results))
    def race(boundary):
        if boundary == stage:
            child.start()
            assert started.wait(10)
            if stage == 'after_copy':
                child.join(10)
                assert child.exitcode == 0
            else:
                assert not done.wait(0.15)  # BEGIN IMMEDIATE is still held by release.
        if boundary == 'after_commit' and stage == 'after_rename':
            child.join(10)
            assert child.exitcode == 0
    try:
        result = release(setup, reopen(setup, race))
        assert result.status == expected
        assert results.get(timeout=5) == ('running' if expected == 'cancelled' else 'complete', expected == 'cancelled')
        assert setup[0].row('run', setup[2])['status'] == expected
        assert setup[0].release(setup[2])['status'] == ('released' if expected == 'complete' else 'exporting')
        if expected == 'complete':
            assert Path(result.release.destination).exists()
        else:
            assert not Path(result.release.destination).exists()
    finally:
        if child.is_alive():
            child.terminate()
        if child.pid:
            child.join(10)
        results.close()


def test_review_pdf_stream_event_preserves_typed_review_identity(setup):
    from resume_agent.api.events import HITLPendingEvent, dump_event
    from resume_agent.api.streaming import StreamTranslator
    review = setup[1].inspect(setup[2]).review
    raw = {'event': 'on_chain_stream', 'data': {'chunk': {'__interrupt__': [
        {'kind': 'review_pdf', 'run_id': setup[2], 'review': review.model_dump(mode='json'),
         'preview_url': '/draft/example'}]}}}
    events = StreamTranslator().translate(raw)
    assert len(events) == 1 and isinstance(events[0], HITLPendingEvent)
    payload = dump_event(events[0])
    assert payload['kind'] == 'review_pdf' and payload['review'] == review.model_dump(mode='json')
    assert payload['run_id'] == setup[2] and payload['preview_url'] == '/draft/example'
    assert payload['questions'] == [] and payload['suggestions'] == []


def test_released_database_is_authority_when_checkpoint_is_unavailable(setup):
    def crash(stage):
        if stage == 'after_commit':
            raise Crash(stage)
    with pytest.raises(Crash):
        release(setup, reopen(setup, crash))
    setup[0].checkpoint_path.unlink()
    service = reopen(setup)
    assert service.inspect(setup[2]).status == 'complete'
    result = service.recover_unfinished(setup[2], continue_export=True)
    assert result.status == 'complete'
    assert release(setup, service) == result
    assert service.get_final(setup[2]) == Path(setup[3].pdf_path).read_bytes()


def test_final_rejects_symlink_replacement_even_with_same_bytes(setup, tmp_path):
    release(setup)
    canonical = Path(setup[3].pdf_path)
    replacement = tmp_path / 'replacement.pdf'
    replacement.write_bytes(canonical.read_bytes())
    canonical.unlink()
    canonical.symlink_to(replacement)
    with pytest.raises(Conflict):
        reopen(setup).get_final(setup[2])

"""Private v2 lifecycle: real database/checkpoints, injected external-work boundary."""
import asyncio
import multiprocessing

import pytest
from filelock import FileLock
from pydantic import ValidationError

from resume_agent.contracts import (
    AskMissing,
    AskMissingRequest,
    Continue,
    DriverResult,
    PdfReview,
    PdfReviewRequest,
    ReviewPdf,
    RunRequest,
    content_hash,
)
from resume_agent.run_service import DriverConfigurationError, RunService
from resume_agent.run_store import Conflict, RunStore


def request(**changes):
    return RunRequest(job_input="Complete job description", input_type="text", **changes)


def service(tmp_path, driver=None):
    return RunService(RunStore(tmp_path / "library.sqlite", tmp_path / "state.sqlite"), driver=driver)


def create(svc):
    return svc.create(request(), profile_snapshot={"personal": {"full_name": "Candidate", "email": "a@b.c"}})


def pending():
    return AskMissingRequest(request_id="q1", question_ids=["q"])


async def pause(context):
    context.control.checkpoint({"attempt": 1})
    return DriverResult(status="awaiting-input", pending=pending())


def hold_lock(path, ready, release):
    with FileLock(path, timeout=0):
        ready.set()
        release.wait(20)


def test_run_create_is_durable(tmp_path):
    first = service(tmp_path)
    view = create(first)
    reopened = service(tmp_path).get(view.id)
    assert reopened.status == "queued"
    assert reopened.artifact_id == view.artifact_id
    fixed = first.store.input("run", view.id)
    assert fixed["request"]["job_input"] == "Complete job description"
    assert fixed["profile_snapshot"]["skills"] == {}
    assert fixed["profile_revision"] == content_hash(fixed["profile_snapshot"])
    assert fixed["memory_snapshot"] == {}
    assert reopened.fixed_input_hashes["job"] == content_hash("Complete job description")


@pytest.mark.parametrize("pages", [0, 6, True, "2"])
def test_max_pages_strict(pages):
    with pytest.raises(ValidationError):
        request(max_pages=pages)


async def test_no_driver_preserves_queued(tmp_path):
    svc = service(tmp_path)
    view = create(svc)
    with pytest.raises(DriverConfigurationError):
        await svc.drive(view.id)
    assert svc.get(view.id).status == "queued"


async def test_run_lock_cross_process(tmp_path):
    svc = service(tmp_path, pause)
    view = create(svc)
    ctx = multiprocessing.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=hold_lock, args=(str(svc.store.lock_path("run", view.id)), ready, release))
    child.start()
    try:
        assert await asyncio.to_thread(ready.wait, 10)
        with pytest.raises(Conflict, match="owner_busy"):
            await svc.drive(view.id)
    finally:
        release.set()
        child.join(10)
        assert child.exitcode == 0
    assert (await svc.drive(view.id)).status == "awaiting-input"


async def test_action_id_replay(tmp_path):
    calls = []
    async def driver(context):
        calls.append(context.action)
        context.control.checkpoint({"applied_action_ids": ["answer"] if context.action else []})
        return DriverResult(status="awaiting-input", pending=pending())
    svc = service(tmp_path, driver)
    run = create(svc)
    await svc.drive(run.id)
    action = AskMissing(action_id="answer", request_id="q1", answers={"q": "answer"})
    result = await svc.drive(run.id, action)
    replayed = await service(tmp_path, driver).drive(run.id, action)
    assert replayed == result
    assert len(calls) == 2
    with pytest.raises(Conflict, match="action_payload_conflict"):
        await svc.drive(run.id, action.model_copy(update={"answers": {"q": "different"}}))


async def test_stale_and_stage_unsafe_actions(tmp_path):
    svc = service(tmp_path, pause)
    run = create(svc)
    await svc.drive(run.id)
    for action in [Continue(action_id="c"), AskMissing(action_id="a", request_id="old", answers={"q": "a"})]:
        with pytest.raises(Conflict):
            await svc.drive(run.id, action)
    with pytest.raises(Conflict):
        await svc.drive(run.id)
    assert svc.get(run.id).pending.request_id == "q1"


async def test_wrong_pdf_hash_rejected(tmp_path):
    hashes = {key: content_hash(key) for key in ("content_hash", "render_hash", "pdf_hash")}
    async def driver(context):
        context.control.checkpoint({})
        return DriverResult(status="awaiting-input", pending=PdfReviewRequest(
            review=PdfReview(review_id="review", template_version="1", layout_id="standard", **hashes)))
    svc = service(tmp_path, driver)
    run = create(svc)
    await svc.drive(run.id)
    with pytest.raises(Conflict):
        await svc.drive(run.id, ReviewPdf(action_id="a", review_id="review", decision="approve",
                                         **{**hashes, "pdf_hash": content_hash("wrong")}))


async def test_cancel_during_driver_and_after_restart(tmp_path):
    entered, finish = asyncio.Event(), asyncio.Event()
    async def driver(context):
        entered.set()
        await finish.wait()
        context.control.checkpoint({"safe": True})
        return DriverResult(status="awaiting-input", pending=pending())
    svc = service(tmp_path, driver)
    run = create(svc)
    task = asyncio.create_task(svc.drive(run.id))
    await entered.wait()
    cancelled = service(tmp_path).cancel(run.id)
    assert cancelled.cancellation_requested
    finish.set()
    assert (await task).status == "cancelled"
    assert service(tmp_path).get(run.id).status == "cancelled"


async def test_accepted_unfinished_needs_explicit_recovery(tmp_path):
    async def crashing(context):
        if context.action:
            context.control.checkpoint({"applied_action_ids": [context.action.action_id], "attempt": 1})
            raise asyncio.CancelledError()
        return await pause(context)
    svc = service(tmp_path, crashing)
    run = create(svc)
    await svc.drive(run.id)
    action = AskMissing(action_id="a", request_id="q1", answers={"q": "a"})
    with pytest.raises(asyncio.CancelledError):
        await svc.drive(run.id, action)
    recovered = []
    async def recovery(context):
        recovered.append(context)
        assert context.checkpoint["applied_action_ids"] == ["a"]
        assert context.action == action
        assert context.recovering
        context.control.checkpoint({**context.checkpoint, "attempt": 2})
        return DriverResult(status="awaiting-input", pending=pending())
    reopen = service(tmp_path, recovery)
    assert reopen.get(run.id).status == "interrupted"
    assert reopen.get(run.id).pending is None
    with pytest.raises(Conflict, match="action_recovery_required"):
        await reopen.drive(run.id, action)
    with pytest.raises(Conflict):
        await reopen.drive(run.id)
    result = await reopen.drive(run.id, Continue(action_id="recover"))
    assert len(recovered) == 1
    assert await reopen.drive(run.id, action) == result
    assert await reopen.drive(run.id, Continue(action_id="recover")) == result


async def test_driver_failure_is_sanitized_and_replay_stable(tmp_path):
    async def driver(context):
        if context.action:
            raise RuntimeError("secret-provider-token")
        return await pause(context)
    svc = service(tmp_path, driver)
    run = create(svc)
    await svc.drive(run.id)
    action = AskMissing(action_id="a", request_id="q1", answers={"q": "a"})
    result = await svc.drive(run.id, action)
    assert result.status == "failed"
    assert result.diagnostics[0].code == "driver_failed"
    assert "secret-provider-token" not in result.model_dump_json()
    assert await service(tmp_path, driver).drive(run.id, action) == result


async def test_generation_cannot_complete_without_release(tmp_path):
    async def driver(context):
        context.control.checkpoint({})
        return DriverResult(status="complete")
    svc = service(tmp_path, driver)
    result = await svc.drive(create(svc).id)
    assert result.status == "failed"
    assert result.diagnostics[0].code == "release_required"


async def test_driver_must_checkpoint_and_fixed_input_is_detached(tmp_path):
    async def driver(context):
        context.fixed_inputs["profile_snapshot"]["personal"]["full_name"] = "mutated"
        return DriverResult(status="awaiting-input", pending=pending())
    svc = service(tmp_path, driver)
    run = create(svc)
    result = await svc.drive(run.id)
    assert result.diagnostics[0].code == "checkpoint_required"
    assert svc.store.input("run", run.id)["profile_snapshot"]["personal"]["full_name"] == "Candidate"


async def test_subscribe_rebuilds_pending_after_reopen(tmp_path):
    svc = service(tmp_path, pause)
    run = create(svc)
    await svc.drive(run.id)
    events = service(tmp_path).subscribe(run.id)
    first = await anext(events)
    assert first.view.pending.request_id == "q1"
    await events.aclose()


async def test_accept_before_checkpoint_crash_recovers_without_old_pending(tmp_path):
    svc = service(tmp_path, pause)
    run = create(svc)
    await svc.drive(run.id)
    action = AskMissing(action_id="a", request_id="q1", answers={"q": "answer"})
    # Crash after the durable command transaction, before any new checkpoint.
    with svc.store.connection(immediate=True) as conn:
        svc.store.accept("run", run.id, action.model_dump(mode="json"), content_hash(action), conn)
        svc.store.update("run", run.id, status="running", pending=None, conn=conn)
    reopened = service(tmp_path, pause)
    assert reopened.get(run.id).status == "interrupted"
    assert reopened.get(run.id).pending is None
    assert (await reopened.drive(run.id, Continue(action_id="recover"))).status == "awaiting-input"


async def test_suggestion_hash_validated_for_selected_projection(tmp_path):
    from resume_agent.contracts import PresentSuggestions, SuggestionReviewRequest
    source = content_hash("profile")
    async def driver(context):
        context.control.checkpoint({"source": "fixed"})
        return DriverResult(status="awaiting-input", pending=SuggestionReviewRequest(
            review_id="r", source_revision=source, content_hash=content_hash([]), proposal_ids=["p"]))
    store = RunStore(tmp_path / "library.sqlite", tmp_path / "state.sqlite")
    svc = RunService(store, driver=driver)
    run = create(svc)
    await svc.drive(run.id)
    action = PresentSuggestions(action_id="a", review_id="r", source_revision=source,
                                approved_ids=["p"], content_hash=content_hash(["p"]))
    with pytest.raises(Conflict, match="content_validator_not_configured"):
        await svc.drive(run.id, action)
    def validate(checkpoint, incoming):
        assert checkpoint["source"] == "fixed"
        if incoming.content_hash != content_hash(incoming.approved_ids):
            raise ValueError("wrong content hash")
    svc = RunService(store, driver=driver, action_validator=validate)
    with pytest.raises(Conflict, match="action_validation_failed"):
        await svc.drive(run.id, action.model_copy(update={"content_hash": content_hash("wrong")}))
    assert (await svc.drive(run.id, action)).status == "awaiting-input"


async def test_completed_action_result_not_overwritten_on_get(tmp_path):
    svc = service(tmp_path, pause)
    run = create(svc)
    await svc.drive(run.id)
    action = AskMissing(action_id="a", request_id="q1", answers={"q": "x"})
    accepted = await svc.drive(run.id, action)
    svc.get(run.id)
    svc.cancel(run.id)
    assert await svc.drive(run.id, action) == accepted


async def test_checkpoint_namespace_preserves_v1_and_restores_pause_index(tmp_path):
    from langgraph.checkpoint.base import empty_checkpoint
    from langgraph.checkpoint.sqlite import SqliteSaver

    from resume_agent.checkpoint import read_v2_checkpoint
    svc = service(tmp_path, pause)
    run = create(svc)
    with SqliteSaver.from_conn_string(str(svc.store.checkpoint_path)) as saver:
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"schema_version": 1, "original": "preserved"}
        saver.put({"configurable": {"thread_id": run.id, "checkpoint_ns": ""}}, checkpoint, {}, {})
    await svc.drive(run.id)
    assert read_v2_checkpoint(svc.store.checkpoint_path, "run", run.id)["values"]["attempt"] == 1
    with svc.store.connection(immediate=True) as conn:
        svc.store.update("run", run.id, status="running", pending=None, conn=conn)
    assert service(tmp_path).get(run.id).pending.request_id == "q1"
    with SqliteSaver.from_conn_string(str(svc.store.checkpoint_path)) as saver:
        assert saver.get_tuple({"configurable": {"thread_id": run.id}}).checkpoint["channel_values"] == {
            "schema_version": 1, "original": "preserved"}


async def test_cancel_interrupted_accepted_action_has_stable_result(tmp_path):
    async def driver(context):
        if context.action:
            raise asyncio.CancelledError()
        return await pause(context)
    svc = service(tmp_path, driver)
    run = create(svc)
    await svc.drive(run.id)
    action = AskMissing(action_id="a", request_id="q1", answers={"q": "yes"})
    with pytest.raises(asyncio.CancelledError):
        await svc.drive(run.id, action)
    result = service(tmp_path).cancel(run.id)
    assert result.status == "cancelled"
    assert await service(tmp_path).drive(run.id, action) == result


async def test_explicit_domain_driver_failure_is_stable(tmp_path):
    from resume_agent.run_service import DriverFailureError
    async def driver(context):
        if context.action:
            raise DriverFailureError("profile_conflict", "profile_save")
        return await pause(context)
    svc = service(tmp_path, driver)
    run = create(svc)
    await svc.drive(run.id)
    result = await svc.drive(run.id, AskMissing(action_id="a", request_id="q1", answers={"q": "yes"}))
    assert result.diagnostics[0].code == "profile_conflict"
    assert result.diagnostics[0].stage == "profile_save"


async def test_pdf_rejection_cancels_and_replays_without_driver(tmp_path):
    hashes = {key: content_hash(key) for key in ("content_hash", "render_hash", "pdf_hash")}
    calls = []
    async def driver(context):
        calls.append(context)
        context.control.checkpoint({"draft": "retained"})
        return DriverResult(status="awaiting-input", pending=PdfReviewRequest(
            review=PdfReview(review_id="r", template_version="1", layout_id="standard", **hashes)))
    svc = service(tmp_path, driver)
    run = create(svc)
    await svc.drive(run.id)
    action = ReviewPdf(action_id="reject", review_id="r", decision="reject", **hashes)
    result = await svc.drive(run.id, action)
    assert result.status == "cancelled"
    assert len(calls) == 1
    assert await service(tmp_path).drive(run.id, action) == result


async def test_cancellation_retains_failure_diagnostics(tmp_path):
    async def driver(context):
        raise RuntimeError("private error")
    svc = service(tmp_path, driver)
    run = create(svc)
    failed = await svc.drive(run.id)
    cancelled = svc.cancel(run.id)
    assert cancelled.status == "cancelled"
    assert cancelled.diagnostics == failed.diagnostics


def test_known_application_version_is_recorded(tmp_path):
    from resume_agent import __version__
    svc = service(tmp_path)
    run = create(svc)
    assert svc.store.input("run", run.id)["app_version"] == __version__


async def test_checkpoint_write_errors_are_visible_and_recoverable(tmp_path, monkeypatch):
    import sqlite3

    import resume_agent.run_service as module
    svc = service(tmp_path, pause)
    run = create(svc)
    original = module.write_v2_checkpoint
    def broken(*args):
        raise sqlite3.OperationalError("disk unavailable")
    monkeypatch.setattr(module, "write_v2_checkpoint", broken)
    with pytest.raises(sqlite3.OperationalError):
        await svc.drive(run.id)
    monkeypatch.setattr(module, "write_v2_checkpoint", original)
    assert service(tmp_path).get(run.id).status == "interrupted"


async def test_recovered_pdf_rejection_cancels_before_driver_and_replays(tmp_path):
    from resume_agent.checkpoint import read_v2_checkpoint

    hashes = {key: content_hash(key) for key in ("content_hash", "render_hash", "pdf_hash")}
    review = PdfReview(review_id="review", template_version="1", layout_id="standard", **hashes)
    calls = []
    async def driver(context):
        calls.append(context.action)
        context.control.checkpoint({"draft_pdf": "retained.pdf", "review": review.model_dump(mode="json")})
        return DriverResult(status="awaiting-input", pending=PdfReviewRequest(review=review))
    svc = service(tmp_path, driver)
    run = create(svc)
    await svc.drive(run.id)
    before = read_v2_checkpoint(svc.store.checkpoint_path, "run", run.id)["values"]
    rejection = ReviewPdf(action_id="reject", review_id=review.review_id, decision="reject", **hashes)
    # The acceptance committed; the process then died before its first checkpoint/cancel command.
    with svc.store.connection(immediate=True) as conn:
        svc.store.accept("run", run.id, rejection.model_dump(mode="json"), content_hash(rejection), conn)
        svc.store.update("run", run.id, status="running", pending=None, conn=conn)
    reopened = service(tmp_path, driver)
    assert reopened.get(run.id).status == "interrupted"
    continuation = Continue(action_id="recover-rejection")
    result = await reopened.drive(run.id, continuation)
    assert result.status == "cancelled"
    assert result.cancellation_requested
    assert calls == [None]
    assert read_v2_checkpoint(svc.store.checkpoint_path, "run", run.id)["values"] == before
    assert await service(tmp_path).drive(run.id, rejection) == result
    assert await service(tmp_path).drive(run.id, continuation) == result


async def test_unchanged_reads_do_not_write_or_publish_subscription_feedback(tmp_path):
    svc = service(tmp_path, pause)
    run = create(svc)
    await svc.drive(run.id)
    stream = svc.subscribe(run.id)
    first = await anext(stream)
    assert first.view.status == 'awaiting-input'
    before = svc.store.row('run', run.id)['updated_at']
    with svc.store.connection() as conn:
        conn.execute("CREATE TRIGGER unchanged_read_must_not_write BEFORE UPDATE ON runs BEGIN SELECT RAISE(ABORT, 'read wrote run'); END")
    for _ in range(5):
        assert svc.get(run.id).pending == first.view.pending
    assert svc.store.row('run', run.id)['updated_at'] == before
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(stream), timeout=0.05)
    await stream.aclose()

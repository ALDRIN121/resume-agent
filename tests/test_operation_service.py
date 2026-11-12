import pytest

from resume_agent.contracts import AskMissing, AskMissingRequest, DriverResult, OperationRequest
from resume_agent.operation_service import OperationService
from resume_agent.run_store import RunStore


@pytest.mark.parametrize("kind", ["profile_import", "role_evaluation"])
async def test_operation_replay_and_completion_without_pdf(tmp_path, kind):
    calls = []
    async def driver(context):
        calls.append(context.action)
        context.control.checkpoint({"attempt": len(calls)})
        if context.action:
            return DriverResult(status="complete", result={"saved": True})
        return DriverResult(status="pending_review", pending=AskMissingRequest(request_id="r", question_ids=["q"]))
    store = RunStore(tmp_path / "library.sqlite", tmp_path / "state.sqlite")
    svc = OperationService(store, driver=driver)
    view = svc.create(OperationRequest(kind=kind, input={"source": "full source"}))
    assert OperationService(store).get(view.id).status == "pending_model"
    await svc.drive(view.id)
    action = AskMissing(action_id="a", request_id="r", answers={"q": "yes"})
    result = await svc.drive(view.id, action)
    assert result.status == "complete"
    assert await OperationService(store, driver=driver).drive(view.id, action) == result
    assert len(calls) == 2


async def test_cancellation_committed_before_completion_wins(tmp_path):
    store = RunStore(tmp_path / "library.sqlite", tmp_path / "state.sqlite")
    async def driver(context):
        context.control.checkpoint({})
        return DriverResult(status="complete")
    svc = OperationService(store, driver=driver)
    view = svc.create(OperationRequest(kind="role_evaluation", input={}))
    # Simulate cancellation after external work and checkpoint, just before the final transaction.
    original = svc._lifecycle._commit_index
    def commit(owner_id, index, action_ids):
        if index["status"] == "complete":
            store.cancel("operation", owner_id)
        return original(owner_id, index, action_ids)
    svc._lifecycle._commit_index = commit
    assert (await svc.drive(view.id)).status == "cancelled"

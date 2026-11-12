"""Durable attempt budgets use real lifecycle checkpoints, never repaired JSON."""
import asyncio
import json
import sqlite3
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from resume_agent.contracts import Continue, DriverResult, RunRequest
from resume_agent.run_service import DriverFailureError, RunService
from resume_agent.run_store import RunStore


class Answer(BaseModel):
    value: str
    skills: dict[str, list[str]] = {}


class OtherAnswer(BaseModel):
    value: str
    extra: bool = True


def service(tmp_path, driver):
    return RunService(RunStore(tmp_path / "library.sqlite", tmp_path / "state.sqlite"), driver=driver)


def create(svc, mode="app"):
    return svc.create(RunRequest(job_input="Full immutable job source", input_type="text", execution_mode=mode),
                      profile_snapshot={"personal": {"full_name": "Candidate", "email": "a@b.c"}},
                      provider="ollama", model="captured-model")


async def no_sleep(delay):
    pass


async def test_retry_saves_before_call_and_retains_exact_input(tmp_path):
    from resume_agent.model_tasks import ModelTaskRunner
    calls, sleeps, saved = [], [], []
    messages = [HumanMessage(content="Entire immutable source")]

    async def external(received):
        calls.append(deepcopy(received))
        saved.append(svc._lifecycle._latest(run.id)["values"]["model_tasks"])
        if len(calls) == 1:
            received[0].content = "mutated by provider adapter"
            raise TimeoutError("SECRET")
        return '{"value":"ok","skills":{"Unusual Category":["Python"]}}'

    async def sleep(delay):
        sleeps.append(delay)

    async def driver(context):
        result = await ModelTaskRunner(context, sleep=sleep).run("extract_jd", Answer, messages, external)
        assert result.skills == {"Unusual Category": ["Python"]}
        return DriverResult(status="interrupted")

    svc = service(tmp_path, driver)
    run = create(svc)
    assert (await svc.drive(run.id)).status == "interrupted"
    assert calls == [messages, messages]
    assert sleeps == [0.5]
    assert [next(iter(v.values()))["attempts"] for v in saved] == [1, 2]
    assert messages[0].content == "Entire immutable source"


@pytest.mark.parametrize("response,code,calls", [
    ('{"value":"ok",', "truncated_output", 1),
    (AIMessage(content='{"value":"ok"}', response_metadata={"finish_reason":"length"}), "truncated_output", 1),
    ('{"value":}', "invalid_output", 2),
    ('{"missing":true}', "invalid_output", 2),
    (RuntimeError("SECRET unknown server"), "provider_unknown", 1),
    (TimeoutError("SECRET"), "transport", 2),
])
async def test_terminal_errors_have_safe_durable_stage_and_bounded_calls(tmp_path, response, code, calls):
    from resume_agent.model_tasks import ModelTaskRunner
    count = 0
    async def external(messages):
        nonlocal count
        count += 1
        if isinstance(response, Exception):
            raise response
        return response
    async def driver(context):
        try:
            await ModelTaskRunner(context, sleep=no_sleep).run("extract_jd", Answer, ["full input"], external)
        except Exception as exc:
            assert "SECRET" not in str(exc)
            raise DriverFailureError(exc.code, exc.stage) from None
    svc = service(tmp_path, driver)
    run = create(svc)
    result = await svc.drive(run.id)
    assert result.status == "failed"
    assert result.diagnostics[0].code == code
    assert result.diagnostics[0].stage == "extract_jd"
    assert count == calls
    record = next(iter(svc._lifecycle._latest(run.id)["values"]["model_tasks"].values()))
    assert record["attempts"] == calls
    assert record["code"] == code
    assert record["model"] == "captured-model"
    assert "SECRET" not in json.dumps(record)


@pytest.mark.parametrize("crash_at", ["before_call", "after_call"])
async def test_attempt_budget_survives_reopen_and_crash(tmp_path, crash_at):
    from resume_agent.model_tasks import ModelTaskRunner
    count = 0
    async def external(messages):
        nonlocal count
        count += 1
        raise asyncio.CancelledError()
    async def driver(context):
        if crash_at == "before_call":
            original = context.control.checkpoint
            def checkpoint(values):
                original(values)
                raise asyncio.CancelledError()
            context.control.checkpoint = checkpoint
        await ModelTaskRunner(context, sleep=no_sleep).run("extract_jd", Answer, ["full input"], external)
    svc = service(tmp_path, driver)
    run = create(svc)
    for i in range(2):
        with pytest.raises(asyncio.CancelledError):
            await svc.drive(run.id, Continue(action_id=f"continue{i}") if i else None)
        svc = service(tmp_path, driver)
    async def final_driver(context):
        try:
            await ModelTaskRunner(context).run("extract_jd", Answer, ["full input"], external)
        except Exception as exc:
            raise DriverFailureError(exc.code, exc.stage) from None
    svc = service(tmp_path, final_driver)
    result = await svc.drive(run.id, Continue(action_id="final"))
    assert result.diagnostics[0].code == "task_budget_exhausted"
    assert count == (0 if crash_at == "before_call" else 2)


async def test_completed_result_reused_only_for_same_input_and_schema(tmp_path):
    from resume_agent.model_tasks import ModelTaskRunner
    count = 0
    async def external(messages):
        nonlocal count
        count += 1
        return '{"value":"ok"}'
    async def driver(context):
        runner = ModelTaskRunner(context)
        first = await runner.run("extract_jd", Answer, ["full input"], external)
        first.value = "caller mutation"
        again = await runner.run("extract_jd", Answer, ["full input"], external)
        assert again.value == "ok"
        return DriverResult(status="interrupted")
    svc = service(tmp_path, driver)
    run = create(svc)
    await svc.drive(run.id)
    svc = service(tmp_path, driver)
    await svc.drive(run.id, Continue(action_id="continue"))
    assert count == 1
    async def changed(context):
        runner = ModelTaskRunner(context)
        await runner.run("extract_jd", Answer, ["changed input"], external)
        await runner.run("extract_jd", OtherAnswer, ["full input"], external)
        return DriverResult(status="interrupted")
    svc = service(tmp_path, changed)
    await svc.drive(run.id, Continue(action_id="changed"))
    assert count == 3


@pytest.mark.parametrize("during", ["call", "backoff"])
async def test_cancellation_discards_response_and_stops_retries(tmp_path, during):
    from resume_agent.model_tasks import ModelTaskRunner
    calls = 0
    async def external(messages):
        nonlocal calls
        calls += 1
        if during == "call":
            svc.cancel(run.id)
            return '{"value":"discard"}'
        raise TimeoutError("SECRET")
    async def sleep(delay):
        svc.cancel(run.id)
    async def driver(context):
        await ModelTaskRunner(context, sleep=sleep).run("extract_jd", Answer, ["full input"], external)
        raise AssertionError("cancelled response accepted")
    svc = service(tmp_path, driver)
    run = create(svc)
    assert (await svc.drive(run.id)).status == "cancelled"
    assert calls == 1
    record = next(iter(svc._lifecycle._latest(run.id)["values"]["model_tasks"].values()))
    assert "result" not in record


@pytest.mark.parametrize("mode,credentials,code", [("host", True, "unsupported_mode"), ("app", False, "authentication")])
async def test_readiness_stops_before_external_call_with_attempt_zero(tmp_path, mode, credentials, code):
    from resume_agent.model_tasks import ModelTaskRunner
    async def external(messages):
        raise AssertionError("readiness must stop invocation")
    async def driver(context):
        try:
            await ModelTaskRunner(context).run("extract_jd", Answer, ["full input"], external,
                                                credentials_available=credentials)
        except Exception as exc:
            raise DriverFailureError(exc.code, exc.stage) from None
    svc = service(tmp_path, driver)
    run = create(svc, mode)
    result = await svc.drive(run.id)
    assert result.diagnostics[0].code == code
    record = next(iter(svc._lifecycle._latest(run.id)["values"]["model_tasks"].values()))
    assert record["attempts"] == 0


async def test_checkpoint_failure_is_not_caught_as_provider_failure(tmp_path):
    from resume_agent.model_tasks import ModelTaskRunner
    async def driver(context):
        def fail(values):
            raise sqlite3.OperationalError("checkpoint failed")
        context.control.checkpoint = fail
        await ModelTaskRunner(context).run("extract_jd", Answer, ["full input"], lambda messages: None)
    svc = service(tmp_path, driver)
    run = create(svc)
    with pytest.raises(sqlite3.OperationalError, match="checkpoint failed"):
        await svc.drive(run.id)


@pytest.mark.parametrize("status,header,want_calls,want_delay,code", [
    (401, None, 1, None, "authentication"),
    (403, None, 1, None, "authentication"),
    (404, None, 1, None, "model_unavailable"),
    (429, "60", 2, 60, "rate_limited"),
    (429, "61", 1, None, "rate_limited"),
    (429, None, 1, None, "rate_limited"),
    (429, "Thu, 12 Nov 2026 12:00:30 GMT", 2, 30, "rate_limited"),
    (500, None, 2, 0.5, "provider_server"),
])
async def test_typed_retry_policy_counts_actual_external_calls(tmp_path, status, header, want_calls, want_delay, code):
    import httpx

    from resume_agent.model_tasks import ModelTaskRunner
    calls, sleeps = [], []
    async def external(messages):
        calls.append(messages)
        response = httpx.Response(status, headers={"Retry-After": header} if header else {},
                                  request=httpx.Request("POST", "https://provider.example"))
        raise httpx.HTTPStatusError("SECRET", request=response.request, response=response)
    async def sleep(delay):
        sleeps.append(delay)
    async def driver(context):
        try:
            await ModelTaskRunner(context, sleep=sleep, clock=lambda: 1794484800).run(
                "extract_jd", Answer, ["entire input"], external)
        except Exception as exc:
            raise DriverFailureError(exc.code, exc.stage) from None
    svc = service(tmp_path, driver)
    run = create(svc)
    result = await svc.drive(run.id)
    assert result.diagnostics[0].code == code
    assert len(calls) == want_calls
    assert sleeps == ([] if want_delay is None else [want_delay])


async def test_complete_invalid_output_retries_same_input_then_succeeds(tmp_path):
    from resume_agent.model_tasks import ModelTaskRunner
    calls = []
    async def external(messages):
        calls.append(messages)
        return '{"value":}' if len(calls) == 1 else '```json\n{"value":"ok"}\n```'
    async def driver(context):
        result = await ModelTaskRunner(context, sleep=no_sleep).run("extract_jd", Answer, ["full input"], external)
        assert result.value == "ok"
        return DriverResult(status="interrupted")
    svc = service(tmp_path, driver)
    run = create(svc)
    assert (await svc.drive(run.id)).status == "interrupted"
    assert calls == [["full input"], ["full input"]]


async def test_successful_response_crash_before_result_checkpoint_consumes_attempt(tmp_path):
    from resume_agent.model_tasks import ModelTaskRunner
    calls = 0
    crash = True
    async def external(messages):
        nonlocal calls
        calls += 1
        return '{"value":"ok"}'
    async def driver(context):
        original = context.control.checkpoint
        def checkpoint(values):
            if crash and any(item.get("status") == "complete" for item in values["model_tasks"].values()):
                raise asyncio.CancelledError()
            original(values)
        context.control.checkpoint = checkpoint
        result = await ModelTaskRunner(context).run("extract_jd", Answer, ["full input"], external)
        assert result.value == "ok"
        return DriverResult(status="interrupted")
    svc = service(tmp_path, driver)
    run = create(svc)
    with pytest.raises(asyncio.CancelledError):
        await svc.drive(run.id)
    assert next(iter(svc._lifecycle._latest(run.id)["values"]["model_tasks"].values()))["attempts"] == 1
    crash = False
    svc = service(tmp_path, driver)
    assert (await svc.drive(run.id, Continue(action_id="recover"))).status == "interrupted"
    assert calls == 2


async def test_default_adapter_honors_captured_provider_model_and_current_credentials(tmp_path, monkeypatch):
    from resume_agent import llm
    from resume_agent.config import ResumeAgentSettings
    from resume_agent.model_tasks import ModelTaskRunner
    seen = []
    class Adapter:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, messages):
            return Answer(value="ok")
    def factory(settings, task):
        seen.append((settings.provider, settings.model.default, settings.ollama_api_key))
        return Adapter()
    monkeypatch.setattr(llm, "get_chat_model", factory)
    settings = ResumeAgentSettings(_env_file=None, provider="openai", OPENAI_API_KEY="changed-key",
                                   OLLAMA_API_KEY="current-secret", model={"default": "changed-model"})
    async def driver(context):
        result = await ModelTaskRunner(context).run("extract_jd", Answer, ["full input"], settings=settings)
        assert result.value == "ok"
        return DriverResult(status="interrupted")
    svc = service(tmp_path, driver)
    run = create(svc)
    assert (await svc.drive(run.id)).status == "interrupted"
    assert seen == [("ollama", "captured-model", "current-secret")]
    assert settings.provider == "openai" and settings.model.default == "changed-model"
    assert "current-secret" not in json.dumps(svc._lifecycle._latest(run.id))


async def test_multiple_runner_instances_reuse_latest_context_checkpoint(tmp_path):
    from resume_agent.model_tasks import ModelTaskRunner
    calls = 0
    async def external(messages):
        nonlocal calls
        calls += 1
        return '{"value":"ok"}'
    async def driver(context):
        first, second = ModelTaskRunner(context), ModelTaskRunner(context)
        await first.run("extract_jd", Answer, ["full input"], external)
        await second.run("extract_jd", Answer, ["full input"], external)
        return DriverResult(status="interrupted")
    svc = service(tmp_path, driver)
    run = create(svc)
    await svc.drive(run.id)
    assert calls == 1


async def test_interrupted_backoff_respects_remaining_retry_after_on_restart(tmp_path):
    import httpx

    from resume_agent.model_tasks import ModelTaskRunner
    calls, sleeps = [], []
    now = 1000
    crash = True
    async def external(messages):
        calls.append(messages)
        if len(calls) == 1:
            response = httpx.Response(429, headers={"Retry-After": "2"},
                                      request=httpx.Request("POST", "https://provider.example"))
            raise httpx.HTTPStatusError("SECRET", request=response.request, response=response)
        return '{"value":"ok"}'
    async def sleep(delay):
        nonlocal now
        sleeps.append(delay)
        if crash:
            now += 1
            raise asyncio.CancelledError()
        now += delay
    async def driver(context):
        await ModelTaskRunner(context, sleep=sleep, clock=lambda: now).run("extract_jd", Answer, ["input"], external)
        return DriverResult(status="interrupted")
    svc = service(tmp_path, driver)
    run = create(svc)
    with pytest.raises(asyncio.CancelledError):
        await svc.drive(run.id)
    crash = False
    svc = service(tmp_path, driver)
    assert (await svc.drive(run.id, Continue(action_id="recover"))).status == "interrupted"
    assert len(calls) == 2
    assert sleeps == [2, 1]


async def test_real_litellm_http_stack_has_no_nested_retries(tmp_path, monkeypatch):
    import httpx
    import litellm
    import respx

    # Keep the real SDK stack, with its HTTP traffic intercepted by respx.
    monkeypatch.setattr(litellm, "disable_aiohttp_transport", True)

    from resume_agent.config import ResumeAgentSettings
    from resume_agent.model_tasks import ModelTaskRunner
    settings = ResumeAgentSettings(_env_file=None, provider="openai", OPENAI_API_KEY="test-key")
    async def driver(context):
        try:
            await ModelTaskRunner(context, sleep=no_sleep).run("extract_jd", Answer, [HumanMessage(content="input")],
                                                              settings=settings)
        except Exception as exc:
            raise DriverFailureError(exc.code, exc.stage) from None
    svc = service(tmp_path, driver)
    run = svc.create(RunRequest(job_input="full job", input_type="text"),
                     profile_snapshot={"personal": {"full_name": "Candidate", "email": "a@b.c"}},
                     provider="openai", model="gpt-4o-mini")
    with respx.mock:
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(503, json={"error": {"message": "SECRET", "type": "server_error"}}))
        result = await svc.drive(run.id)
        assert route.call_count == 2
    assert result.diagnostics[0].code == "provider_server"
    assert "SECRET" not in json.dumps(svc._lifecycle._latest(run.id))


async def test_missing_current_provider_credentials_never_reaches_external_call(tmp_path, monkeypatch):
    from resume_agent.config import ResumeAgentSettings
    from resume_agent.model_tasks import ModelTaskRunner
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = ResumeAgentSettings(_env_file=None, provider="openai", OPENAI_API_KEY="")
    async def external(messages):
        raise AssertionError("missing credentials must prevent invocation")
    async def driver(context):
        try:
            await ModelTaskRunner(context).run("extract_jd", Answer, ["input"], external, settings=settings)
        except Exception as exc:
            raise DriverFailureError(exc.code, exc.stage) from None
    svc = service(tmp_path, driver)
    run = svc.create(RunRequest(job_input="full job", input_type="text"),
                     profile_snapshot={"personal": {"full_name": "Candidate", "email": "a@b.c"}},
                     provider="openai", model="gpt-5.4-mini")
    result = await svc.drive(run.id)
    assert result.diagnostics[0].code == "authentication"
    assert next(iter(svc._lifecycle._latest(run.id)["values"]["model_tasks"].values()))["attempts"] == 0


async def test_concurrent_task_calls_share_one_durable_attempt_budget(tmp_path):
    from resume_agent.model_tasks import ModelTaskRunner
    from resume_agent.provider_errors import ModelTaskError
    calls = 0
    async def external(messages):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        raise TimeoutError("SECRET")
    async def driver(context):
        first, second = ModelTaskRunner(context, sleep=no_sleep), ModelTaskRunner(context, sleep=no_sleep)
        results = await asyncio.gather(first.run("extract_jd", Answer, ["input"], external),
                                       second.run("extract_jd", Answer, ["input"], external),
                                       return_exceptions=True)
        assert all(isinstance(result, ModelTaskError) for result in results)
        return DriverResult(status="interrupted")
    svc = service(tmp_path, driver)
    run = create(svc)
    await svc.drive(run.id)
    assert calls == 2

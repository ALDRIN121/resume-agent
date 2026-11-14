"""Single durable retry owner for structured model tasks.

A checkpoint consumes an attempt BEFORE the external call. A crash can consume
an attempt without a call, or leave an external call's result unknown. This is
an at-most-two-call budget, not a claim of exactly-once provider execution.
"""
from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from pydantic import BaseModel, ValidationError

from .contracts import ModelRequest, ModelResponse, content_hash
from .external_model import ExternalModelPauseError, register_request
from .provider_errors import ModelTaskError, ProviderFailure, classify_provider_error

if TYPE_CHECKING:
    from .config import ResumeAgentSettings
    from .run_service import DriverContext

ExternalCall = Callable[[object], Awaitable[object]]
# One live invocation per durable driver context, even across runner instances.
_CONTEXT_LOCKS: WeakKeyDictionary[object, asyncio.Lock] = WeakKeyDictionary()


def _json_input(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_json_input(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_input(item) for key, item in value.items()}
    return value


class ModelTaskRunner:
    def __init__(self, context: DriverContext, *, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.time):
        self.context, self.sleep, self.clock = context, sleep, clock
        self._lock = _CONTEXT_LOCKS.setdefault(context.control, asyncio.Lock())
        fixed = context.fixed_inputs
        self.provider, self.model = fixed.get("provider"), fixed.get("model")
        self.mode = fixed.get("request", {}).get("execution_mode", "app")

    def _save(self, key: str, record: dict) -> None:
        tasks = {**deepcopy(self.context.checkpoint.get("model_tasks", {})), key: deepcopy(record)}
        # Persistence/cancellation failures deliberately stay outside provider handling.
        self.context.control.checkpoint({"model_tasks": tasks})
        self.context.checkpoint["model_tasks"] = deepcopy(tasks)

    def _stop(self, key: str, record: dict, failure: ProviderFailure):
        record.update(code=failure.code, status="failed")
        self._save(key, record)
        raise ModelTaskError(failure.code, record["stage"], self.model, record["attempts"]) from None

    async def run[T: BaseModel](self, stage: str, schema: type[T], messages: object, invoke: ExternalCall | None = None,
                  *, settings: ResumeAgentSettings | None = None,
                  credentials_available: bool | None = None) -> T:
        """Serialize structured tasks and enforce their shared durable call budget."""
        async with self._lock:
            return await self._run(stage, schema, messages, invoke, settings=settings,
                                   credentials_available=credentials_available)

    async def _run[T: BaseModel](self, stage: str, schema: type[T], messages: object, invoke: ExternalCall | None = None,
                  *, settings: ResumeAgentSettings | None = None,
                  credentials_available: bool | None = None) -> T:
        """Run/reuse a task bound to fixed provider/model, stage, schema and full input.

        Production callers can omit invoke and supply current settings: only
        current credentials/endpoints are read; the run's captured provider/model
        win over current selection. Injected adapters must use those captured
        selections, disable internal retries and attest credentials if necessary.
        """
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", stage):
            raise ValueError("invalid task stage")
        self.context.control.check_cancelled()
        fixed_messages = deepcopy(messages)
        identity = {"stage": stage, "schema": schema.model_json_schema(),
                    "input": _json_input(fixed_messages), "provider": self.provider,
                    "model": self.model, "mode": self.mode}
        key = content_hash(identity)
        record = deepcopy(self.context.checkpoint.get("model_tasks", {}).get(key, {"stage": stage, "model": self.model,
                          "attempts": 0, "status": "ready"}))
        if self.mode == 'host':
            return self._host_run(key, record, schema, identity)
        if self.mode != "app":
            self._stop(key, record, ProviderFailure("unsupported_mode"))
        from .llm import get_chat_model, parse_structured_response
        if record["status"] == "complete":
            # The stored value was validated under this schema/input hash already.
            result = schema.model_validate(deepcopy(record["result"]))
            self._save(key, record)
            return result
        if record["status"] == "failed":
            raise ModelTaskError(record["code"], stage, self.model, record["attempts"]) from None
        if record["attempts"] >= 2:
            self._stop(key, record, ProviderFailure("task_budget_exhausted"))
        if credentials_available is False:
            self._stop(key, record, ProviderFailure("authentication"))
        if invoke is None or credentials_available is None:
            from .config import ResumeAgentSettings
            current = settings or ResumeAgentSettings.load()
            if not self.provider or not self.model:
                self._stop(key, record, ProviderFailure("model_unavailable"))
            captured = current.model_copy(deep=True, update={"provider": self.provider})
            captured.model.default = self.model
            try:
                adapter = get_chat_model(captured, task="structured")
            except Exception as exc:
                self._stop(key, record, classify_provider_error(exc, now=self.clock()))
            if invoke is None:
                invoke = adapter.with_structured_output(schema).ainvoke
        if "retry_at" in record:
            self.context.control.check_cancelled()
            remaining = min(60, max(0, record["retry_at"] - self.clock()))
            await self.sleep(remaining)
            self.context.control.check_cancelled()
            record.pop("retry_at")
        while record["attempts"] < 2:
            self.context.control.check_cancelled()
            record.update(attempts=record["attempts"] + 1, status="running")
            self._save(key, record)
            self.context.control.check_cancelled()
            try:
                raw = await invoke(deepcopy(fixed_messages))
            except Exception as exc:
                failure = classify_provider_error(exc, now=self.clock())
            else:
                self.context.control.check_cancelled()
                try:
                    result = parse_structured_response(raw, schema)
                except Exception as exc:
                    failure = classify_provider_error(exc, now=self.clock())
                else:
                    self.context.control.check_cancelled()
                    record.update(status="complete", result=result.model_dump(mode="json"))
                    record.pop("code", None)
                    self._save(key, record)
                    return result
            self.context.control.check_cancelled()
            record.update(code=failure.code)
            if failure.retry_after is None or record["attempts"] >= 2:
                self._stop(key, record, failure)
            record["retry_at"] = self.clock() + failure.retry_after
            self._save(key, record)
            self.context.control.check_cancelled()
            await self.sleep(failure.retry_after)
            self.context.control.check_cancelled()
            record.pop("retry_at")
        raise AssertionError("unreachable model attempt budget")

    def _host_run(self, key, record, schema, identity):
        """Checkpoint accepted responses before validation; never construct a provider."""
        self.context.control.check_cancelled()
        if record['status'] == 'complete':
            result = schema.model_validate(deepcopy(record['result']))
            self._save(key, record)
            return result
        if record['status'] == 'failed':
            raise ModelTaskError(record['code'], record['stage'], self.model, record['attempts'])
        request_id = register_request(self.context, key, record.get('request_id'))
        record.update(request_id=request_id, input_hash=key, status='pending')
        action = self.context.action
        if isinstance(action, ModelResponse) and action.request_id == request_id:
            if action.input_hash != key:
                from .run_store import Conflict
                raise Conflict('stale_model_input')
            saved_response = record.get('response')
            if not saved_response or saved_response['action_id'] != action.action_id:
                if record['attempts'] >= 2:
                    self._stop(key, record, ProviderFailure('task_budget_exhausted'))
                record.update(attempts=record['attempts'] + 1, response={
                    'action_id': action.action_id, 'result': deepcopy(action.result), 'status': 'validating'})
                self._save(key, record)
            saved_response = record['response']
            if saved_response['status'] == 'validating':
                self.context.control.check_cancelled()
                try:
                    result = schema.model_validate(deepcopy(saved_response['result']))
                except (ValueError, ValidationError, TypeError):
                    saved_response['status'] = 'invalid'
                    record['validation_error'] = 'invalid_structured_response'
                    if record['attempts'] >= 2:
                        self._stop(key, record, ProviderFailure('invalid_output'))
                    self._save(key, record)
                else:
                    record.update(status='complete', result=result.model_dump(mode='json'))
                    saved_response['status'] = 'complete'
                    record.pop('validation_error', None)
                    self._save(key, record)
                    return result
        self._save(key, record)
        raise ExternalModelPauseError(ModelRequest(request_id=request_id, input_hash=key, payload={
            'task': record['stage'], 'schema_name': schema.__name__, 'schema_version': 1,
            'input_payload': deepcopy(identity['input']), 'output_schema': deepcopy(identity['schema']),
            'attempts_used': record['attempts'], 'attempts_remaining': 2 - record['attempts'],
            'validation_error': record.get('validation_error')}))


def invoke_bounded[T: BaseModel](invoke: Callable[[object], object], messages: object, schema: type[T],
                   *, sleep: Callable[[float], None] = time.sleep,
                   clock: Callable[[], float] = time.time) -> T:
    """Legacy synchronous boundary; v2 callers must use ModelTaskRunner instead."""
    from .llm import parse_structured_response
    fixed = deepcopy(messages)
    for attempt in range(1, 3):
        try:
            return parse_structured_response(invoke(deepcopy(fixed)), schema)
        except Exception as exc:
            failure = classify_provider_error(exc, now=clock())
            if failure.retry_after is None or attempt == 2:
                raise ModelTaskError(failure.code, "extract_jd", None, attempt) from None
            sleep(failure.retry_after)
    raise AssertionError("unreachable model attempt budget")

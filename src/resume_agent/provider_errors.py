"""Sanitized provider categories and deliberately narrow retry decisions."""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime

import httpx
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

_GUIDANCE = {
    "authentication": 'The model provider rejected the API key. Reconnect in Settings ("API key") or re-enter your key.',
    "model_unavailable": "The model is not available from this provider. Choose an available model in Settings.",
    "rate_limited": "Rate limited by the model provider. Wait and retry, or check your provider usage limits.",
    "transport": "The model provider could not be reached or took too long to respond. Please retry.",
    "provider_server": "The model provider is temporarily unavailable. Please retry later.",
    "invalid_output": "The model returned invalid structured output. Retry or choose another model.",
    "context_limit": "The input exceeds this model's context limit. Choose a model with a larger context window.",
    "truncated_output": "The model response was truncated. Increase the output budget or choose another model.",
    "task_budget_exhausted": "This task has used its two model attempts. Start a new run to try again.",
    "unsupported_mode": "Host mode is not supported in this release. Choose app mode to continue.",
    "provider_unknown": "The model request failed (provider_unknown). Check the provider settings and retry.",
}


@dataclass(frozen=True)
class ProviderFailure:
    code: str
    retry_after: float | None = None

    @property
    def guidance(self) -> str:
        return _GUIDANCE[self.code]


class StructuredOutputError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(_GUIDANCE[code])


class ModelTaskError(RuntimeError):
    """Only these safe fields may cross the workflow/UI diagnostic boundary."""

    def __init__(self, code: str, stage: str, model: str | None, attempts: int):
        self.code, self.stage, self.model, self.attempts = code, stage, model, attempts
        self.guidance = _GUIDANCE[code]
        super().__init__(self.guidance)


def _retry_after(value: object, now: float) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                return None
            delay = date.astimezone(UTC).timestamp() - now
        except (ValueError, TypeError, OverflowError):
            return None
    return delay if math.isfinite(delay) and 0 <= delay <= 60 else None


def classify_provider_error(exc: Exception, *, now: float | None = None) -> ProviderFailure:
    """Use status/code/types/causes, never free-form server text to infer a retry."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (StructuredOutputError, ModelTaskError)):
            code = current.code
            return ProviderFailure(code, 0 if code == "invalid_output" else None)
        response = getattr(current, "response", None)
        status = getattr(current, "status_code", None) or getattr(response, "status_code", None)
        code = getattr(current, "code", None)
        body = getattr(current, "body", None)
        if isinstance(body, dict):
            error = body.get("error", body)
            if isinstance(error, dict):
                code = error.get("code") or error.get("type") or code
        module = type(current).__module__.split(".", 1)[0]
        name = type(current).__name__ if module in {"litellm", "openai", "anthropic", "google"} else ""
        if code in ("context_length_exceeded", "context_window_exceeded") or name == "ContextWindowExceededError":
            return ProviderFailure("context_limit")
        if code in ("model_not_found", "unsupported_model") or name == "NotFoundError" or status == 404:
            return ProviderFailure("model_unavailable")
        if status in (401, 403) or name in ("AuthenticationError", "PermissionDeniedError"):
            return ProviderFailure("authentication")
        if status == 429 or name == "RateLimitError":
            headers = getattr(response, "headers", None) or getattr(current, "headers", {}) or {}
            value = headers.get("retry-after") or headers.get("Retry-After")
            return ProviderFailure("rate_limited", _retry_after(value, time.time() if now is None else now))
        if isinstance(status, int) and 500 <= status <= 599:
            return ProviderFailure("provider_server", 0.5)
        if isinstance(current, (TimeoutError, ConnectionError, httpx.TransportError)) or name in (
            "APIConnectionError", "APITimeoutError", "Timeout",
        ):
            return ProviderFailure("transport", 0.5)
        if isinstance(current, (OutputParserException, ValidationError)):
            return ProviderFailure("invalid_output", 0)
        current = current.__cause__
    return ProviderFailure("provider_unknown")


def safe_error_guidance(exc: Exception) -> str:
    """Constrained legacy text hints affect guidance only, never retry eligibility."""
    result = classify_provider_error(exc)
    if result.code != "provider_unknown":
        return result.guidance
    text = str(exc).lower()
    if re.search(r"\b(insufficient_quota|insufficient credits|payment required)\b", text) or "error code: 402" in text:
        return "Out of LLM credits. Check billing with your selected provider in Settings, or switch provider and retry."
    if re.search(r"\b(401|403|authentication_error|unauthorized|invalid api key)\b", text):
        return _GUIDANCE["authentication"]
    if re.search(r"\b(429|rate limit|rate-limit|too many requests)\b", text):
        return _GUIDANCE["rate_limited"]
    if "upgrade_required" in text:
        return "Your Command Code plan does not include API access. Check your plan in Command Code Studio."
    if "unsupported_model" in text:
        return _GUIDANCE["model_unavailable"]
    if re.search(r"\b(timeout|timed out)\b", text):
        return _GUIDANCE["transport"]
    return result.guidance

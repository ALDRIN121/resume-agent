"""Provider failures expose safe categories and only narrowly bounded retries."""
from datetime import UTC, datetime

import httpx
import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ValidationError


class StatusError(Exception):
    def __init__(self, status, headers=None, code=None):
        super().__init__("SECRET provider response and API key")
        self.status_code = status
        self.response = httpx.Response(status, headers=headers or {})
        self.code = code


@pytest.mark.parametrize("exc,code,delay", [
    (StatusError(401), "authentication", None),
    (StatusError(403), "authentication", None),
    (StatusError(404), "model_unavailable", None),
    (StatusError(429, {"Retry-After": "2"}), "rate_limited", 2),
    (StatusError(429, {"Retry-After": "61"}), "rate_limited", None),
    (StatusError(429, {"Retry-After": "-1"}), "rate_limited", None),
    (StatusError(429), "rate_limited", None),
    (StatusError(503), "provider_server", 0.5),
    (TimeoutError("SECRET"), "transport", 0.5),
    (httpx.ConnectError("SECRET"), "transport", 0.5),
    (StatusError(400, code="context_length_exceeded"), "context_limit", None),
    (RuntimeError("SECRET unknown server error"), "provider_unknown", None),
    (OutputParserException("SECRET invalid json"), "invalid_output", 0),
])
def test_typed_failures_are_sanitized_and_narrowly_retryable(exc, code, delay):
    from resume_agent.provider_errors import classify_provider_error
    failure = classify_provider_error(exc)
    assert failure.code == code
    assert failure.retry_after == delay
    assert "SECRET" not in str(failure)
    assert failure.guidance


@pytest.mark.parametrize("value,delay", [
    ("Thu, 12 Nov 2026 12:00:30 GMT", 30),
    ("Thu, 12 Nov 2026 12:01:01 GMT", None),
    ("Thu, 12 Nov 2026 11:59:59 GMT", None),
    ("garbage", None), ("nan", None), ("0", 0), ("60", 60),
])
def test_retry_after_http_date_and_numeric_bounds(value, delay):
    from resume_agent.provider_errors import classify_provider_error
    failure = classify_provider_error(StatusError(429, {"Retry-After": value}),
                                      now=datetime(2026, 11, 12, 12, tzinfo=UTC).timestamp())
    assert failure.retry_after == delay


def test_nested_typed_cause_and_schema_errors_are_classified():
    from resume_agent.provider_errors import classify_provider_error
    wrapped = RuntimeError("SECRET wrapper")
    wrapped.__cause__ = StatusError(401)
    assert classify_provider_error(wrapped).code == "authentication"

    class Required(BaseModel):
        value: int
    try:
        Required.model_validate({"value": "SECRET"})
    except ValidationError as exc:
        result = classify_provider_error(exc)
    assert result.code == "invalid_output"
    assert "SECRET" not in str(result)

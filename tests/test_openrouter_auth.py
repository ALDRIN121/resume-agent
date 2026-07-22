"""Tests for OpenRouter sign-in (OAuth exchange), provider auto-detect, and the
OpenRouter LLM branch — all offline (respx mocks the OpenRouter endpoint)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.config import ResumeAgentSettings
from resume_agent.llm import describe_llm_error, get_chat_model

_KEYS_ENDPOINT = "https://openrouter.ai/api/v1/auth/keys"


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    """Point config + secrets writes at a temp dir so nothing touches real $HOME."""
    from resume_agent import config
    from resume_agent.ui import setup_wizard

    cfg_file = tmp_path / "config.yaml"
    secrets = tmp_path / ".env"
    for mod in (config, setup_wizard):
        monkeypatch.setattr(mod, "CONFIG_DIR", tmp_path, raising=False)
        monkeypatch.setattr(mod, "SECRETS_FILE", secrets, raising=False)
    monkeypatch.setattr(config, "CONFIG_FILE", cfg_file, raising=False)
    # Drop any provider keys inherited from the real environment.
    for var in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                "GOOGLE_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY", "OLLAMA_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return {"config_file": cfg_file, "secrets": secrets}


@respx.mock
def test_openrouter_exchange_provisions_key_and_activates(isolated_config):
    route = respx.post(_KEYS_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"key": "sk-or-test-123"})
    )
    client = TestClient(create_app(), base_url="http://localhost")

    resp = client.post(
        "/api/auth/openrouter/exchange",
        json={"code": "auth-code", "code_verifier": "verifier"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["settings"]["provider"] == "openrouter"
    assert route.called
    # Key persisted to the secrets file; provider written to config.
    assert "sk-or-test-123" in isolated_config["secrets"].read_text()
    assert "openrouter" in isolated_config["config_file"].read_text()


@respx.mock
def test_openrouter_exchange_reports_failure(isolated_config):
    respx.post(_KEYS_ENDPOINT).mock(return_value=httpx.Response(400, json={"error": "bad code"}))
    client = TestClient(create_app(), base_url="http://localhost")

    resp = client.post(
        "/api/auth/openrouter/exchange",
        json={"code": "bad", "code_verifier": "verifier"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "error" in body
    # Nothing was persisted.
    assert not isolated_config["secrets"].exists()


def test_detect_reports_present_env_key(isolated_config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-present")
    client = TestClient(create_app(), base_url="http://localhost")

    resp = client.get("/api/settings/detect")

    assert resp.status_code == 200
    detected = resp.json()["detected"]
    providers = {d["provider"] for d in detected}
    assert "openrouter" in providers
    entry = next(d for d in detected if d["provider"] == "openrouter")
    assert entry["source"] == "env"
    assert entry["defaultModel"]


def test_llm_openrouter_uses_openai_compatible_client():
    settings = ResumeAgentSettings(
        provider="openrouter",
        openrouter_api_key="sk-or-test",
    )
    llm = get_chat_model(settings, task="default")
    assert llm.__class__.__name__ == "ChatOpenAI"
    # Routed at OpenRouter, not the default OpenAI host.
    assert "openrouter.ai" in str(llm.openai_api_base)


@pytest.mark.parametrize(
    "raw,expected_fragment",
    [
        ("Error code: 402 - insufficient credits", "Out of LLM credits"),
        ("429 Too Many Requests: rate limit exceeded", "Rate limited"),
        ("openai.RateLimitError: insufficient_quota", "Out of LLM credits"),
        ("Error code: 401 - invalid api key", "rejected the API key"),
        ("Some unexpected boom", "Some unexpected boom"),
    ],
)
def test_describe_llm_error_classifies(raw, expected_fragment):
    assert expected_fragment in describe_llm_error(Exception(raw))

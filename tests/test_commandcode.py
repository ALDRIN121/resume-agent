"""Command Code adapter and settings integration, without live credentials."""
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from resume_agent import config
from resume_agent.api.app import create_app
from resume_agent.config import ResumeAgentSettings
from resume_agent.llm import describe_llm_error, get_chat_model
from resume_agent.ui import setup_wizard

MODEL = "deepseek/deepseek-v4.1-flash"
ENDPOINT = "https://api.commandcode.ai/provider/v1/chat/completions"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for mod in (config, setup_wizard):
        monkeypatch.setattr(mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(mod, "CONFIG_FILE", tmp_path / "config.yaml")
        monkeypatch.setattr(mod, "SECRETS_FILE", tmp_path / ".env")
    monkeypatch.setattr(ResumeAgentSettings, "model_config", {
        **ResumeAgentSettings.model_config, "env_file": None,
    })
    for name in (*setup_wizard._KEY_ENV.values(), "COMMAND_CODE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_catalog_exposes_commandcode():
    client = TestClient(create_app(), base_url="http://localhost")
    data = client.get("/api/settings/providers").json()
    provider = next(p for p in data["providers"] if p["id"] == "commandcode")
    assert provider["name"] == "Command Code"
    assert provider["needsKey"] is True
    assert data["models"]["commandcode"][0] == MODEL
    assert data["visionModels"]["commandcode"] == []


@respx.mock
async def test_adapter_sends_authenticated_chat_request(isolated):
    route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json={
        "id": "test", "object": "chat.completion", "created": 1, "model": MODEL,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
    }))
    settings = ResumeAgentSettings(provider="commandcode", COMMAND_CODE_API_KEY="test-secret",
                                   model={"default": MODEL, "vision": ""})
    llm = get_chat_model(settings)
    reply = await llm.ainvoke("Hello")
    assert reply.content == "OK"
    assert route.calls[0].request.headers["authorization"] == "Bearer test-secret"
    assert json.loads(route.calls[0].request.content)["model"] == MODEL
    assert llm.request_timeout == 120
    assert llm.max_retries == 2


def test_save_and_test_settings_do_not_expose_key(isolated, monkeypatch):
    client = TestClient(create_app(), base_url="http://localhost")
    result = client.put("/api/settings", json={
        "provider": "commandcode", "default_model": MODEL,
        "vision_enabled": False, "api_key": "test-secret",
    })
    assert result.status_code == 200
    data = result.json()
    assert data["providerName"] == "Command Code"
    assert data["status"] == "connected"
    assert data["visionEnabled"] is False
    assert "test-secret" not in result.text
    assert "test-secret" not in (isolated / "config.yaml").read_text()
    assert "COMMAND_CODE_API_KEY=test-secret" in (isolated / ".env").read_text()
    assert (isolated / ".env").stat().st_mode & 0o777 == 0o600
    detected = client.get("/api/settings/detect").json()["detected"]
    assert any(p["provider"] == "commandcode" and p["defaultModel"] == MODEL for p in detected)


def test_configuration_requires_selected_provider_key(isolated):
    (isolated / "config.yaml").write_text("provider: commandcode\n")
    settings = ResumeAgentSettings(provider="commandcode", OPENAI_API_KEY="unrelated")
    assert not settings.is_configured()


def test_auth_error_does_not_send_commandcode_users_to_openrouter():
    message = describe_llm_error(RuntimeError("401 authentication_error"))
    assert "Settings" in message
    assert "OpenRouter" not in message


def test_disabled_vision_skips_model_call(monkeypatch):
    from resume_agent.agents import pdf_validator

    def unexpected_call(*args, **kwargs):
        pytest.fail("Disabled vision must not call a text-only provider")

    monkeypatch.setattr(pdf_validator, "get_chat_model", unexpected_call)
    settings = ResumeAgentSettings(model={"default": MODEL, "vision": ""})
    result = pdf_validator.pdf_validator_node({"page_images": ["page.png"]}, settings=settings)
    assert result == {"validation_passed": True, "validation_feedback": None}


def test_commandcode_provider_switch_disables_stale_vision():
    from resume_agent.api.routers.settings import SettingsUpdate, _settings_from_request
    settings = ResumeAgentSettings(model={"default": "old", "vision": "claude-opus-4-8"})
    updated = _settings_from_request(settings, SettingsUpdate(provider="commandcode", default_model=MODEL))
    assert updated.model.vision == ""


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_checkpoint_roundtrip_uses_registered_resume_types(tmp_path, monkeypatch, caplog, asynchronous):
    from resume_agent import checkpoint
    from resume_agent.schemas import GapAnalysis, JobDescription, PersonalInfo, UserResume
    monkeypatch.setattr(checkpoint, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(checkpoint, "STATE_DB", tmp_path / "state.sqlite")
    value = {"jd": JobDescription(company="TechCorp", role_title="Engineer"),
             "resume": UserResume(personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com")),
             "gaps": GapAnalysis()}
    def verify(saver):
        decoded = saver.serde.loads_typed(saver.serde.dumps_typed(value))
        assert decoded == value
        assert isinstance(decoded["resume"], UserResume)
        assert "unregistered type" not in caplog.text
    if asynchronous:
        async with checkpoint.get_async_checkpointer() as saver:
            verify(saver)
    else:
        with checkpoint.get_checkpointer() as saver:
            verify(saver)

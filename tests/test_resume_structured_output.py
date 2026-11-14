"""Resume parsing supports arbitrary skill categories on OpenAI-compatible APIs."""

import json

import httpx
import pytest
import respx
import yaml

from resume_agent.agents import base_resume_loader as loader
from resume_agent.agents import hitl
from resume_agent.config import ResumeAgentSettings
from resume_agent.schemas import GapAnalysis, UserResume

PROVIDERS = [
    ("openai", "OPENAI_API_KEY", "https://api.openai.com/v1/chat/completions"),
    ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/chat/completions"),
    ("commandcode", "COMMAND_CODE_API_KEY", "https://api.commandcode.ai/provider/v1/chat/completions"),
]


def resume_response(request, payload):
    body = json.loads(request.content)
    if body.get("response_format", {}).get("type") == "json_schema":
        return httpx.Response(400, json={"error": {
            "message": "Invalid schema for response_format 'UserResume': Extra required key 'skills' supplied.",
            "type": "invalid_request_error", "param": "response_format", "code": None,
        }})

    if body.get("tools"):
        tool = body["tools"][0]["function"]
        assert tool["strict"] is False
        assert tool["parameters"]["properties"]["skills"]["additionalProperties"] == {
            "type": "array", "items": {"type": "string"},
        }
        message = {"role": "assistant", "content": None, "tool_calls": [{
            "id": "resume-call", "type": "function", "function": {
                "name": "UserResume", "arguments": json.dumps(payload),
            },
        }]}
    else:
        assert any('"skills"' in str(message["content"]) for message in body["messages"])
        message = {"role": "assistant", "content": json.dumps(payload)}
    return httpx.Response(200, json={
        "id": "resume-test", "object": "chat.completion", "created": 1,
        "model": body["model"],
        "choices": [{"index": 0, "finish_reason": "tool_calls" if body.get("tools") else "stop", "message": message}],
    })


@pytest.mark.parametrize("provider,key_name,endpoint", PROVIDERS)
@pytest.mark.parametrize("stage", ["parse", "enrich"])
@respx.mock
def test_resume_keeps_arbitrary_skill_categories(tmp_path, monkeypatch, provider, key_name, endpoint, stage):
    settings = ResumeAgentSettings(
        _env_file=None, provider=provider, **{key_name: "test-key"},
        model={"default": "test-model", "vision": ""},
    )
    monkeypatch.setattr(ResumeAgentSettings, "load", lambda: settings)
    saved = tmp_path / "base_resume.yaml"
    monkeypatch.setattr(loader, "BASE_RESUME_FILE", saved)
    payload = {
        "personal": {"full_name": "Test User", "email": "test@example.com"},
        "skills": {"Languages": ["Python", "Go"], "Data & ML Platforms": ["Spark"]},
    }
    respx.post(endpoint).mock(side_effect=lambda request: resume_response(request, payload))

    if stage == "parse":
        source = tmp_path / "resume.tex"
        source.write_text("Test User, test@example.com; Languages: Python, Go; Data & ML Platforms: Spark")
        result = loader.parse_and_save_resume(source)
        assert yaml.safe_load(saved.read_text())["skills"] == payload["skills"]
    else:
        monkeypatch.setattr(hitl, "interrupt", lambda _: {"answers": {"q1": "I have used Go."}})
        result = hitl.hitl_node({
            "base_resume": UserResume(personal=payload["personal"]),
            "gap_analysis": GapAnalysis(open_questions=[{
                "id": "q1", "prompt": "Have you used Go?", "why_asking": "Required skill",
            }]),
        }, settings=settings)["tailored_resume"]

    assert isinstance(result, UserResume)
    assert result.skills == payload["skills"]
    assert result.personal.email == "test@example.com"


@respx.mock
def test_resume_parser_still_rejects_invalid_model_output(tmp_path, monkeypatch):
    settings = ResumeAgentSettings(
        _env_file=None, provider="openai", OPENAI_API_KEY="test-key",
        model={"default": "test-model", "vision": ""},
    )
    monkeypatch.setattr(ResumeAgentSettings, "load", lambda: settings)
    saved = tmp_path / "base_resume.yaml"
    monkeypatch.setattr(loader, "BASE_RESUME_FILE", saved)
    source = tmp_path / "resume.tex"
    source.write_text("Test User; Languages: Python")
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=lambda request: resume_response(request, {
            "personal": {"full_name": "Test User"}, "skills": {"Languages": ["Python"]},
        })
    )

    with pytest.raises(ValueError, match="email"):
        loader.parse_and_save_resume(source)
    assert not saved.exists()


@pytest.mark.parametrize('raw', [
    '```json\n{"personal":',
    '```json\n{"personal":{"full_name":"Test","email":"test@example.com"}}',
])
def test_unclosed_json_fence_stops_without_automatic_retry(raw):
    from resume_agent.model_tasks import invoke_bounded
    from resume_agent.provider_errors import ModelTaskError

    calls = []

    def invoke(messages):
        calls.append(messages)
        return raw

    with pytest.raises(ModelTaskError) as error:
        invoke_bounded(invoke, ['complete input'], UserResume, sleep=lambda _: None)
    assert error.value.code == 'truncated_output'
    assert error.value.attempts == 1
    assert len(calls) == 1

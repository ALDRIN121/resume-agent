"""The shared adapter preserves provider routing and validates structured replies."""

import json
import os

import httpx
import pytest
import respx
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError
from typer.testing import CliRunner

from resume_agent.config import MAX_LLM_OUTPUT_TOKENS, ResumeAgentSettings
from resume_agent.llm import get_chat_model
from resume_agent.schemas import UserResume


@pytest.fixture
def sdk(monkeypatch):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import litellm

    calls = []
    payload = {"personal": {"full_name": "Test User", "email": "test@example.com"},
               "skills": {"Languages": ["Python"], "Data & ML Platforms": ["Spark"]}}
    state = {"payload": payload, "omit_tool": False, "malformed": False}

    def completion(**kwargs):
        calls.append(kwargs)
        if kwargs.get("stream"):
            return iter([
                {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "O"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {"content": "K"}, "finish_reason": "stop"}]},
            ])
        content = state.get("raw_content", "invalid JSON" if state["malformed"] else json.dumps(state["payload"]))
        message = {"role": "assistant", "content": content}
        reason = state.get("finish_reason", "stop")
        if kwargs.get("tools") and not state["omit_tool"]:
            tool = kwargs["tools"][0]["function"]
            assert tool.get("strict") is False
            if "skills" in tool["parameters"]["properties"]:
                assert tool["parameters"]["properties"]["skills"]["additionalProperties"] == {
                    "type": "array", "items": {"type": "string"},
                }
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "test-call", "type": "function", "function": {
                    "name": tool["name"], "arguments": content,
                },
            }]}
            reason = "tool_calls"
        return litellm.ModelResponse(
            id="test-response", model=kwargs["model"], created=1,
            choices=[{"index": 0, "message": message, "finish_reason": reason}],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

    async def acompletion(**kwargs):
        result = completion(**kwargs)
        if kwargs.get("stream"):
            async def chunks():
                for chunk in result:
                    yield chunk
            return chunks()
        return result

    monkeypatch.setattr(litellm, "completion", completion)
    monkeypatch.setattr(litellm, "acompletion", acompletion)
    return calls, state


@pytest.mark.parametrize("provider,model,key_name,route,base_url", [
    ("openai", "gpt-5.4-mini", "OPENAI_API_KEY", "openai", None),
    ("anthropic", "claude-sonnet-4-6", "ANTHROPIC_API_KEY", "anthropic", None),
    ("gemini", "gemini-2.5-flash", "GOOGLE_API_KEY", "gemini", None),
    ("openrouter", "anthropic/claude-sonnet-4-6", "OPENROUTER_API_KEY", "openrouter", "https://router.example/v1"),
    ("commandcode", "deepseek/deepseek-v4.1-flash", "COMMAND_CODE_API_KEY", "openai", "https://api.commandcode.ai/provider/v1"),
    ("nvidia", "nvidia/llama-3.1-nemotron-70b-instruct", "NVIDIA_API_KEY", "nvidia_nim", "https://nim.example/v1"),
    ("ollama", "qwen2.5:7b", "OLLAMA_API_KEY", "ollama_chat", "https://ollama.example"),
])
@pytest.mark.parametrize("task", ["default", "vision"])
def test_factory_routes_existing_settings_through_litellm(sdk, provider, model, key_name, route, base_url, task):
    settings = ResumeAgentSettings(
        _env_file=None, provider=provider, **{key_name: "selected-provider-key"},
        model={"default": model, "vision": "selected-vision-model"},
        openrouter_base_url="https://router.example/v1", nvidia_base_url="https://nim.example/v1",
        ollama_base_url="https://ollama.example",
    )
    before = dict(os.environ)
    reply = get_chat_model(settings, task=task, temperature=0.2).invoke([HumanMessage(content="Hello")])
    request = sdk[0][-1]
    assert reply.content
    assert request["custom_llm_provider"] == route
    assert request["model"] == (model if task == "default" else "selected-vision-model")
    assert request["api_key"] == "selected-provider-key"
    assert request.get("api_base") == base_url
    assert request["max_tokens"] == MAX_LLM_OUTPUT_TOKENS
    assert request["temperature"] == 0.2
    assert request["timeout"] == 120
    assert request["messages"] == [{"role": "user", "content": "Hello"}]
    assert dict(os.environ) == before
    if provider == "openrouter":
        assert request["extra_headers"]["X-Title"] == "resume-generator"


def test_local_ollama_requires_no_key(sdk, monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    settings = ResumeAgentSettings(_env_file=None, provider="ollama")
    get_chat_model(settings).invoke("Hello")
    assert not sdk[0][-1].get("api_key")
    assert sdk[0][-1]["api_base"] == "http://localhost:11434"


def test_missing_selected_provider_key_fails_without_using_another_key(sdk, monkeypatch):
    monkeypatch.delenv("COMMAND_CODE_API_KEY", raising=False)
    settings = ResumeAgentSettings(_env_file=None, provider="commandcode", OPENAI_API_KEY="unrelated")
    with pytest.raises(ValueError, match="COMMAND_CODE_API_KEY"):
        get_chat_model(settings)
    assert sdk[0] == []


@pytest.mark.parametrize("model", ["gpt-5.4-mini", "private-custom-model"])
async def test_structured_output_preserves_skill_categories_sync_and_async(sdk, model):
    settings = ResumeAgentSettings(_env_file=None, provider="openai", OPENAI_API_KEY="test-key",
                                   model={"default": model, "vision": ""})
    structured = get_chat_model(settings, task="structured").with_structured_output(UserResume)
    messages = [SystemMessage(content="Parse this resume."), HumanMessage(content="Test User")]
    for reply in (structured.invoke(messages), await structured.ainvoke(messages)):
        assert isinstance(reply, UserResume)
        assert reply.skills == {"Languages": ["Python"], "Data & ML Platforms": ["Spark"]}
    request = sdk[0][-1]
    assert request.get("response_format", {}).get("type") != "json_schema"
    if model == "private-custom-model":
        assert not request.get("tools")
        assert not request.get("response_format")
        assert any('"skills"' in str(message["content"]) for message in request["messages"])


@pytest.mark.parametrize("model", ["gpt-5.4-mini", "private-custom-model"])
def test_invalid_structured_output_is_rejected(sdk, model):
    sdk[1]["payload"] = {"personal": {"full_name": "Test User"}}
    settings = ResumeAgentSettings(_env_file=None, provider="openai", OPENAI_API_KEY="test-key",
                                   model={"default": model, "vision": ""})
    structured = get_chat_model(settings, task="structured").with_structured_output(UserResume)
    with pytest.raises((ValidationError, ValueError), match="email"):
        structured.invoke("Parse this resume.")


def test_missing_tool_call_is_not_a_successful_empty_resume(sdk):
    sdk[1]["omit_tool"] = True
    settings = ResumeAgentSettings(_env_file=None, provider="openai", OPENAI_API_KEY="test-key",
                                   model={"default": "gpt-5.4-mini", "vision": ""})
    structured = get_chat_model(settings, task="structured").with_structured_output(UserResume)
    with pytest.raises((ValidationError, ValueError)):
        structured.invoke("Parse this resume.")


async def test_sync_async_streaming_and_vision_messages_reach_the_adapter(sdk):
    settings = ResumeAgentSettings(_env_file=None, provider="openai", OPENAI_API_KEY="test-key")
    llm = get_chat_model(settings, task="vision")
    messages = [HumanMessage(content=[
        {"type": "text", "text": "Check this page."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,test-image"}},
    ])]
    assert "".join(chunk.content for chunk in llm.stream(messages)) == "OK"
    assert "".join([chunk.content async for chunk in llm.astream(messages)]) == "OK"
    assert sdk[0][-1]["messages"][0]["content"][1]["image_url"]["url"] == "data:image/png;base64,test-image"
    assert sdk[0][-1]["model"] == settings.model.vision


def test_malformed_json_fallback_is_rejected(sdk):
    sdk[1]["malformed"] = True
    settings = ResumeAgentSettings(_env_file=None, provider="openai", OPENAI_API_KEY="test-key",
                                   model={"default": "private-custom-model", "vision": ""})
    with pytest.raises(ValueError, match="Invalid json"):
        get_chat_model(settings).with_structured_output(UserResume).invoke("Parse this resume.")


@pytest.mark.parametrize("model", ["gpt-5.4-mini", "private-custom-model"])
@pytest.mark.parametrize("malformed", [False, True])
def test_include_raw_retains_the_reply_and_parsing_error(sdk, model, malformed):
    sdk[1]["malformed"] = malformed
    settings = ResumeAgentSettings(_env_file=None, provider="openai", OPENAI_API_KEY="test-key",
                                   model={"default": model, "vision": ""})
    result = get_chat_model(settings).with_structured_output(UserResume, include_raw=True).invoke("Parse this resume.")
    assert result["raw"] is not None
    if malformed:
        assert result["parsed"] is None
        assert result["parsing_error"] is not None
    else:
        assert result["parsed"].personal.email == "test@example.com"
        assert result["parsing_error"] is None


@pytest.mark.parametrize("include_raw", [False, True])
def test_truncated_json_with_complete_required_fields_is_rejected(sdk, include_raw):
    sdk[1]["raw_content"] = (
        '{"personal":{"full_name":"Test User","email":"test@example.com"},'
        '"skills":{"Languages":["Python"],"Extra":["Go",'
    )
    settings = ResumeAgentSettings(_env_file=None, provider="openai", OPENAI_API_KEY="test-key",
                                   model={"default": "private-custom-model", "vision": ""})
    parser = get_chat_model(settings).with_structured_output(UserResume, include_raw=include_raw)
    if include_raw:
        result = parser.invoke("Parse this resume.")
        assert result["parsed"] is None
        assert result["parsing_error"] is not None
        assert result["raw"].content.endswith('["Go",')
    else:
        with pytest.raises(ValueError):
            parser.invoke("Parse this resume.")


def test_length_cutoff_is_rejected_even_when_the_json_is_complete(sdk):
    sdk[1]["finish_reason"] = "length"
    settings = ResumeAgentSettings(_env_file=None, provider="openai", OPENAI_API_KEY="test-key",
                                   model={"default": "private-custom-model", "vision": ""})
    with pytest.raises(ValueError, match="truncated"):
        get_chat_model(settings).with_structured_output(UserResume).invoke("Parse this resume.")


def test_complete_fenced_json_remains_supported(sdk):
    sdk[1]["raw_content"] = '```json\n' + json.dumps(sdk[1]["payload"]) + '\n```'
    settings = ResumeAgentSettings(_env_file=None, provider="openai", OPENAI_API_KEY="test-key",
                                   model={"default": "private-custom-model", "vision": ""})
    result = get_chat_model(settings).with_structured_output(UserResume).invoke("Parse this resume.")
    assert result.personal.email == "test@example.com"


def test_failed_cli_reimport_preserves_the_existing_resume(sdk, tmp_path, monkeypatch):
    from resume_agent import cli
    from resume_agent.agents import base_resume_loader

    sdk[1]["raw_content"] = '{"personal":{"full_name":"Test User","email":"test@example.com"},'
    settings = ResumeAgentSettings(_env_file=None, provider="openai", OPENAI_API_KEY="test-key",
                                   model={"default": "private-custom-model", "vision": ""})
    monkeypatch.setattr(ResumeAgentSettings, "load", lambda: settings)
    monkeypatch.setattr(ResumeAgentSettings, "is_configured", lambda self: True)
    saved = tmp_path / "base_resume.yaml"
    previous = 'personal:\n  full_name: Previous Owner\n  email: previous@example.com\n'
    saved.write_text(previous)
    for module in (cli, base_resume_loader):
        monkeypatch.setattr(module, "BASE_RESUME_FILE", saved)
    source = tmp_path / "resume.tex"
    source.write_text("Test User test@example.com")

    result = CliRunner().invoke(cli.app, ["init", "--source", str(source)])
    assert result.exit_code == 1
    assert saved.exists()
    assert saved.read_text() == previous


@pytest.mark.parametrize("provider,model,key_name,endpoint", [
    ("openai", "gpt-5.4-mini", "OPENAI_API_KEY", "https://api.openai.com/v1/chat/completions"),
    ("anthropic", "claude-sonnet-4-6", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/messages"),
    ("gemini", "gemini-2.5-flash", "GOOGLE_API_KEY", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"),
    ("openrouter", "openrouter/auto", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/chat/completions"),
    ("commandcode", "deepseek/deepseek-v4.1-flash", "COMMAND_CODE_API_KEY", "https://api.commandcode.ai/provider/v1/chat/completions"),
    ("nvidia", "meta/llama-3.3-70b-instruct", "NVIDIA_API_KEY", "https://nim.example/v1/chat/completions"),
    ("ollama", "llama3.2", "OLLAMA_API_KEY", "https://ollama.example/api/chat"),
])
@respx.mock
def test_provider_http_requests_keep_the_endpoint_model_and_key(provider, model, key_name, endpoint):
    payload = {
        "id": "test-response", "object": "chat.completion", "created": 1, "model": model,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "OK"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    if provider == "anthropic":
        payload = {"id": "test-response", "type": "message", "role": "assistant", "model": model,
                   "content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn",
                   "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
    elif provider == "gemini":
        payload = {"candidates": [{"index": 0, "content": {"role": "model", "parts": [{"text": "OK"}]},
                                   "finishReason": "STOP"}], "modelVersion": model,
                   "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2}}
    elif provider == "ollama":
        payload = {"model": model, "created_at": "2026-11-03T00:00:00Z",
                   "message": {"role": "assistant", "content": "OK"}, "done": True,
                   "done_reason": "stop", "total_duration": 1, "load_duration": 0,
                   "prompt_eval_count": 1, "eval_count": 1}
    route = respx.post(endpoint).mock(return_value=httpx.Response(200, json=payload))
    settings = ResumeAgentSettings(
        _env_file=None, provider=provider, **{key_name: "test-provider-key"},
        model={"default": model, "vision": ""},
        nvidia_base_url="https://nim.example/v1", ollama_base_url="https://ollama.example",
    )
    assert get_chat_model(settings).invoke("Hello").content == "OK"
    request = route.calls[0].request
    if provider == "anthropic":
        assert request.headers["x-api-key"] == "test-provider-key"
    elif provider == "gemini":
        assert (request.headers.get("x-goog-api-key") or request.url.params.get("key")) == "test-provider-key"
    else:
        assert request.headers["authorization"] == "Bearer test-provider-key"
    if provider != "gemini":
        assert json.loads(request.content)["model"] == model

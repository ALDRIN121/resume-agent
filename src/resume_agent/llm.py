"""Pluggable LLM factory — returns a BaseChatModel for a given task type."""

from __future__ import annotations

import json
import os
import re
from operator import itemgetter
from typing import TYPE_CHECKING, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableLambda, RunnableMap, RunnablePassthrough
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel

from .config import MAX_LLM_OUTPUT_TOKENS
from .provider_errors import StructuredOutputError, safe_error_guidance

if TYPE_CHECKING:
    from .config import ResumeAgentSettings

TaskType = Literal["default", "vision", "structured", "fast"]

# Use LiteLLM's bundled capability catalogue, including for offline Ollama use.
# Set this before importing LiteLLM so importing the CLI never fetches a catalogue.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm  # noqa: E402
from langchain_litellm import ChatLiteLLM  # noqa: E402


class ResumeChatLiteLLM(ChatLiteLLM):
    """Keep app schemas valid across models with different output capabilities."""

    def with_structured_output(self, schema: type[BaseModel], *, include_raw: bool = False):
        format_instructions = PydanticOutputParser(pydantic_object=schema).get_format_instructions()
        prompt = RunnableLambda(lambda messages: messages)
        if litellm.supports_function_calling(self.model, self.custom_llm_provider):
            # Strict schemas cannot represent arbitrary resume skill categories.
            tool = convert_to_openai_tool(schema, strict=False)
            bound = self.bind_tools([tool], tool_choice="required")
            parser = RunnableLambda(lambda message: parse_structured_response(message, schema, require_tool=True))
        else:
            instructions = SystemMessage(content=format_instructions)

            def add_schema(messages):
                return [instructions, *self._convert_input(messages).to_messages()]

            prompt = RunnableLambda(add_schema)
            bound = self
            if litellm.supports_response_schema(self.model, self.custom_llm_provider):
                bound = self.bind(response_format={"type": "json_object"})
            parser = RunnableLambda(lambda message: parse_structured_response(message, schema))

        if include_raw:
            parsed = RunnablePassthrough.assign(
                parsed=itemgetter("raw") | parser, parsing_error=lambda _: None,
            ).with_fallbacks(
                [RunnablePassthrough.assign(parsed=lambda _: None)],
                exception_key="parsing_error",
            )
            return prompt | RunnableMap(raw=bound) | parsed
        return prompt | bound | parser


def _incomplete_json(text: str) -> bool:
    """Recognize unclosed JSON containers/strings without repairing their contents."""
    if not text.lstrip().startswith(("{", "[")):
        return False
    stack, quoted, escaped = [], False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack or stack.pop() != ("{" if char == "}" else "["):
                return False
    return quoted or bool(stack)


def parse_structured_response(response: object, schema: type[BaseModel], *, require_tool: bool = False):
    """Validate complete structured/tool JSON; never salvage a partial response."""
    metadata = getattr(response, "response_metadata", {})
    reason = metadata.get("finish_reason") or metadata.get("stop_reason")
    if reason in {"length", "max_tokens", "max_output_tokens", "MAX_TOKENS"}:
        raise StructuredOutputError("truncated_output")
    if isinstance(response, schema):
        return response
    tool_calls = getattr(response, "tool_calls", [])
    invalid_calls = getattr(response, "invalid_tool_calls", [])
    if tool_calls:
        matching = [call for call in tool_calls if call.get("name") == schema.__name__]
        return schema.model_validate(matching[0]["args"] if matching else None)
    if invalid_calls:
        response = invalid_calls[0].get("args", "")
    elif require_tool:
        return schema.model_validate(None)
    else:
        response = getattr(response, "content", response)
    if isinstance(response, str):
        text = response.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1)
        try:
            response = json.loads(text)
        except json.JSONDecodeError:
            code = "truncated_output" if _incomplete_json(text) else "invalid_output"
            raise StructuredOutputError(code) from None
    return schema.model_validate(response)


def describe_llm_error(exc: Exception) -> str:
    """Return actionable guidance without echoing provider response text."""
    return safe_error_guidance(exc)


def get_chat_model(
    settings: ResumeAgentSettings,
    task: TaskType = "default",
    *,
    temperature: float = 0.3,
) -> BaseChatModel:
    """
    Return an appropriate BaseChatModel for the given provider + task type.

    task="vision"     — multimodal model that can process images
    task="structured" — model used for JSON structured-output extraction
    task="fast"       — lightweight model for quick classification tasks
    task="default"    — general-purpose reasoning model
    """
    provider = settings.provider
    model_name = (
        settings.model.vision if task == "vision" else settings.model.default
    )

    provider_routes = {
        "anthropic": "anthropic", "openai": "openai", "gemini": "gemini",
        "ollama": "ollama_chat", "nvidia": "nvidia_nim",
        "openrouter": "openrouter", "commandcode": "openai",
    }
    if provider not in provider_routes:
        raise ValueError(f"Unknown provider: {provider!r}")

    key_names = {
        "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
        "gemini": "GOOGLE_API_KEY", "ollama": "OLLAMA_API_KEY",
        "nvidia": "NVIDIA_API_KEY", "openrouter": "OPENROUTER_API_KEY",
        "commandcode": "COMMAND_CODE_API_KEY",
    }
    api_key = getattr(settings, f"{provider}_api_key") or os.environ.get(key_names[provider])
    if provider == "gemini":
        api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if provider != "ollama" and not api_key:
        raise StructuredOutputError("authentication")

    base_urls = {
        "ollama": settings.ollama_base_url,
        "nvidia": settings.nvidia_base_url or None,
        "openrouter": settings.openrouter_base_url,
        "commandcode": "https://api.commandcode.ai/provider/v1",
    }
    headers = None
    if provider == "openrouter":
        headers = {"HTTP-Referer": "https://github.com/resume-generator", "X-Title": "resume-generator"}

    return ResumeChatLiteLLM(
        model=model_name,
        custom_llm_provider=provider_routes[provider],
        api_key=api_key,
        api_base=base_urls.get(provider),
        extra_headers=headers,
        temperature=temperature,
        max_tokens=MAX_LLM_OUTPUT_TOKENS,
        request_timeout=120,
        max_retries=0,
        # ModelTaskRunner (or the bounded legacy helper) is the sole retry owner.
        # LiteLLM drops parameters (such as temperature) that a model rejects.
        model_kwargs={"num_retries": 0, "drop_params": True},
        use_responses_api=False,
    )

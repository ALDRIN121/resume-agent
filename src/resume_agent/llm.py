"""Pluggable LLM factory — returns a BaseChatModel for a given task type."""

from __future__ import annotations

import json
import os
import re
from operator import itemgetter
from typing import TYPE_CHECKING, Literal

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.output_parsers.openai_tools import PydanticToolsParser
from langchain_core.runnables import RunnableLambda, RunnableMap, RunnablePassthrough
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel

from .config import MAX_LLM_OUTPUT_TOKENS

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
            parser = PydanticToolsParser(tools=[schema], first_tool_only=True)
            # A model that omits the tool call must fail validation, not return None.
            parser = parser | RunnableLambda(schema.model_validate)
        else:
            instructions = SystemMessage(content=format_instructions)

            def add_schema(messages):
                return [instructions, *self._convert_input(messages).to_messages()]

            prompt = RunnableLambda(add_schema)
            bound = self
            if litellm.supports_response_schema(self.model, self.custom_llm_provider):
                bound = self.bind(response_format={"type": "json_object"})
            def parse_json(message):
                # Decode complete JSON only. LangChain's JSON parser repairs
                # truncated replies, which can silently drop resume sections.
                text = message.content.strip()
                fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
                if fenced:
                    text = fenced.group(1)
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise OutputParserException("Invalid json output from model.", llm_output=text) from exc
                return schema.model_validate(data)

            parser = RunnableLambda(parse_json)

        def require_complete(message):
            if message.response_metadata.get("finish_reason") == "length":
                raise OutputParserException("The model response was truncated; retry with a larger output budget.")
            return message

        parser = RunnableLambda(require_complete) | parser

        if include_raw:
            parsed = RunnablePassthrough.assign(
                parsed=itemgetter("raw") | parser, parsing_error=lambda _: None,
            ).with_fallbacks(
                [RunnablePassthrough.assign(parsed=lambda _: None)],
                exception_key="parsing_error",
            )
            return prompt | RunnableMap(raw=bound) | parsed
        return prompt | bound | parser


def describe_llm_error(exc: Exception) -> str:
    """Turn a raw provider exception into a short, actionable message for the UI.

    Covers the common failure modes users hit with OpenRouter / OpenAI-compatible
    providers — out of credits, rate limited, bad key — and falls back to the raw
    message for anything unrecognised.
    """
    low = str(exc).lower()

    def has(*needles: str) -> bool:
        return any(n in low for n in needles)

    # Out of credits — OpenAI reports this as 429 "insufficient_quota", OpenRouter as 402.
    if has("insufficient", "402", "payment required", "not enough credit", "requires more credit"):
        return (
            "Out of LLM credits. Check billing with your selected provider in Settings, "
            "or switch to another provider — then retry."
        )
    if has("429", "rate limit", "rate-limit", "too many requests"):
        return (
            "Rate limited by the model provider. Wait a moment and retry, or check "
            "the usage limits for your selected provider."
        )
    if has("upgrade_required"):
        return "Your Command Code plan does not include API access. Check your plan in Command Code Studio."
    if has("unsupported_model"):
        return "The model is not available from this provider. Choose an available model in Settings."
    if has("timeout", "timed out"):
        return "The model provider took too long to respond. Please retry."
    if has("401", "403", "authentication", "unauthorized", "invalid api key", "no auth credentials"):
        return (
            'The model provider rejected the API key. Reconnect in Settings '
            '("API key") or re-enter your key.'
        )
    return str(exc)


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
        raise ValueError(f"Missing {key_names[provider]}. Run: resume-generator setup")

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
        max_retries=2,
        # Retry once at the LangChain boundary; avoid nested SDK retry budgets.
        # LiteLLM drops parameters (such as temperature) that a model rejects.
        model_kwargs={"num_retries": 0, "drop_params": True},
        use_responses_api=False,
    )

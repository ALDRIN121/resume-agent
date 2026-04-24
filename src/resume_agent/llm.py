"""Pluggable LLM factory — returns a BaseChatModel for a given task type."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

from langchain_core.language_models import BaseChatModel

from .config import MAX_LLM_OUTPUT_TOKENS

if TYPE_CHECKING:
    from .config import ResumeAgentSettings

TaskType = Literal["default", "vision", "structured", "fast"]


def get_chat_model(
    settings: "ResumeAgentSettings",
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

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # Pass the key directly — do NOT write to os.environ, which would leak
        # the key into child subprocesses (Tectonic, Playwright).
        api_key = settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        return ChatAnthropic(
            model=model_name,
            temperature=temperature,
            max_tokens=MAX_LLM_OUTPUT_TOKENS,
            api_key=api_key,  # type: ignore[arg-type]
        )  # type: ignore[call-arg]

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        api_key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
        oai_model = _map_openai_model(model_name, task)
        return ChatOpenAI(
            model=oai_model,
            temperature=temperature,
            max_tokens=MAX_LLM_OUTPUT_TOKENS,
            api_key=api_key,  # type: ignore[arg-type]
        )

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_key = (
            settings.gemini_api_key
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            max_output_tokens=MAX_LLM_OUTPUT_TOKENS,
            google_api_key=api_key,  # type: ignore[arg-type]
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model_name,
            temperature=temperature,
            base_url=settings.ollama_base_url,
            # Force JSON output for structured extraction tasks so the model
            # doesn't return markdown-formatted text instead of a JSON object.
            format="json" if task == "structured" else None,
        )

    if provider == "nvidia":
        from langchain_nvidia_ai_endpoints import ChatNVIDIA

        api_key = settings.nvidia_api_key or os.environ.get("NVIDIA_API_KEY")
        kwargs: dict = dict(
            model=model_name,
            temperature=temperature,
            max_tokens=MAX_LLM_OUTPUT_TOKENS,
            nvidia_api_key=api_key,
        )
        if settings.nvidia_base_url:
            kwargs["base_url"] = settings.nvidia_base_url
        return ChatNVIDIA(**kwargs)  # type: ignore[arg-type]

    raise ValueError(f"Unknown provider: {provider!r}")


def _map_openai_model(model_name: str, task: TaskType) -> str:
    """Translate Anthropic model names to OpenAI equivalents."""
    if task == "vision":
        return "gpt-4o"
    if "opus" in model_name or "sonnet" in model_name:
        return "gpt-4o"
    return "gpt-4o-mini"

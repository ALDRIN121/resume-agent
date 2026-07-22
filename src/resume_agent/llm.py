"""Pluggable LLM factory — returns a BaseChatModel for a given task type."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

from langchain_core.language_models import BaseChatModel

from .config import MAX_LLM_OUTPUT_TOKENS

if TYPE_CHECKING:
    from .config import ResumeAgentSettings

TaskType = Literal["default", "vision", "structured", "fast"]


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
            "Out of LLM credits. Add credit to your OpenRouter account, switch to a "
            "free model (name ends in ':free'), or use local Ollama — then retry."
        )
    if has("429", "rate limit", "rate-limit", "too many requests"):
        return (
            "Rate limited by the model provider. Wait a moment and retry, pick a "
            "':free' model, or add $10 of OpenRouter credit to raise the daily limit."
        )
    if has("401", "403", "authentication", "unauthorized", "invalid api key", "no auth credentials"):
        return (
            'The model provider rejected the API key. Reconnect in Settings '
            '("Sign in with OpenRouter") or re-enter your key.'
        )
    return str(exc)


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
        # Use the configured model directly — model_name is already vision-aware
        # (settings.model.vision vs .default is chosen above by task).
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            max_tokens=MAX_LLM_OUTPUT_TOKENS,
            api_key=api_key,  # type: ignore[arg-type]
        )

    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        # OpenRouter is OpenAI-compatible — one key routes to hundreds of models.
        # The key is provisioned via the in-app "Sign in with OpenRouter" OAuth flow.
        api_key = settings.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY")
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            max_tokens=MAX_LLM_OUTPUT_TOKENS,
            api_key=api_key,  # type: ignore[arg-type]
            base_url=settings.openrouter_base_url,
            # OpenRouter ranking/attribution headers (optional but recommended).
            default_headers={
                "HTTP-Referer": "https://github.com/resume-generator",
                "X-Title": "resume-generator",
            },
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

        api_key = settings.ollama_api_key or os.environ.get("OLLAMA_API_KEY")
        client_kwargs: dict = {}
        if api_key:
            client_kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}

        return ChatOllama(
            model=model_name,
            temperature=temperature,
            base_url=settings.ollama_base_url,
            # Force JSON output for structured extraction tasks so the model
            # doesn't return markdown-formatted text instead of a JSON object.
            format="json" if task == "structured" else None,
            client_kwargs=client_kwargs or None,
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

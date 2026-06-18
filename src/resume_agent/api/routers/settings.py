"""Settings, provider catalogue, connection test, and doctor endpoints."""

from __future__ import annotations

import os
import shutil
import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ...config import BASE_RESUME_FILE, SOURCE_DIR, ResumeAgentSettings
from ...llm import get_chat_model
from ...ui import setup_wizard

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    provider: str | None = None
    default_model: str | None = None
    vision_model: str | None = None
    vision_enabled: bool | None = None
    base_url: str | None = None
    api_key: str | None = None
    generator_max: int | None = None
    compile_timeout_seconds: int | None = None
    scrape_timeout_seconds: int | None = None
    output_dir: str | None = None
    enable_hr_review: bool | None = None


class TestConnectionRequest(SettingsUpdate):
    model: str | None = None


@router.get("")
async def get_settings() -> dict[str, Any]:
    settings = ResumeAgentSettings.load()
    return _settings_payload(settings)


@router.put("")
async def update_settings(request: SettingsUpdate) -> dict[str, Any]:
    settings = _settings_from_request(ResumeAgentSettings.load(), request)
    _write_secret_if_present(settings.provider, request.api_key)
    settings.save()
    return _settings_payload(settings)


@router.get("/providers")
async def get_providers() -> dict[str, Any]:
    providers = []
    for provider_id, label, description, is_remote in setup_wizard._PROVIDERS:
        frontend_id = _frontend_provider_id(provider_id, is_remote)
        providers.append(
            {
                "id": frontend_id,
                "provider": provider_id,
                "name": label.split(" — ")[0].replace(" (Google)", ""),
                "sub": label.split(" — ")[1] if " — " in label else description,
                "cost": description.split(" · ")[0],
                "url": setup_wizard._KEY_URL.get(provider_id),
                "needsKey": provider_id != "ollama" or is_remote,
                "hint": description,
                "logo": label[:1],
                "remote": is_remote,
            }
        )
    return {
        "providers": providers,
        "models": _with_ollama_aliases(setup_wizard._MODELS),
        "visionModels": _with_ollama_aliases(setup_wizard._VISION),
    }


@router.post("/test-connection")
async def test_connection(request: TestConnectionRequest) -> dict[str, Any]:
    base = ResumeAgentSettings.load()
    settings = _settings_from_request(base, request)
    model = request.model or request.default_model
    if model:
        settings = settings.model_copy(
            update={"model": settings.model.model_copy(update={"default": model})}
        )
    if request.api_key:
        settings = _settings_with_secret(settings, request.api_key)

    started = time.perf_counter()
    try:
        llm = get_chat_model(settings, task="default", temperature=0.0)
        response = await llm.ainvoke("Reply with the single word: OK")
        return {
            "ok": True,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "reply": str(response.content).strip()[:120],
        }
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "reply": "",
            "error": str(exc),
        }


@router.post("/doctor")
async def doctor() -> dict[str, Any]:
    settings = ResumeAgentSettings.load()
    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "Tectonic (LaTeX engine)",
            shutil.which(settings.latex.tectonic_path) is not None,
            "Install Tectonic or update latex.tectonic_path.",
        )
    )
    checks.append(
        _check(
            "Poppler utils (PDF to image)",
            shutil.which("pdftoppm") is not None or shutil.which("pdfinfo") is not None,
            "Install poppler-utils.",
        )
    )
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        playwright_ok = True
    except ImportError:
        playwright_ok = False
    checks.append(_check("Playwright", playwright_ok, "Run: playwright install chromium."))

    provider = settings.provider
    if provider == "ollama":
        import httpx

        try:
            httpx.get(settings.ollama_base_url, timeout=3)
            key_ok = True
        except Exception:
            key_ok = False
        checks.append(_check("Ollama reachable", key_ok, settings.ollama_base_url))
    else:
        key_name = setup_wizard._KEY_ENV.get(provider, "API_KEY")
        key_ok = bool(getattr(settings, f"{provider}_api_key", None) or os.environ.get(key_name))
        checks.append(_check(key_name, key_ok, "Set it in ~/.resume_generator/.env."))

    checks.append(_check("Base resume", BASE_RESUME_FILE.exists(), f"Upload a resume or place one in {SOURCE_DIR}."))
    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def _settings_payload(settings: ResumeAgentSettings) -> dict[str, Any]:
    provider_id = _frontend_provider_id(settings.provider, False)
    return {
        "provider": settings.provider,
        "providerId": provider_id,
        "providerName": settings.provider.title() if settings.provider != "ollama" else "Ollama",
        "defaultModel": settings.model.default,
        "visionModel": settings.model.vision,
        "visionEnabled": bool(settings.model.vision),
        "baseUrl": settings.ollama_base_url if settings.provider == "ollama" else settings.nvidia_base_url or None,
        "generatorMax": settings.retries.generator_max,
        "compileTimeoutSeconds": settings.latex.compile_timeout_seconds,
        "scrapeTimeoutSeconds": settings.scraping.timeout_seconds,
        "outputDir": settings.output.base_dir,
        "enableHrReview": settings.features.enable_hr_review,
        "status": "connected" if settings.is_configured() else "reconnecting",
        "latencyMs": None,
        "lastTested": None,
        "testReply": None,
    }


def _settings_from_request(settings: ResumeAgentSettings, request: SettingsUpdate) -> ResumeAgentSettings:
    provider = _backend_provider_id(request.provider) if request.provider else settings.provider
    vision = request.vision_model if request.vision_model is not None else settings.model.vision
    if request.vision_enabled is False:
        vision = ""
    model = settings.model.model_copy(
        update={
            "default": request.default_model or getattr(request, "model", None) or settings.model.default,
            "vision": vision,
        }
    )
    updates: dict[str, Any] = {"provider": provider, "model": model}
    if request.base_url:
        if provider == "ollama":
            updates["ollama_base_url"] = request.base_url.rstrip("/")
        elif provider == "nvidia":
            updates["nvidia_base_url"] = request.base_url.rstrip("/")
    if request.generator_max is not None:
        updates["retries"] = settings.retries.model_copy(update={"generator_max": request.generator_max})
    if request.compile_timeout_seconds is not None:
        updates["latex"] = settings.latex.model_copy(update={"compile_timeout_seconds": request.compile_timeout_seconds})
    if request.scrape_timeout_seconds is not None:
        updates["scraping"] = settings.scraping.model_copy(update={"timeout_seconds": request.scrape_timeout_seconds})
    if request.output_dir is not None:
        updates["output"] = settings.output.model_copy(update={"base_dir": request.output_dir})
    if request.enable_hr_review is not None:
        updates["features"] = settings.features.model_copy(update={"enable_hr_review": request.enable_hr_review})
    return settings.model_copy(update=updates)


def _settings_with_secret(settings: ResumeAgentSettings, api_key: str) -> ResumeAgentSettings:
    field = {
        "gemini": "gemini_api_key",
        "nvidia": "nvidia_api_key",
        "anthropic": "anthropic_api_key",
        "openai": "openai_api_key",
        "ollama": "ollama_api_key",
    }.get(settings.provider)
    return settings.model_copy(update={field: api_key}) if field else settings


def _write_secret_if_present(provider: str, api_key: str | None) -> None:
    if not api_key:
        return
    env_name = setup_wizard._KEY_ENV.get(provider) or ("OLLAMA_API_KEY" if provider == "ollama" else None)
    if env_name:
        setup_wizard._write_secret(env_name, api_key)
        os.environ[env_name] = api_key


def _frontend_provider_id(provider: str, remote: bool) -> str:
    if provider == "ollama":
        return "ollama_remote" if remote else "ollama_local"
    return provider


def _backend_provider_id(provider_id: str | None) -> str:
    if provider_id in {"ollama_local", "ollama_remote"}:
        return "ollama"
    return provider_id or "ollama"


def _with_ollama_aliases(data: dict[str, list[str]]) -> dict[str, list[str]]:
    result = dict(data)
    if "ollama" in data:
        result["ollama_local"] = data["ollama"]
        result["ollama_remote"] = data["ollama"]
    return result


def _check(label: str, ok: bool, hint: str) -> dict[str, Any]:
    return {"label": label, "ok": ok, "hint": "" if ok else hint}

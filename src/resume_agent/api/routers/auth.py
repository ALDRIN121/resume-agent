"""OpenRouter OAuth (PKCE) — exchange an authorization code for an API key.

"Sign in with OpenRouter" is the app's one-click LLM setup: the browser runs the
PKCE flow (see the frontend), OpenRouter redirects back with a ``code``, and this
endpoint exchanges ``{code, code_verifier}`` for a user-owned API key which is then
persisted and made the active provider. No manual key entry, no provider picking.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from ...config import ResumeAgentSettings
from ...ui import setup_wizard
from .settings import _settings_payload

router = APIRouter(prefix="/api/auth/openrouter", tags=["auth"])

_KEYS_ENDPOINT = "https://openrouter.ai/api/v1/auth/keys"


class ExchangeRequest(BaseModel):
    code: str
    code_verifier: str


@router.post("/exchange")
async def exchange(request: ExchangeRequest) -> dict[str, Any]:
    """Exchange the OAuth code for an OpenRouter key, then activate the provider."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _KEYS_ENDPOINT,
                json={
                    "code": request.code,
                    "code_verifier": request.code_verifier,
                    "code_challenge_method": "S256",
                },
            )
        resp.raise_for_status()
        key = resp.json().get("key")
    except Exception as exc:
        return {"ok": False, "error": f"OpenRouter code exchange failed: {exc}"}

    if not key:
        return {"ok": False, "error": "OpenRouter did not return an API key."}

    # Persist the key to ~/.resume_generator/.env (chmod 600), never into config.yaml.
    setup_wizard._write_secret("OPENROUTER_API_KEY", key)

    # Make OpenRouter the active provider with sensible free-tier defaults.
    settings = ResumeAgentSettings.load()
    default_model = setup_wizard._MODELS["openrouter"][0]
    vision_model = setup_wizard._VISION["openrouter"][0]
    settings = settings.model_copy(
        update={
            "provider": "openrouter",
            "openrouter_api_key": key,
            "model": settings.model.model_copy(
                update={"default": default_model, "vision": vision_model}
            ),
        }
    )
    settings.save()

    return {"ok": True, "settings": _settings_payload(settings)}

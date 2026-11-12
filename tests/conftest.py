"""Isolate application state before test modules import the application."""

import atexit
import os
import tempfile
from pathlib import Path

import pytest

# API imports initialize the library immediately, so a pytest fixture is too late.
# Child processes inherit this environment, including isolated Python (-I).
_state_directory = tempfile.TemporaryDirectory(prefix="resume-agent-tests-")
atexit.register(_state_directory.cleanup)
for _name in tuple(os.environ):
    if (
        _name.startswith(("RESUME_GENERATOR_", "LITELLM_"))
        or _name.endswith(("_API_KEY", "_API_TOKEN", "_BASE_URL"))
        or _name in {
            "ANTHROPIC_AUTH_TOKEN", "OPENAI_ACCESS_TOKEN", "OPENAI_API_BASE",
            "AZURE_API_BASE", "AZURE_API_VERSION", "GOOGLE_APPLICATION_CREDENTIALS",
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        }
    ):
        os.environ.pop(_name)
os.environ["RESUME_GENERATOR_STATE_DIR"] = str(Path(_state_directory.name).resolve())
# LiteLLM must use its bundled cost map rather than fetching one during imports.
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"


@pytest.fixture
def public_dns(monkeypatch):
    """Keep mocked HTTP tests independent of public DNS availability."""
    import socket

    def resolve(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", port or 443))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)

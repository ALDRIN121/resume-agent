"""State isolation contracts exercised in fresh application processes."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]


def _sandbox(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "project"
    home.mkdir()
    cwd.mkdir()
    current = home / ".resume_generator"
    legacy = home / ".resume_agent"
    current.mkdir()
    legacy.mkdir()
    (current / "config.yaml").write_text("provider: openai\n", encoding="utf-8")
    (current / ".env").write_text("OPENAI_API_KEY=fake-home-sentinel\n", encoding="utf-8")
    (legacy / "legacy-marker.txt").write_text("do not migrate\n", encoding="utf-8")
    (cwd / ".env").write_text("ANTHROPIC_API_KEY=fake-cwd-sentinel\n", encoding="utf-8")
    env = os.environ.copy()
    env["HOME"] = str(home)
    before = _files(home) | _files(cwd)
    return home, cwd, env, before


def _files(directory):
    return {str(path): path.read_bytes() for path in directory.rglob("*") if path.is_file()}


def _run(code, cwd, env):
    # Do not let pytest include the child environment in failure tracebacks.
    __tracebackhide__ = True
    result = subprocess.run(
        [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]);\n" + code,
         str(PROJECT / "src")],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_settings_override_ignores_home_and_cwd_secrets(tmp_path):
    # Ignoring the override, loading cwd dotenv, or migrating home breaks this contract.
    home, cwd, env, before = _sandbox(tmp_path)
    state = tmp_path / "state"
    env["RESUME_GENERATOR_STATE_DIR"] = str(state)
    state.mkdir()
    (state / ".env").write_text("NVIDIA_API_KEY=fake-state-secret\n", encoding="utf-8")
    data = _run('''
import json
from resume_agent import config
settings = config.ResumeAgentSettings.load()
settings.save()
print(json.dumps({
    "root": str(config.CONFIG_DIR), "provider": settings.provider,
    "home_secret_absent": settings.openai_api_key is None,
    "cwd_secret_absent": settings.anthropic_api_key is None,
    "state_secret_loaded": settings.nvidia_api_key == "fake-state-secret",
    "paths": [str(path) for path in (config.CONFIG_FILE, config.SECRETS_FILE,
              config.SOURCE_DIR, config.BASE_RESUME_FILE, config.STATE_DB)],
}))
''', cwd, env)
    assert data["root"] == str(state)
    assert data["provider"] == "ollama"
    assert data["home_secret_absent"] and data["cwd_secret_absent"]
    assert data["state_secret_loaded"]
    assert all(Path(path).is_relative_to(state) for path in data["paths"])
    assert (state / "config.yaml").exists()
    assert _files(home) | _files(cwd) == before


def test_override_does_not_migrate_legacy_home(tmp_path):
    home, cwd, env, before = _sandbox(tmp_path)
    state = tmp_path / "fresh-state"
    env["RESUME_GENERATOR_STATE_DIR"] = str(state)
    data = _run('''
import json
from resume_agent.config import CONFIG_DIR, ResumeAgentSettings, migrate_config_dir
migrate_config_dir()
settings = ResumeAgentSettings.load()
settings.save()
print(json.dumps({"root": str(CONFIG_DIR), "migrated": (CONFIG_DIR / "legacy-marker.txt").exists()}))
''', cwd, env)
    assert data == {"root": str(state), "migrated": False}
    assert _files(home) | _files(cwd) == before


@pytest.mark.parametrize("override", ["~/isolated-state", "relative-state/../isolated-state"])
def test_override_expands_and_resolves_paths(tmp_path, override):
    home, cwd, env, before = _sandbox(tmp_path)
    env["RESUME_GENERATOR_STATE_DIR"] = override
    data = _run('''
import json
from resume_agent.config import CONFIG_DIR, ResumeAgentSettings
settings = ResumeAgentSettings.load()
print(json.dumps({"root": str(CONFIG_DIR), "provider": settings.provider}))
''', cwd, env)
    expected = home / "isolated-state" if override.startswith("~") else cwd / "isolated-state"
    assert data == {"root": str(expected), "provider": "ollama"}
    assert _files(home) | _files(cwd) == before


def test_default_state_path_remains_compatible(tmp_path):
    home, cwd, env, before = _sandbox(tmp_path)
    env.pop("RESUME_GENERATOR_STATE_DIR")
    data = _run('''
import json
from resume_agent.config import CONFIG_DIR, ResumeAgentSettings
settings = ResumeAgentSettings.load()
print(json.dumps({"root": str(CONFIG_DIR), "provider": settings.provider,
                  "home_secret_loaded": settings.openai_api_key == "fake-home-sentinel"}))
''', cwd, env)
    assert data == {"root": str(home / ".resume_generator"), "provider": "openai",
                    "home_secret_loaded": True}
    assert _files(home) | _files(cwd) == before


@pytest.mark.parametrize("override", ["", "   ", "\t\n"])
def test_empty_override_is_rejected_before_state_initialization(tmp_path, override):
    home, cwd, env, before = _sandbox(tmp_path)
    env["RESUME_GENERATOR_STATE_DIR"] = override
    data = _run('''
import json
try:
    from resume_agent import config
except ValueError as exc:
    print(json.dumps({"rejected": True, "reason": str(exc)}))
else:
    print(json.dumps({"rejected": False, "reason": ""}))
''', cwd, env)
    assert data == {"rejected": True, "reason": "RESUME_GENERATOR_STATE_DIR must not be empty"}
    assert _files(home) | _files(cwd) == before


def test_child_api_initializes_only_explicit_state(tmp_path):
    home, cwd, env, before = _sandbox(tmp_path)
    state = tmp_path / "api-state"
    env["RESUME_GENERATOR_STATE_DIR"] = str(state)
    data = _run('''
import json
from fastapi.testclient import TestClient
from resume_agent.api.app import create_app
from resume_agent import config, library
from resume_agent.api import run_manager
with TestClient(create_app(), base_url="http://localhost") as client:
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/api/settings").json()["provider"] == "ollama"
    assert client.put("/api/settings", json={"ui_theme": "dark"}).status_code == 200
print(json.dumps({"root": str(config.CONFIG_DIR), "database": str(library.LIBRARY_DB),
                  "history": str(run_manager._HISTORY_FILE)}))
''', cwd, env)
    assert data == {"root": str(state), "database": str(state / "library.sqlite"),
                    "history": str(state / "run_history.jsonl")}
    assert (state / "library.sqlite").exists()
    assert (state / "config.yaml").exists()
    assert _files(home) | _files(cwd) == before


def test_suite_startup_sanitizes_environment_before_application_import(tmp_path):
    home, cwd, env, before = _sandbox(tmp_path)
    env.update({
        "RESUME_GENERATOR_STATE_DIR": str(home / ".resume_generator"),
        "RESUME_GENERATOR_PROVIDER": "openai",
        "OPENAI_API_KEY": "fake-inherited-secret",
        "OLLAMA_BASE_URL": "https://provider.example.invalid",
        "LITELLM_PROXY_API_BASE": "https://proxy.example.invalid",
        "TEST_ORDINARY_RUNTIME_VARIABLE": "preserved",
    })
    data = _run(f'''
import json
import os
import runpy
runpy.run_path({str(PROJECT / "tests" / "conftest.py")!r})
from resume_agent.config import CONFIG_DIR, ResumeAgentSettings
settings = ResumeAgentSettings.load()
print(json.dumps({{
    "root": str(CONFIG_DIR), "provider": settings.provider,
    "inherited_key_absent": settings.openai_api_key is None,
    "endpoint_is_default": settings.ollama_base_url == "http://localhost:11434",
    "proxy_override_absent": "LITELLM_PROXY_API_BASE" not in os.environ,
    "runtime_preserved": os.environ.get("TEST_ORDINARY_RUNTIME_VARIABLE") == "preserved",
    "local_cost_map": os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP") == "True",
}}))
''', cwd, env)
    assert not Path(data.pop("root")).is_relative_to(tmp_path)
    assert data == {
        "provider": "ollama", "inherited_key_absent": True, "endpoint_is_default": True,
        "proxy_override_absent": True, "runtime_preserved": True, "local_cost_map": True,
    }
    assert _files(home) | _files(cwd) == before

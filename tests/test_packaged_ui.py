"""Exercise the UI shipped to users, without relying on the source checkout."""

import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def distributions(tmp_path_factory):
    project = Path(__file__).resolve().parents[1]
    output = tmp_path_factory.mktemp("ui-distributions")
    # uv builds the wheel from the sdist, checking both release artifacts.
    result = subprocess.run(
        ["uv", "build", "--python", sys.executable, "--out-dir", str(output)],
        cwd=project,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output


def test_sdist_contains_frontend_bundle(distributions):
    with tarfile.open(next(distributions.glob("*.tar.gz"))) as archive:
        paths = archive.getnames()
    assert any(path.endswith("/Frontend/dist/index.html") for path in paths)
    assert any("/Frontend/dist/assets/" in path and path.endswith(".js") for path in paths)
    assert any("/Frontend/dist/assets/" in path and path.endswith(".css") for path in paths)


def test_installed_wheel_serves_web_ui(distributions, tmp_path):
    installed = tmp_path / "installed"
    wheel = next(distributions.glob("*.whl"))
    result = subprocess.run(
        ["uv", "pip", "install", "--no-deps", "--target", str(installed), str(wheel)],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    # Use the existing runtime dependencies, but import our wheel ahead of any
    # editable install and run outside the repository under isolated Python.
    result = subprocess.run(
        [sys.executable, "-I", "-c", r'''
import os
import re
import sys
from pathlib import Path

installed = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(installed))
import resume_agent
from fastapi.testclient import TestClient
from resume_agent.api.app import create_app
from resume_agent.config import CONFIG_DIR, ResumeAgentSettings
from resume_agent.llm import get_chat_model

model = get_chat_model(ResumeAgentSettings(_env_file=None, provider="ollama"))
assert model.custom_llm_provider == "ollama_chat"
assert model.api_base == "http://localhost:11434"

assert Path(resume_agent.__file__).resolve().is_relative_to(installed)
assert CONFIG_DIR == Path(os.environ["RESUME_GENERATOR_STATE_DIR"]).resolve()
with TestClient(create_app(), base_url="http://localhost") as client:
    root = client.get("/")
    assert root.status_code == 200, root.text
    assert root.headers["content-type"].startswith("text/html")
    assert '<div id="root"></div>' in root.text
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', root.text)
    assert any(path.endswith(".js") for path in assets)
    assert any(path.endswith(".css") for path in assets)
    for path in assets:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.content
        assert not response.headers["content-type"].startswith("text/html")
    assert client.get("/library/saved-resume").text == root.text
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/api/health").json() == {"ok": True}
''', str(installed)],
        cwd=tmp_path,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

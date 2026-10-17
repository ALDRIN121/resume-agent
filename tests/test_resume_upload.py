"""Upload progress follows the actual parser and preserves a resume on failure."""
from unittest.mock import MagicMock

import pytest
import yaml
from fastapi.testclient import TestClient

from resume_agent.agents import base_resume_loader as loader
from resume_agent.api.app import create_app
from resume_agent.api.routers import resume as router
from resume_agent.config import ResumeAgentSettings
from resume_agent.schemas import UserResume


@pytest.mark.parametrize("fails", [False, True])
def test_upload_reports_the_real_parsing_phase(tmp_path, monkeypatch, fails):
    saved_file = tmp_path / "base_resume.yaml"
    old = UserResume(personal={"full_name": "Old Owner", "email": "old@example.com"})
    new = UserResume(personal={"full_name": "New Owner", "email": "new@example.com"})
    saved_file.write_text(yaml.safe_dump(old.model_dump()))
    monkeypatch.setattr(loader, "BASE_RESUME_FILE", saved_file)
    monkeypatch.setattr(router, "BASE_RESUME_FILE", saved_file)
    monkeypatch.setattr(router, "SOURCE_DIR", tmp_path / "source")
    monkeypatch.setattr(ResumeAgentSettings, "load", lambda: ResumeAgentSettings(_env_file=None))
    llm = MagicMock()
    if fails:
        llm.with_structured_output.return_value.invoke.side_effect = RuntimeError("Provider unavailable")
    else:
        llm.with_structured_output.return_value.invoke.return_value = new
    monkeypatch.setattr(loader, "get_chat_model", lambda *a, **k: llm)

    with TestClient(create_app(), base_url="http://localhost") as client:
        response = client.post("/api/resume/upload", files={
            "file": ("resume.tex", b"Resume text for New Owner", "text/plain"),
        })
        assert response.status_code == 200
        events = []
        with client.websocket_connect(f"/ws/resume-parse/{response.json()['job_id']}",
                                      headers={"host": "localhost"}) as socket:
            while True:
                event = socket.receive_json()
                events.append((event["stage_id"], event["status"]))
                if event["status"] == "failed" or event["stage_id"] == "write_yaml" and event["status"] == "done":
                    break
        assert events == [
            ("upload", "done"), ("extract", "running"), ("extract", "done"),
            ("parse", "running"),
        ] + ([("parse", "failed")] if fails else [
            ("parse", "done"), ("write_yaml", "running"), ("write_yaml", "done"),
        ])
        assert client.get("/api/resume").json()["personal"]["full_name"] == (
            "Old Owner" if fails else "New Owner"
        )


def test_cli_parser_still_works_without_progress_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "BASE_RESUME_FILE", tmp_path / "base.yaml")
    monkeypatch.setattr(ResumeAgentSettings, "load", lambda: ResumeAgentSettings(_env_file=None))
    llm = MagicMock()
    resume = UserResume(personal={"full_name": "CLI Owner", "email": "cli@example.com"})
    llm.with_structured_output.return_value.invoke.return_value = resume
    monkeypatch.setattr(loader, "get_chat_model", lambda *a, **k: llm)
    source = tmp_path / "resume.tex"
    source.write_text("Resume content")
    assert loader.parse_and_save_resume(source) == resume

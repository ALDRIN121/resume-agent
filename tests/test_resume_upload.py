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


def _private_import_client(tmp_path, parser=None):
    from fastapi import FastAPI

    from resume_agent.imports import ImportService
    from resume_agent.profile_store import ProfileStore
    from resume_agent.run_store import RunStore
    service = ImportService(RunStore(tmp_path / "library.sqlite", tmp_path / "state.sqlite"),
        ProfileStore(tmp_path / "profile.yaml"),
        parser=parser or (lambda text: UserResume(personal={
            "full_name": "Synthetic Candidate", "email": "example@example.invalid"})))
    app = FastAPI()
    app.include_router(router.create_profile_router(service))
    return TestClient(app), service


def test_private_profile_router_review_accept_conflict_and_source(tmp_path):
    client, service = _private_import_client(tmp_path)
    with client:
        created = client.post("/api/profile/imports", files={"file": ("source.tex", b"Full source text")})
        assert created.status_code == 201
        review = created.json()
        assert review["status"] == "pending_review"
        assert client.get(f"/api/profile/imports/{review['id']}").json()["source"]["text"] == "Full source text"
        assert client.get(f"/api/profile/imports/{review['id']}/source").content == b"Full source text"
        assert not service.profiles.path.exists()
        action = {"action_id": "accept-1", "review_id": review["pending"]["review_id"],
                  "draft_hash": review["pending"]["draft_hash"], "expected_profile_revision": None}
        stale = client.post(f"/api/profile/imports/{review['id']}/accept", json=action | {"review_id": "stale"})
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"]
        accepted = client.post(f"/api/profile/imports/{review['id']}/accept", json=action)
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "complete"
        assert client.post(f"/api/profile/imports/{review['id']}/accept", json=action).json() == accepted.json()
        assert client.get("/api/profile").json()["review_required"] is False
        assert client.get("/api/profile/imports/unknown").status_code == 404


def test_private_profile_router_reject_and_explicit_current_review(tmp_path):
    client, service = _private_import_client(tmp_path)
    current = service.profiles.save(None, UserResume(personal={
        "full_name": "Synthetic Candidate", "email": "example@example.invalid"}), {})
    with client:
        assert client.get("/api/profile").json()["review_required"] is True
        assert client.post("/api/profile/review", json={"expected_revision": "stale"}).status_code == 409
        reviewed = client.post("/api/profile/review", json={"expected_revision": current.revision})
        assert reviewed.status_code == 200
        assert reviewed.json()["review_required"] is False
        created = client.post("/api/profile/imports", files={"file": ("source.tex", b"Full source text")}).json()
        rejected = client.post(f"/api/profile/imports/{created['id']}/reject", json={
            "action_id": "reject-1", "review_id": created["pending"]["review_id"]})
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "cancelled"
        assert service.profiles.load_snapshot().revision == current.revision


def test_private_upload_limit_rejects_before_source_storage_or_parser(tmp_path):
    client, service = _private_import_client(tmp_path, lambda text: pytest.fail("parser called"))
    with client:
        response = client.post("/api/profile/imports", files={
            "file": ("source.pdf", b"x" * (10 * 1024 * 1024 + 1))})
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "upload_too_large"
    with service.operations.store.connection() as connection:
        assert connection.execute("SELECT count(*) FROM operations").fetchone()[0] == 0
    assert not service.profiles.path.exists()


@pytest.mark.parametrize("size,status", [(10 * 1024 * 1024, 200), (10 * 1024 * 1024 + 1, 413)])
def test_legacy_upload_size_checked_before_source_storage(tmp_path, monkeypatch, size, status):
    source_dir = tmp_path / "source"
    monkeypatch.setattr(router, "SOURCE_DIR", source_dir)
    async def no_external_parse(*args):
        pass
    monkeypatch.setattr(router, "_parse_resume_job", no_external_parse)
    with TestClient(create_app(), base_url="http://localhost") as client:
        result = client.post("/api/resume/upload", files={"file": ("resume.tex", b"x" * size)})
    assert result.status_code == status
    if status == 413:
        assert not source_dir.exists()
    else:
        assert next(source_dir.iterdir()).stat().st_size == size

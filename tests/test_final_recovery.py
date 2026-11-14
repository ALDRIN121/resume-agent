"""Public recovery boundaries with real persistence and fictional content."""
# Imported pytest fixtures are injected by their parameter names.
# ruff: noqa: F811
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_agent.contracts import AcceptImport, Continue, PresentSuggestions, ReviewPdf, RunRequest
from tests.test_release_service import Crash, release, reopen
from tests.test_release_service import setup as release_setup  # noqa: F401
from tests.test_v2_api import services
from tests.test_v2_workflow import PROFILE, build


@pytest.mark.parametrize("change_output", [False, True])
async def test_public_continue_reuses_reservation_before_release_row(
    tmp_path, monkeypatch, change_output
):
    import resume_agent.release_service as module

    calls = []
    service, workflow, ids = build(tmp_path, calls, questions=False)
    run = service.create(
        RunRequest(job_input="Engineer", input_type="text"), profile_snapshot=PROFILE
    )
    ids.append(run.id)
    pending = (await service.drive(run.id)).pending
    preview = workflow.content_preview(run.id, pending.review_id, pending.source_revision, [])
    view = await service.drive(
        run.id,
        PresentSuggestions(
            action_id="content",
            review_id=pending.review_id,
            source_revision=pending.source_revision,
            approved_ids=[],
            content_hash=preview.manifest.content_hash,
        ),
    )
    review = view.pending.review
    original = module.prepare_export
    reserved = []

    def crash(*args, **kwargs):
        plan = original(*args, **kwargs)
        reserved.append(plan)
        raise Crash()

    monkeypatch.setattr(module, "prepare_export", crash)
    with pytest.raises(Crash):
        await service.drive(
            run.id,
            ReviewPdf(
                action_id="approval",
                decision="approve",
                **{
                    key: getattr(review, key)
                    for key in ("review_id", "content_hash", "render_hash", "pdf_hash")
                },
            ),
        )
    assert service.store.release(run.id) is None
    monkeypatch.setattr(module, "prepare_export", original)
    restarted, workflow2, _ = build(tmp_path, calls, questions=False)
    if change_output:
        workflow2.output_dir = tmp_path / "changed-output"
    assert restarted.get(run.id).status == "interrupted"
    completed = await restarted.drive(run.id, Continue(action_id="recover"))
    assert completed.status == "complete", completed
    assert completed.release.destination == str(reserved[0].destination)
    assert completed.release.ownership_token == reserved[0].ownership_token
    assert (
        Path(completed.release.destination).read_bytes()
        == Path(completed.release.canonical_pdf_path).read_bytes()
    )
    assert len(list((tmp_path / "output").rglob("*.pdf"))) == 1 and len(calls) == 3


def test_startup_cleanup_conflict_is_durable_per_run_and_preserves_other_work(
    tmp_path, release_setup
):
    from resume_agent.config import ResumeAgentSettings
    from resume_agent.runtime import Runtime

    def crash(stage):
        if stage == "after_rename":
            raise Crash()

    with pytest.raises(Crash):
        release(release_setup, reopen(release_setup, crash))
    store, _, identifier, _, _, _ = release_setup
    plan = reopen(release_setup).inspect(identifier).plan
    plan.destination.write_bytes(b"unrelated replacement; preserve this file")
    store.cancel("run", identifier)
    from resume_agent.run_service import RunService

    other = RunService(store).create(
        RunRequest(job_input="Unrelated role", input_type="text"), profile_snapshot=PROFILE
    )
    for _ in range(2):
        runtime = Runtime(
            root=tmp_path, settings=ResumeAgentSettings(_env_file=None, provider="ollama")
        )
        view = runtime.runs.get(identifier)
        assert view.status == "cancelled"
        assert any(
            d.code == "export_ownership_conflict" and d.stage == "release_recovery"
            for d in view.diagnostics
        )
        assert runtime.runs.get(other.id).status == "queued"
        assert plan.destination.read_bytes() == b"unrelated replacement; preserve this file"


def test_deferred_import_is_discoverable_before_parsing_and_continues_saved_acceptance(
    tmp_path, monkeypatch
):
    from resume_agent.api.app import create_app

    runtime, calls = services(tmp_path)
    with TestClient(create_app(services=runtime), base_url="http://localhost") as client:
        created = client.post(
            "/api/resume/upload?defer_processing=true",
            files={"file": ("resume.tex", b"Complete fictional source.")},
        ).json()
        assert created["status"] == "pending_model" and calls == []
        listing = client.get("/api/profile/imports").json()
        assert listing["items"][0]["id"] == created["id"] and listing["total"] == 1
        assert "source" not in listing["items"][0]
        parsed = client.post("/api/profile/imports/" + created["id"] + "/continue", json=None)
        assert parsed.status_code == 200, parsed.text
        review = parsed.json()["pending"]
        assert calls == ["import_profile"]
    original = runtime.profiles.save_reviewed

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise Crash()

    monkeypatch.setattr(runtime.profiles, "save_reviewed", crash)
    with pytest.raises(Crash):
        asyncio.run(
            runtime.imports.drive(
                created["id"],
                AcceptImport(
                    action_id="accept",
                    **{
                        key: review[key]
                        for key in ("review_id", "draft_hash", "expected_profile_revision")
                    },
                ),
            )
        )
    monkeypatch.setattr(runtime.profiles, "save_reviewed", original)
    saved = runtime.profiles.path.read_bytes()
    with TestClient(create_app(services=runtime), base_url="http://localhost") as client:
        assert client.get("/api/profile/imports").json()["items"][0]["status"] == "interrupted"
        assert (
            client.post(
                "/api/profile/imports/" + created["id"] + "/continue", json=None
            ).status_code
            == 409
        )
        done = client.post(
            "/api/profile/imports/" + created["id"] + "/continue", json={"action_id": "resume"}
        )
        assert done.status_code == 200 and done.json()["status"] == "complete", done.text
        assert runtime.profiles.path.read_bytes() == saved and calls == ["import_profile"]
        pending = client.post(
            "/api/profile/imports?defer_processing=true",
            files={"file": ("other.tex", b"Other source.")},
        ).json()
        cancelled = client.post("/api/profile/imports/" + pending["id"] + "/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        assert (
            client.get("/api/profile/imports").json()["total"] == 0
            and runtime.profiles.path.read_bytes() == saved
        )

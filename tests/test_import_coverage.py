"""Supported source is retained whole; drafts never silently replace candidate facts."""

import hashlib
from unittest.mock import MagicMock

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from resume_agent.agents import base_resume_loader, jd_extractor
from resume_agent.config import ResumeAgentSettings
from resume_agent.imports import ImportInputError, extract_source
from resume_agent.schemas import JobDescription, UserResume


def candidate():
    return UserResume(
        personal={"full_name": "Example Candidate", "email": "example@example.invalid"}
    )


@pytest.mark.parametrize("size", [12_050, 48_000])
def test_resume_parser_receives_complete_supported_text(tmp_path, monkeypatch, size):
    text = "é" * (size - 12) + "FINAL_MARKER"
    source = tmp_path / "resume.tex"
    source.write_text(text)
    monkeypatch.setattr(base_resume_loader, "BASE_RESUME_FILE", tmp_path / "profile.yaml")
    monkeypatch.setattr(ResumeAgentSettings, "load", lambda: ResumeAgentSettings(_env_file=None))
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.side_effect = lambda messages: (
        candidate()
        if text in messages[1].content
        else (_ for _ in ()).throw(AssertionError("text lost"))
    )
    monkeypatch.setattr(base_resume_loader, "get_chat_model", lambda *args, **kwargs: llm)
    assert base_resume_loader.parse_and_save_resume(source) == candidate()


def test_resume_oversize_rejects_before_model_or_profile_write(tmp_path, monkeypatch):
    source = tmp_path / "resume.tex"
    source.write_text("a" * 48_001)
    saved = tmp_path / "profile.yaml"
    saved.write_text("original profile")
    monkeypatch.setattr(base_resume_loader, "BASE_RESUME_FILE", saved)
    monkeypatch.setattr(
        base_resume_loader, "get_chat_model", lambda *a, **k: pytest.fail("model called")
    )
    with pytest.raises(ValueError, match="48,000"):
        base_resume_loader.parse_and_save_resume(source)
    assert saved.read_text() == "original profile"


@pytest.mark.parametrize("size", [8_050, 48_000])
def test_jd_full_text_reaches_model_and_storage(monkeypatch, size):
    text = "x" * (size - 17) + "RESTRICTED_REGION"
    llm = MagicMock()

    def parse(messages):
        assert text in messages[1].content
        return JobDescription(company="Example", role_title="Engineer")

    llm.with_structured_output.return_value.invoke.side_effect = parse
    monkeypatch.setattr(jd_extractor, "get_chat_model", lambda *a, **k: llm)
    result = jd_extractor.jd_extractor_node(
        {"raw_input": text}, settings=ResumeAgentSettings(_env_file=None)
    )
    assert result["jd"].raw_text == text


def test_jd_oversize_rejected_before_model_setup(monkeypatch):
    monkeypatch.setattr(jd_extractor, "get_chat_model", lambda *a, **k: pytest.fail("model called"))
    with pytest.raises(ValueError, match="48,000"):
        jd_extractor.jd_extractor_node({"raw_input": "a" * 48_001})


def make_pdf():
    import io

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 250 Td (Synthetic source text) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_blank_page(width=300, height=300)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_records_every_page_and_source_hash(tmp_path):
    raw = make_pdf()
    result = extract_source(raw, "resume.pdf")
    assert result.text.strip() == "Synthetic source text"
    assert [page.page_number for page in result.pages] == [1, 2]
    assert [page.readable for page in result.pages] == [True, False]
    assert result.pages[1].warning
    assert result.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert all(page.source_sha256 == result.source_sha256 for page in result.pages)
    assert result.unreadable_pages == [2]


@pytest.mark.parametrize("raw", [b"invalid pdf", None])
def test_invalid_or_entirely_blank_pdf_rejected(raw):
    if raw is None:
        import io

        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        output = io.BytesIO()
        writer.write(output)
        raw = output.getvalue()
    with pytest.raises(ImportInputError):
        extract_source(raw, "resume.pdf")


def test_raw_bytes_limit_inclusive_before_extraction(monkeypatch):
    import resume_agent.imports as module

    # Boundary bytes are checked before text length or PDF decoding.
    monkeypatch.setattr(module, "_extract_pdf", lambda raw: [("source", None)])
    assert extract_source(b"x" * (10 * 1024 * 1024), "resume.pdf").text == "source"
    with pytest.raises(ImportInputError, match="10 MiB"):
        extract_source(b"x" * (10 * 1024 * 1024 + 1), "resume.pdf")


def make_service(tmp_path, parser=candidate):
    from resume_agent.imports import ImportService
    from resume_agent.profile_store import ProfileStore
    from resume_agent.run_store import RunStore

    return ImportService(
        RunStore(tmp_path / "library.sqlite", tmp_path / "state.sqlite"),
        ProfileStore(tmp_path / "profile.yaml"),
        parser=lambda text: parser(),
    )


def accept_action(view, **updates):
    from resume_agent.contracts import AcceptImport

    values = dict(
        action_id="accept-1",
        review_id=view["pending"]["review_id"],
        draft_hash=view["pending"]["draft_hash"],
        expected_profile_revision=view["expected_profile_revision"],
        intentionally_blank_pages=view["source"]["unreadable_pages"],
    )
    values.update(updates)
    return AcceptImport(**values)


async def test_import_preserves_source_and_draft_across_reopen_and_requires_accept(tmp_path):
    service = make_service(tmp_path)
    created = service.create(b"Complete source for review", "resume.tex")
    assert not service.profiles.path.exists()
    assert created["draft"] is None
    service = make_service(tmp_path)
    review = await service.drive(created["id"])
    assert review["status"] == "pending_review"
    assert review["source"]["text"] == "Complete source for review"
    assert review["draft"] == candidate().model_dump(mode="json")
    assert service.read_source(created["id"]) == ("resume.tex", b"Complete source for review")
    assert not service.profiles.path.exists()
    service = make_service(tmp_path, lambda: pytest.fail("parser called twice"))
    reopened = service.get(created["id"])
    assert reopened["draft"] == review["draft"]
    result = await service.drive(created["id"], accept_action(reopened))
    assert result["status"] == "complete"
    assert service.profiles.load_snapshot().profile == candidate()
    assert not service.profiles.load_snapshot().review_required
    original = service.profiles.path.read_bytes()
    assert await make_service(tmp_path).drive(created["id"], accept_action(reopened)) == result
    assert service.profiles.path.read_bytes() == original


async def test_pdf_accept_requires_exact_blank_page_confirmation(tmp_path):
    from resume_agent.run_store import Conflict

    service = make_service(tmp_path)
    review = await service.drive(service.create(make_pdf(), "resume.pdf")["id"])
    for confirmations in ([], [1], [1, 2]):
        with pytest.raises(Conflict):
            await service.drive(
                review["id"], accept_action(review, intentionally_blank_pages=confirmations)
            )
        assert not service.profiles.path.exists()
    accepted = await service.drive(
        review["id"], accept_action(review, intentionally_blank_pages=[2])
    )
    assert accepted["status"] == "complete"
    assert service.profiles.load_snapshot().provenance["intentionally_blank_pages"] == [2]


async def test_stale_review_draft_or_profile_never_changes_yaml(tmp_path):
    from resume_agent.run_store import Conflict

    service = make_service(tmp_path)
    review = await service.drive(service.create(b"Source text", "resume.tex")["id"])
    for invalid in (
        {"review_id": "stale"},
        {"draft_hash": "a" * 64},
        {"expected_profile_revision": "b" * 64},
    ):
        with pytest.raises(Conflict):
            await service.drive(review["id"], accept_action(review, **invalid))
        assert not service.profiles.path.exists()
    service.profiles.save(None, candidate().model_copy(update={"summary": "Changed elsewhere"}), {})
    old = service.profiles.path.read_bytes()
    with pytest.raises(Conflict):
        await service.drive(review["id"], accept_action(review))
    assert service.profiles.path.read_bytes() == old


async def test_import_profile_revision_is_frozen_at_create(tmp_path):
    from resume_agent.run_store import Conflict

    service = make_service(tmp_path)
    created = service.create(b"Source text", "resume.tex")
    service.profiles.save(None, candidate(), {})
    review = await service.drive(created["id"])
    assert review["expected_profile_revision"] is None
    with pytest.raises(Conflict):
        await service.drive(review["id"], accept_action(review))


@pytest.mark.parametrize("output", ["raise", {}])
async def test_failed_or_invalid_parser_never_changes_profile(tmp_path, output):
    def parser():
        if output == "raise":
            raise RuntimeError("provider-secret-must-not-persist")
        return output

    service = make_service(tmp_path, parser)
    initial = service.profiles.save(None, candidate(), {})
    original = service.profiles.path.read_bytes()
    created = service.create(b"Source retained even on failure", "resume.tex")
    result = await service.drive(created["id"])
    assert result["status"] == "failed"
    assert result["diagnostics"] == [{"code": "driver_failed", "stage": "driver"}]
    assert "provider-secret" not in str(result)
    assert (
        make_service(tmp_path).get(created["id"])["source"]["text"]
        == "Source retained even on failure"
    )
    assert service.profiles.path.read_bytes() == original
    assert service.profiles.load_snapshot().revision == initial.revision


async def test_rejection_replays_and_retains_audit_source_and_draft(tmp_path):
    from resume_agent.contracts import RejectImport

    service = make_service(tmp_path)
    review = await service.drive(service.create(b"Review this source", "resume.tex")["id"])
    action = RejectImport(action_id="reject-1", review_id=review["pending"]["review_id"])
    result = await service.drive(review["id"], action)
    assert result["status"] == "cancelled"
    assert result["draft"] == candidate().model_dump(mode="json")
    assert result["source"]["text"] == "Review this source"
    reopened = make_service(tmp_path)
    assert await reopened.drive(review["id"], action) == result
    assert not service.profiles.path.exists()
    with service.operations.store.connection() as connection:
        row = connection.execute(
            "SELECT request_json,status FROM actions WHERE action_id='reject-1'"
        ).fetchone()
    assert '"kind":"reject_import"' in row[0]
    assert row[1] == "complete"


async def test_accept_without_completed_draft_review_is_rejected(tmp_path):
    from resume_agent.contracts import AcceptImport
    from resume_agent.run_store import Conflict

    service = make_service(tmp_path)
    created = service.create(b"Review this source", "resume.tex")
    with pytest.raises(Conflict):
        await service.drive(
            created["id"],
            AcceptImport(
                action_id="early",
                review_id="unknown",
                draft_hash="a" * 64,
                expected_profile_revision=None,
            ),
        )
    assert not service.profiles.path.exists()


async def test_accepted_profile_recovers_without_duplicate_save_after_interruption(
    tmp_path, monkeypatch
):
    import asyncio

    from resume_agent.contracts import Continue

    service = make_service(tmp_path)
    review = await service.drive(service.create(b"Review this source", "resume.tex")["id"])
    action = accept_action(review)
    original_save = service.profiles.save_reviewed

    def interrupt_after_save(*args, **kwargs):
        original_save(*args, **kwargs)
        raise asyncio.CancelledError()

    monkeypatch.setattr(service.profiles, "save_reviewed", interrupt_after_save)
    with pytest.raises(asyncio.CancelledError):
        await service.drive(review["id"], action)
    saved = service.profiles.path.read_bytes()
    reopened = make_service(tmp_path)
    assert reopened.get(review["id"])["status"] == "interrupted"
    result = await reopened.drive(review["id"], Continue(action_id="recover-1"))
    assert result["status"] == "complete"
    assert reopened.profiles.path.read_bytes() == saved
    assert await reopened.drive(review["id"], action) == result


async def test_action_id_payload_reuse_conflicts_across_reopen(tmp_path):
    from resume_agent.run_store import Conflict

    service = make_service(tmp_path)
    review = await service.drive(service.create(b"Source", "resume.tex")["id"])
    action = accept_action(review)
    await service.drive(review["id"], action)
    with pytest.raises(Conflict, match="action_payload_conflict"):
        await make_service(tmp_path).drive(
            review["id"], action.model_copy(update={"review_id": "other"})
        )


async def test_draft_checkpoint_mutation_does_not_approve_old_review(tmp_path):
    from resume_agent.checkpoint import read_v2_checkpoint, write_v2_checkpoint
    from resume_agent.run_store import Conflict

    service = make_service(tmp_path)
    review = await service.drive(service.create(b"Source", "resume.tex")["id"])
    path = service.operations.store.checkpoint_path
    envelope = read_v2_checkpoint(path, "operation", review["id"])
    envelope["values"]["draft"]["summary"] = "Unexpected edited facts"
    write_v2_checkpoint(path, "operation", review["id"], envelope)
    with pytest.raises(Conflict):
        await service.drive(review["id"], accept_action(review))
    assert not service.profiles.path.exists()


async def test_profile_save_race_returns_stable_conflict_and_preserves_winner(
    tmp_path, monkeypatch
):
    from resume_agent.run_store import Conflict

    service = make_service(tmp_path)
    review = await service.drive(service.create(b"Source", "resume.tex")["id"])
    original = service.profiles.save_reviewed

    def race(expected, draft, metadata):
        service.profiles.save(
            None, candidate().model_copy(update={"summary": "Other writer won"}), {}
        )
        return original(expected, draft, metadata)

    monkeypatch.setattr(service.profiles, "save_reviewed", race)
    with pytest.raises(Conflict, match="profile_conflict"):
        await service.drive(review["id"], accept_action(review))
    assert service.profiles.load_snapshot().profile.summary == "Other writer won"
    with pytest.raises(Conflict, match="profile_conflict"):
        await make_service(tmp_path).drive(review["id"], accept_action(review))

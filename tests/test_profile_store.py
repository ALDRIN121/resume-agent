"""Profile revisions and review provenance survive real file operations."""

import multiprocessing

import pytest
import yaml
from pydantic import ValidationError

from resume_agent.profile_store import ProfileConflictError, ProfileStore
from resume_agent.schemas import UserResume


def profile(name="Example Candidate"):
    return UserResume(personal={"full_name": name, "email": "candidate@example.invalid"})


def test_save_is_optimistic_and_reopen_preserves_revision(tmp_path):
    path = tmp_path / "profile.yaml"
    store = ProfileStore(path)
    assert store.load_snapshot() is None
    saved = store.save(None, profile(), {"source_sha256": "a" * 64})
    reopened = ProfileStore(path).load_snapshot()
    assert reopened.revision == saved.revision
    assert reopened.profile == profile()
    assert reopened.review_required  # parsing/source metadata is not human approval
    with pytest.raises(ProfileConflictError):
        store.save(None, profile("Other Candidate"), {})
    assert store.load_snapshot().profile == profile()


def test_explicit_review_binds_current_revision_and_manual_edits_require_review(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump({"personal": profile().personal.model_dump()}))
    store = ProfileStore(path)
    initial = store.load_snapshot()
    assert initial.review_required
    reviewed = store.review_current_profile(initial.revision)
    assert not reviewed.review_required
    document = yaml.safe_load(path.read_text())
    document["summary"] = "Manually changed facts"
    path.write_text(yaml.safe_dump(document))
    changed = store.load_snapshot()
    assert changed.revision != reviewed.revision
    assert changed.review_required
    with pytest.raises(ProfileConflictError):
        store.review_current_profile(initial.revision)
    assert store.review_current_profile(changed.revision).review_required is False


def test_revision_hash_includes_validated_defaults(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump({"personal": profile().personal.model_dump()}))
    minimal = ProfileStore(path).load_snapshot()
    path.write_text(yaml.safe_dump(profile().model_dump()))
    assert ProfileStore(path).load_snapshot().revision == minimal.revision


def test_invalid_profile_preserves_original(tmp_path):
    store = ProfileStore(tmp_path / "profile.yaml")
    first = store.save(None, profile(), {})
    original = store.path.read_bytes()
    with pytest.raises(ValidationError):
        store.save(first.revision, {"personal": {}}, {})
    assert store.path.read_bytes() == original


def test_replace_failure_preserves_yaml_and_unique_backups(tmp_path, monkeypatch):
    import resume_agent.profile_store as module

    store = ProfileStore(tmp_path / "profile.yaml")
    first = store.save(None, profile(), {})
    original = store.path.read_bytes()
    second = store.save(first.revision, profile("Second Candidate"), {})
    first_backup = next(tmp_path.glob("profile.yaml.*.bak"))
    assert first_backup.read_bytes() == original
    second_bytes = store.path.read_bytes()
    monkeypatch.setattr(module.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        store.save(second.revision, profile("Third Candidate"), {})
    assert store.path.read_bytes() == second_bytes
    assert first_backup.read_bytes() == original
    assert len(list(tmp_path.glob("profile.yaml.*.bak"))) == 2
    assert not list(tmp_path.glob("*.tmp"))


def _hold_lock(path, ready, release):
    from filelock import FileLock

    with FileLock(str(path) + ".lock"):
        ready.set()
        release.wait(10)


def test_profile_lock_is_process_independent(tmp_path):
    path = tmp_path / "profile.yaml"
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    process = context.Process(target=_hold_lock, args=(path, ready, release))
    process.start()
    try:
        assert ready.wait(10)
        with pytest.raises(ProfileConflictError):
            ProfileStore(path).save(None, profile(), {})
        assert not path.exists()
    finally:
        release.set()
        process.join(10)


def test_explicit_reviewed_save_is_atomic_and_cannot_bless_another_revision(tmp_path):
    store = ProfileStore(tmp_path / "profile.yaml")
    saved = store.save_reviewed(None, profile(), {"review_id": "review-1", "draft_hash": "a" * 64})
    assert not saved.review_required
    assert saved.provenance["review_id"] == "review-1"
    assert saved.provenance["reviewed_revision"] == saved.revision
    assert not ProfileStore(store.path).load_snapshot().review_required


@pytest.mark.parametrize("review", [False, True])
def test_lock_is_released_for_another_process_after_save_or_review(tmp_path, review):
    store = ProfileStore(tmp_path / "profile.yaml")
    saved = store.save(None, profile(), {})
    if review:
        store.review_current_profile(saved.revision)
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    process = context.Process(target=_hold_lock, args=(store.path, ready, release))
    process.start()
    try:
        assert ready.wait(10)
    finally:
        release.set()
        process.join(10)

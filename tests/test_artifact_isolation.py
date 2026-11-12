"""Real filesystem ownership and atomic export contracts."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest

from resume_agent import artifacts


def owned_pdf(tmp_path, marker=b"%PDF-A"):
    run = artifacts.RunArtifacts.create(str(uuid4()), tmp_path / "runs")
    attempt = run.attempt(1)
    attempt.pdf_path.write_bytes(marker)
    return run, attempt


def export_plan(tmp_path, marker=b"%PDF-A", company="Acme"):
    run, attempt = owned_pdf(tmp_path, marker)
    plan = artifacts.prepare_export(
        run.artifact_id,
        attempt.pdf_path,
        artifacts.hash_file(attempt.pdf_path),
        tmp_path / "output",
        company,
        "Jane Doe",
    )
    return plan


def test_owned_paths_and_immutable_copies(tmp_path):
    run, one = owned_pdf(tmp_path)
    two = run.attempt(2)
    assert one.pdf_path != two.pdf_path
    assert one.source_path == run.run_dir / "attempts/1/source.tex"
    assert artifacts.RunArtifacts.create(run.artifact_id, tmp_path / "runs") == run
    run.write_inputs({"company": "Acme"})
    run.write_inputs({"company": "Acme"})
    with pytest.raises(FileExistsError):
        run.write_inputs({"company": "Other"})
    one.write_manifest({"pdf_hash": artifacts.hash_file(one.pdf_path)})
    with pytest.raises(FileExistsError):
        one.write_manifest({"pdf_hash": "changed"})


@pytest.mark.parametrize(
    "value", ["../evil", "company", "", str(uuid4()).upper(), "{" + str(uuid4()) + "}"]
)
def test_rejects_noncanonical_ids(tmp_path, value):
    with pytest.raises(ValueError):
        artifacts.RunArtifacts.create(value, tmp_path)


@pytest.mark.parametrize("value", [True, False, 0, -1, "1", "../1", 1.1])
def test_rejects_invalid_attempts(tmp_path, value):
    run, _ = owned_pdf(tmp_path)
    with pytest.raises(ValueError):
        run.attempt(value)


def test_rejects_symlink_run_attempt_and_owned_files(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "runs"
    root.mkdir()
    artifact_id = str(uuid4())
    (root / artifact_id).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        artifacts.RunArtifacts.create(artifact_id, root)
    run = artifacts.RunArtifacts.create(str(uuid4()), root)
    (run.run_dir / "attempts/1").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        run.attempt(1)
    (run.run_dir / "inputs.json").symlink_to(outside / "stolen")
    with pytest.raises(ValueError):
        run.write_inputs({"secret": "source"})
    assert not (outside / "stolen").exists()


def test_plan_serializes_and_reserves_without_copy(tmp_path):
    plan = export_plan(tmp_path)
    assert artifacts.ExportPlan.from_dict(plan.to_dict()) == plan
    assert plan.destination.exists()
    assert not plan.temporary_path.exists()
    assert plan.canonical_pdf_path.is_absolute()
    assert plan.ownership_token
    assert plan.reservation_identity
    artifacts.prepare_copy(plan)
    assert plan.temporary_path.read_bytes() == b"%PDF-A"
    assert plan.destination.read_bytes() != b"%PDF-A"
    artifacts.commit_export(plan)
    assert artifacts.hash_file(plan.destination) == plan.expected_hash
    assert plan.canonical_pdf_path.read_bytes() == b"%PDF-A"
    # Recovery after rename is idempotent and retains ownership proof.
    artifacts.commit_export(artifacts.ExportPlan.from_dict(plan.to_dict()))


def test_ten_interleaved_same_company_exports_keep_hashes(tmp_path):
    with ThreadPoolExecutor(max_workers=10) as pool:
        plans = list(pool.map(lambda n: export_plan(tmp_path, f"%PDF-{n}".encode()), range(10)))
    assert len({p.destination for p in plans}) == 10
    assert len({p.canonical_pdf_path for p in plans}) == 10
    for plan in reversed(plans):
        artifacts.prepare_copy(plan)
    for plan in plans:
        artifacts.commit_export(plan)
        assert artifacts.hash_file(plan.destination) == plan.expected_hash


def test_copy_failure_and_cleanup_preserve_canonical(tmp_path, monkeypatch):
    plan = export_plan(tmp_path)

    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(artifacts.shutil, "copyfileobj", fail)
    with pytest.raises(OSError, match="disk full"):
        artifacts.prepare_copy(plan)
    assert plan.destination.read_bytes() != b"%PDF-A"
    artifacts.cleanup_export(plan)
    assert not plan.destination.exists()
    assert not plan.temporary_path.exists()
    assert plan.canonical_pdf_path.exists()


def test_hash_mismatch_never_exports(tmp_path):
    plan = export_plan(tmp_path)
    plan.canonical_pdf_path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash"):
        artifacts.prepare_copy(plan)
    assert not plan.temporary_path.exists()
    with pytest.raises(ValueError):
        artifacts.prepare_copy(replace(plan, artifact_id=str(uuid4())))


def test_recovery_reuses_owned_valid_temp_and_preserves_unexpected_bytes(tmp_path):
    plan = export_plan(tmp_path)
    artifacts.prepare_copy(plan)
    inode = plan.temporary_path.stat().st_ino
    artifacts.prepare_copy(plan, recover=True)
    assert plan.temporary_path.stat().st_ino == inode
    plan.temporary_path.unlink()
    plan.temporary_path.write_bytes(b"outsider")
    plan.destination.write_bytes(b"outsider too")
    with pytest.raises(ValueError):
        artifacts.commit_export(plan)
    artifacts.cleanup_export(plan)
    assert plan.destination.read_bytes() == b"outsider too"
    assert plan.temporary_path.read_bytes() == b"outsider"


def test_forged_plan_cannot_remove_unowned_files(tmp_path):
    plan = export_plan(tmp_path)
    artifacts.prepare_copy(plan)
    other = tmp_path / "unowned"
    other.write_bytes(b"keep")
    forged = replace(plan, temporary_path=other)
    with pytest.raises(ValueError):
        artifacts.cleanup_export(forged)
    assert other.read_bytes() == b"keep"


def test_export_rejects_symlink_company_directory(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    (output / "acme").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        export_plan(tmp_path)
    assert list(outside.iterdir()) == []


def test_owned_failed_copy_can_be_retried_explicitly(tmp_path, monkeypatch):
    plan = export_plan(tmp_path)
    real_copy = artifacts.shutil.copyfileobj

    def fail(source, target):
        target.write(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(artifacts.shutil, "copyfileobj", fail)
    with pytest.raises(OSError):
        artifacts.prepare_copy(plan)
    monkeypatch.setattr(artifacts.shutil, "copyfileobj", real_copy)
    artifacts.prepare_copy(plan, recover=True)
    artifacts.commit_export(plan)
    assert plan.destination.read_bytes() == b"%PDF-A"


def test_cleanup_after_rename_requires_explicit_cancel(tmp_path):
    plan = export_plan(tmp_path)
    artifacts.prepare_copy(plan)
    artifacts.commit_export(plan)
    artifacts.cleanup_export(plan, remove_export=True)
    assert not plan.destination.exists()
    assert plan.canonical_pdf_path.read_bytes() == b"%PDF-A"


def test_replaced_temp_hash_blocks_commit_without_exposing_pdf(tmp_path):
    plan = export_plan(tmp_path)
    artifacts.prepare_copy(plan)
    plan.temporary_path.write_bytes(b"different")
    with pytest.raises(ValueError, match="hash"):
        artifacts.commit_export(plan)
    assert plan.destination.read_bytes() != b"%PDF-A"
    artifacts.cleanup_export(plan)
    assert plan.temporary_path.read_bytes() == b"different"


def test_concurrent_reopen_of_same_owned_run(tmp_path):
    artifact_id = str(uuid4())
    with ThreadPoolExecutor(max_workers=10) as pool:
        runs = list(
            pool.map(lambda _: artifacts.RunArtifacts.create(artifact_id, tmp_path), range(30))
        )
    assert len({run.run_dir for run in runs}) == 1

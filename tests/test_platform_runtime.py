"""Actual process locking and native path export on each supported CI platform."""
from __future__ import annotations

import multiprocessing
from pathlib import Path
from uuid import uuid4

import pytest
from filelock import FileLock, Timeout

from resume_agent.artifacts import (
    RunArtifacts,
    cleanup_export,
    commit_export,
    hash_file,
    prepare_copy,
    prepare_export,
)


def _hold_native_lock(path, ready, release):
    with FileLock(path):
        ready.set()
        release.wait(15)


def test_separate_process_lock_excludes_then_releases(tmp_path):
    context = multiprocessing.get_context('spawn')
    ready, release = context.Event(), context.Event()
    lock = str(tmp_path / 'state with spaces — résumé.lock')
    child = context.Process(target=_hold_native_lock, args=(lock, ready, release))
    child.start()
    try:
        assert ready.wait(10), 'The child did not acquire its real OS lock'
        with pytest.raises(Timeout):
            FileLock(lock, timeout=0.05).acquire()
    finally:
        release.set()
        child.join(10)
        if child.is_alive():
            child.terminate()
            child.join(5)
    assert child.exitcode == 0
    with FileLock(lock, timeout=1):
        pass


def test_export_preserves_bytes_under_native_unicode_and_space_paths(tmp_path):
    root = tmp_path / 'state with spaces — résumé'
    artifact = RunArtifacts.create(str(uuid4()), root / 'runs')
    pdf = artifact.attempt(1).pdf_path
    pdf.write_bytes(b'%PDF-1.7\nnative filesystem byte identity\n%%EOF')
    plan = prepare_export(artifact.artifact_id, pdf, hash_file(pdf), root / 'exports',
                          'Example / Company', 'Casey Example')
    prepare_copy(plan)
    commit_export(plan)
    assert plan.destination.read_bytes() == pdf.read_bytes()
    assert plan.destination.resolve().is_relative_to((root / 'exports').resolve())
    assert hash_file(plan.destination) == plan.expected_hash


def test_export_ownership_uses_utf8_with_a_windows_default_encoding(tmp_path, monkeypatch):
    """Exercise real export files while reproducing Windows' non-UTF-8 default."""
    native_read_text = Path.read_text

    def read_text(path, encoding=None, errors=None):
        return native_read_text(path, encoding=encoding or 'cp1252', errors=errors)

    monkeypatch.setattr(Path, 'read_text', read_text)
    root = tmp_path / 'state with spaces — résumé'
    artifact = RunArtifacts.create(str(uuid4()), root / 'runs')
    pdf = artifact.attempt(1).pdf_path
    expected = b'%PDF-1.7\nUTF-8 ownership across export and cleanup\n%%EOF'
    pdf.write_bytes(expected)
    plan = prepare_export(artifact.artifact_id, pdf, hash_file(pdf), root / 'exports',
                          'Example Company', 'Casey Example')

    prepare_copy(plan)
    commit_export(plan)
    commit_export(plan)  # Recovery after rename reads the same UTF-8 record.
    cleanup_export(plan)

    assert plan.destination.read_bytes() == expected
    assert pdf.read_bytes() == expected
    assert not plan.ownership_path.exists()

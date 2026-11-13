"""Actual process locking and native path export on each supported CI platform."""
from __future__ import annotations

import multiprocessing
from uuid import uuid4

import pytest
from filelock import FileLock, Timeout

from resume_agent.artifacts import (
    RunArtifacts,
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

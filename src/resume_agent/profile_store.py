"""Validated candidate facts with optimistic, atomic, process-safe writes."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from filelock import FileLock, Timeout

from .config import BASE_RESUME_FILE
from .contracts import content_hash, utc_now
from .schemas import UserResume


class ProfileConflictError(RuntimeError):
    code = "profile_conflict"


@dataclass(frozen=True)
class ProfileSnapshot:
    profile: UserResume
    revision: str
    provenance: dict[str, Any] | None
    review_required: bool


class ProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else BASE_RESUME_FILE

    def load_snapshot(self) -> ProfileSnapshot | None:
        if not self.path.exists():
            return None
        document = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        profile = UserResume.model_validate(document)
        revision = content_hash(profile)
        metadata = document.get("_resume_agent")
        provenance = metadata if isinstance(metadata, dict) else None
        reviewed = bool(
            provenance
            and provenance.get("profile_revision") == revision
            and provenance.get("reviewed_revision") == revision
        )
        return ProfileSnapshot(profile, revision, provenance, not reviewed)

    def save(
        self,
        expected_revision: str | None,
        profile: UserResume | dict,
        source_metadata: dict[str, Any],
    ) -> ProfileSnapshot:
        return self._save(expected_revision, profile, source_metadata, reviewed=False)

    def save_reviewed(
        self,
        expected_revision: str | None,
        profile: UserResume | dict,
        source_metadata: dict[str, Any],
    ) -> ProfileSnapshot:
        """Persist a human-accepted draft and its review provenance in one replacement."""
        return self._save(expected_revision, profile, source_metadata, reviewed=True)

    def _save(self, expected_revision, profile, source_metadata, *, reviewed):
        profile = UserResume.model_validate(profile)
        revision = content_hash(profile)
        metadata = dict(source_metadata)
        metadata.pop("reviewed_revision", None)
        metadata["profile_revision"] = revision
        if reviewed:
            metadata.update(reviewed_revision=revision, reviewed_at=utc_now())
        with self._lock():
            self._check_revision(expected_revision)
            self._replace(profile, metadata)
            return self.load_snapshot()

    def review_current_profile(self, expected_revision: str) -> ProfileSnapshot:
        with self._lock():
            current = self._check_revision(expected_revision)
            if current is None:
                raise ProfileConflictError("No current profile to review")
            metadata = dict(current.provenance or {})
            metadata.update(
                profile_revision=current.revision,
                reviewed_revision=current.revision,
                reviewed_at=utc_now(),
            )
            self._replace(current.profile, metadata)
            return self.load_snapshot()

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(self.path) + ".lock", timeout=0)
        try:
            lock.acquire()
        except Timeout as exc:
            raise ProfileConflictError("Profile is being changed by another process") from exc
        try:
            yield
        finally:
            lock.release()

    def _check_revision(self, expected: str | None) -> ProfileSnapshot | None:
        current = self.load_snapshot()
        if (current.revision if current else None) != expected:
            raise ProfileConflictError("Profile revision changed; review the current profile")
        return current

    def _replace(self, profile: UserResume, metadata: dict[str, Any]) -> None:
        document = profile.model_dump(mode="json") | {"_resume_agent": metadata}
        encoded = yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if self.path.exists():
                backup = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.bak")
                with self.path.open("rb") as source, backup.open("xb") as target:
                    shutil.copyfileobj(source, target)
                    target.flush()
                    os.fsync(target.fileno())
            os.replace(temporary, self.path)
            temporary = None
            if os.name != "nt":
                directory_fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

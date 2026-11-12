"""Run-owned artifacts and recoverable, hash-verified atomic exports.

These helpers never declare a run released. The release service persists an
ExportPlan before prepare_copy, then calls commit_export in its transaction.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

from .config import CONFIG_DIR
from .tools.fs import build_output_path


def _uuid(value: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("artifact_id must be a canonical UUID") from exc
    return value


def _safe(path: Path) -> Path:
    """Reject symlinks at or below an explicitly chosen resolved root."""
    if path.is_symlink():
        raise ValueError(f"Unexpected symlink: {path}")
    return path


def _directory(path: Path) -> Path:
    _safe(path)
    path.mkdir(exist_ok=True)
    if not path.is_dir():
        raise ValueError(f"Expected directory: {path}")
    return path


def _open(path: Path, flags: int):
    _safe(path)
    return os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), 0o600)


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _immutable(path: Path, value: dict) -> None:
    _safe(path)
    data = _json_bytes(value)
    staging = path.with_name(f".{path.name}.{uuid4()}.new")
    fd = _open(staging, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Readers see complete immutable bytes, including concurrent reopen.
            os.link(staging, path, follow_symlinks=False)
        except FileExistsError:
            _safe(path)
            if path.read_bytes() != data:
                raise FileExistsError(f"Immutable artifact already exists: {path}") from None
    finally:
        staging.unlink()


def hash_file(path: str | Path) -> str:
    """Return SHA-256 of a regular file without following a final symlink."""
    with os.fdopen(_open(Path(path), os.O_RDONLY), "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Artifact must be a regular file")
        return hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass(frozen=True)
class AttemptArtifacts:
    run: RunArtifacts
    number: int
    attempt_dir: Path
    source_path: Path
    log_path: Path
    pdf_path: Path
    images_dir: Path
    manifest_path: Path

    def write_manifest(self, manifest: dict) -> None:
        self.run.attempt(self.number)
        _immutable(self.manifest_path, manifest)


@dataclass(frozen=True)
class RunArtifacts:
    artifact_id: str
    root: Path
    run_dir: Path
    inputs_path: Path
    manifest_path: Path

    @classmethod
    def create(cls, artifact_id: str, root: Path | None = None) -> RunArtifacts:
        artifact_id = _uuid(artifact_id)
        root = Path(root) if root is not None else CONFIG_DIR / "runs"
        _safe(root)
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve()
        run_dir = _directory(root / artifact_id)
        manifest_path = run_dir / "manifest.json"
        _immutable(manifest_path, {"artifact_id": artifact_id})
        _directory(run_dir / "attempts")
        return cls(artifact_id, root, run_dir, run_dir / "inputs.json", manifest_path)

    def attempt(self, number: int) -> AttemptArtifacts:
        if type(number) is not int or number < 1:
            raise ValueError("Attempt number must be a positive integer")
        _safe(self.run_dir)
        attempts = _directory(self.run_dir / "attempts")
        folder = _directory(attempts / str(number))
        paths = [
            folder / name
            for name in ("source.tex", "tectonic_raw.log", "resume.pdf", "manifest.json")
        ]
        for path in paths:
            _safe(path)
        images = _directory(folder / "images")
        return AttemptArtifacts(
            self, number, folder, paths[0], paths[1], paths[2], images, paths[3]
        )

    def write_inputs(self, inputs: dict) -> None:
        _safe(self.run_dir)
        _immutable(self.inputs_path, inputs)


def _identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Expected regular file: {path}")
    return info.st_dev, info.st_ino


@dataclass(frozen=True)
class ExportPlan:
    artifact_id: str
    canonical_pdf_path: Path
    expected_hash: str
    destination: Path
    temporary_path: Path
    ownership_token: str
    reservation_identity: tuple[int, int]

    @property
    def ownership_path(self) -> Path:
        return self.destination.with_name(
            f".{self.destination.name}.{self.ownership_token}.owner.json"
        )

    def to_dict(self) -> dict:
        result = asdict(self)
        for field in ("canonical_pdf_path", "destination", "temporary_path"):
            result[field] = str(result[field])
        result["reservation_identity"] = list(self.reservation_identity)
        return result

    @classmethod
    def from_dict(cls, value: dict) -> ExportPlan:
        fields = dict(value)
        for field in ("canonical_pdf_path", "destination", "temporary_path"):
            fields[field] = Path(fields[field])
        fields["reservation_identity"] = tuple(fields["reservation_identity"])
        plan = cls(**fields)
        _validate_plan(plan)
        return plan


def _validate_plan(plan: ExportPlan) -> None:
    _uuid(plan.artifact_id)
    _uuid(plan.ownership_token)
    if not re.fullmatch(r"[0-9a-f]{64}", plan.expected_hash):
        raise ValueError("Invalid expected PDF hash")
    for path in (plan.canonical_pdf_path, plan.destination, plan.temporary_path):
        if not path.is_absolute() or path != path.parent.resolve() / path.name:
            raise ValueError("Export paths must be absolute without symlink parents")
        _safe(path)
    if plan.temporary_path != plan.destination.with_name(
        f".{plan.destination.name}.{plan.ownership_token}.tmp"
    ):
        raise ValueError("Temporary path does not match export ownership")
    # Canonical PDFs must belong to this UUID's numbered attempt directory.
    pdf = plan.canonical_pdf_path
    if (
        pdf.name != "resume.pdf"
        or not pdf.parent.name.isdecimal()
        or int(pdf.parent.name) < 1
        or pdf.parent.parent.name != "attempts"
        or pdf.parent.parent.parent.name != plan.artifact_id
    ):
        raise ValueError("Canonical PDF does not belong to artifact UUID")
    if plan.destination == pdf or plan.temporary_path == pdf:
        raise ValueError("Export cannot replace canonical PDF")


def _reservation_bytes(plan: ExportPlan) -> bytes:
    return _json_bytes({"artifact_id": plan.artifact_id, "ownership_token": plan.ownership_token})


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return  # Windows cannot open directories for fsync; files are flushed.
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_owner(plan: ExportPlan, owner: dict, *, initial: bool = False) -> None:
    if initial:
        _immutable(plan.ownership_path, owner)
    else:
        # The sidecar is owned; an exclusive sibling makes updates crash-safe.
        staging = plan.ownership_path.with_name(plan.ownership_path.name + "." + str(uuid4()))
        _immutable(staging, owner)
        os.replace(staging, plan.ownership_path)
    _sync_directory(plan.destination.parent)


def _owner(plan: ExportPlan) -> dict:
    _validate_plan(plan)
    _safe(plan.ownership_path)
    try:
        owner = json.loads(plan.ownership_path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("Missing or invalid export ownership") from exc
    if owner.get("plan") != plan.to_dict():
        raise ValueError("Export ownership does not match plan")
    return owner


def _matches(path: Path, identity, expected_hash: str) -> bool:
    try:
        return _identity(path) == tuple(identity) and hash_file(path) == expected_hash
    except (OSError, ValueError):
        return False


def _reservation_matches(plan: ExportPlan) -> bool:
    return _matches(
        plan.destination,
        plan.reservation_identity,
        hashlib.sha256(_reservation_bytes(plan)).hexdigest(),
    )


def prepare_export(
    artifact_id: str,
    canonical_pdf_path: str | Path,
    expected_hash: str,
    base_dir: Path,
    company_name: str,
    user_full_name: str,
    *,
    today: date | None = None,
) -> ExportPlan:
    """Reserve a friendly filename and persist ownership WITHOUT copying bytes."""
    artifact_id = _uuid(artifact_id)
    source = Path(canonical_pdf_path).absolute()
    if hash_file(source) != expected_hash:
        raise ValueError("Canonical PDF hash mismatch")
    _safe(base_dir)
    base_dir = base_dir.resolve()
    destination = build_output_path(base_dir, company_name, user_full_name, today=today)
    token = str(uuid4())
    plan = ExportPlan(
        artifact_id,
        source,
        expected_hash,
        destination,
        destination.with_name(f".{destination.name}.{token}.tmp"),
        token,
        _identity(destination),
    )
    try:
        _validate_plan(plan)
        with os.fdopen(_open(destination, os.O_WRONLY), "wb") as stream:
            stream.write(_reservation_bytes(plan))
            stream.flush()
            os.fsync(stream.fileno())
        _write_owner(plan, {"plan": plan.to_dict()}, initial=True)
    except BaseException:
        # This function owns the newly reserved inode, even before a plan exists.
        if _identity(destination) == plan.reservation_identity:
            destination.unlink()
        raise
    return plan


def prepare_copy(plan: ExportPlan, *, recover: bool = False) -> Path:
    """Exclusively prepare and fsync a verified temp, or explicitly recover it."""
    owner = _owner(plan)
    if hash_file(plan.canonical_pdf_path) != plan.expected_hash:
        raise ValueError("Canonical PDF hash mismatch")
    if not _reservation_matches(plan):
        raise ValueError("Export reservation ownership mismatch")
    if plan.temporary_path.exists():
        if (
            recover
            and owner.get("temporary_identity")
            and _matches(plan.temporary_path, owner["temporary_identity"], plan.expected_hash)
        ):
            return plan.temporary_path
        if (
            recover
            and owner.get("temporary_identity")
            and _matches(plan.temporary_path, owner["temporary_identity"], owner["temporary_hash"])
        ):
            plan.temporary_path.unlink()  # owned partial copy, explicit continuation
        else:
            raise ValueError("Unexpected or unverified temporary file")
    fd = _open(plan.temporary_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    owner["temporary_identity"] = list(_identity(plan.temporary_path))
    owner["temporary_hash"] = hashlib.sha256(b"").hexdigest()
    try:
        _write_owner(plan, owner)
        with os.fdopen(fd, "wb") as target:
            fd = -1
            with os.fdopen(_open(plan.canonical_pdf_path, os.O_RDONLY), "rb") as source:
                shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
        if (
            hash_file(plan.canonical_pdf_path) != plan.expected_hash
            or hash_file(plan.temporary_path) != plan.expected_hash
        ):
            raise ValueError("PDF hash mismatch during copy")
        owner["temporary_hash"] = plan.expected_hash
        _write_owner(plan, owner)
    except BaseException:
        if fd != -1:
            os.close(fd)
        # Record the partial owned bytes so cleanup cannot erase later changes.
        if _identity(plan.temporary_path) == tuple(owner["temporary_identity"]):
            owner["temporary_hash"] = hash_file(plan.temporary_path)
            _write_owner(plan, owner)
        raise
    return plan.temporary_path


def commit_export(plan: ExportPlan) -> Path:
    """Atomically replace this reservation; caller owns release transaction."""
    owner = _owner(plan)
    identity = owner.get("temporary_identity")
    if hash_file(plan.canonical_pdf_path) != plan.expected_hash or not identity:
        raise ValueError("Canonical hash or prepared copy missing")
    if _matches(plan.destination, identity, plan.expected_hash):
        return plan.destination  # crash after rename, before DB commit
    if not _reservation_matches(plan):
        raise ValueError("Export reservation ownership mismatch")
    if not _matches(plan.temporary_path, identity, plan.expected_hash):
        raise ValueError("Temporary PDF ownership or hash mismatch")
    os.replace(plan.temporary_path, plan.destination)
    _sync_directory(plan.destination.parent)
    # Keep sidecar: recovery can prove destination ownership after rename.
    return plan.destination


def cleanup_export(plan: ExportPlan, *, remove_export: bool = False) -> None:
    """Remove matching owned files only; never remove the canonical PDF.

    After a durable release, default cleanup removes the sidecar but retains the
    exported PDF. Cancellation recovery may explicitly remove_export before the
    release record commits. Unexpected replacements are always preserved.
    """
    owner = _owner(plan)
    identity = owner.get("temporary_identity")
    if identity and _matches(plan.temporary_path, identity, owner["temporary_hash"]):
        plan.temporary_path.unlink()
    if _reservation_matches(plan) or (
        remove_export and identity and _matches(plan.destination, identity, plan.expected_hash)
    ):
        plan.destination.unlink()
    plan.ownership_path.unlink()
    _sync_directory(plan.destination.parent)

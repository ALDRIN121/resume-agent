"""Version check and self-update via GitHub API + git pull."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Optional

GITHUB_REPO = "ALDRIN121/resume-agent"
_CACHE_FILE_NAME = ".update_cache.json"
_CACHE_TTL = 24 * 3600  # 24 hours


def _cache_file() -> Path:
    from .config import CONFIG_DIR
    return CONFIG_DIR / _CACHE_FILE_NAME


def _find_repo_root() -> Optional[Path]:
    """
    Find the git repo root.

    Priority:
    1. RESUME_GENERATOR_DIR env var (honoured by both install scripts).
    2. Standard install locations written by install.sh / install.ps1.
    3. Walk up from __file__ (editable / dev installs where the package IS the repo).
    """
    import os
    import platform as _platform

    env_dir = os.environ.get("RESUME_GENERATOR_DIR")
    if env_dir:
        p = Path(env_dir)
        if (p / ".git").exists():
            return p

    if _platform.system() == "Windows":
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            p = Path(local_app) / "resume-generator"
            if (p / ".git").exists():
                return p
    else:
        p = Path.home() / ".local" / "share" / "resume-generator"
        if (p / ".git").exists():
            return p

    # Fallback: walk up from __file__ for dev / editable installs
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent

    return None


def _get_local_sha() -> Optional[str]:
    repo = _find_repo_root()
    if not repo:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=repo,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _get_cached_remote_sha() -> Optional[str]:
    f = _cache_file()
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - data.get("ts", 0) < _CACHE_TTL:
            return data.get("sha")
    except Exception:
        pass
    return None


def _save_remote_sha(sha: str) -> None:
    f = _cache_file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            json.dumps({"sha": sha, "ts": time.time()}),
            encoding="utf-8",
        )
    except Exception:
        pass


def _fetch_remote_sha() -> Optional[str]:
    """Query GitHub API for the latest commit SHA on main."""
    try:
        import httpx
        resp = httpx.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/commits/main",
            headers={"Accept": "application/vnd.github.sha"},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.text.strip()
    except Exception:
        pass
    return None


def check_for_update() -> Optional[str]:
    """
    Non-blocking startup check.
    Returns a hint string if an update is available, None if up-to-date or check failed.
    Network is only hit once per 24 hours (cached in CONFIG_DIR).
    """
    local = _get_local_sha()
    if not local:
        return None

    remote = _get_cached_remote_sha()
    if remote is None:
        remote = _fetch_remote_sha()
        if remote:
            _save_remote_sha(remote)

    if remote and remote != local:
        return "A new version is available. Run: [bold]resume-generator update[/bold]"
    return None


def perform_update(repo: Path) -> tuple[bool, str, str]:
    """
    Pull latest changes from GitHub and re-install via uv.
    Returns (success, error_hint, captured_output).
    error_hint is "" on success or "windows_locked" for the Windows file-lock case.
    """
    r1 = subprocess.run(
        ["git", "-C", str(repo), "pull"],
        check=False,
        capture_output=True,
        text=True,
    )
    # Echo git pull output so the user sees "Already up to date." etc.
    if r1.stdout:
        print(r1.stdout, end="", flush=True)
    if r1.stderr:
        print(r1.stderr, end="", flush=True)

    if r1.returncode != 0:
        return False, "", (r1.stderr + r1.stdout).strip()

    uv = _find_uv()
    cmd = [uv, "tool", "install", ".", "--force"] if uv else ["uv", "sync"]
    r2 = subprocess.run(cmd, cwd=repo, check=False, capture_output=True, text=True)
    if r2.returncode == 0:
        return True, "", ""

    combined = ((r2.stderr or "") + (r2.stdout or "")).strip()
    low = combined.lower()
    # Windows can't overwrite a running executable — os error 5 (access denied)
    # or os error 32 (file in use by another process)
    if (
        "access is denied" in low
        or "os error 5" in low
        or "os error 32" in low
        or "being used by another process" in low
        or "cannot access the file" in low
    ):
        return False, "windows_locked", combined
    return False, "", combined


def _find_uv() -> Optional[str]:
    import shutil as _sh
    return _sh.which("uv")

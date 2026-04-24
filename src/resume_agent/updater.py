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
    """Walk up from this file to find the nearest .git directory."""
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


def perform_update() -> bool:
    """
    Pull latest changes from GitHub and re-install via uv.
    Returns True on success.
    """
    repo = _find_repo_root()
    if not repo:
        return False

    r1 = subprocess.run(["git", "-C", str(repo), "pull"], check=False)
    if r1.returncode != 0:
        return False

    uv = _find_uv()
    if uv:
        r2 = subprocess.run([uv, "tool", "install", ".", "--force"], cwd=repo, check=False)
        return r2.returncode == 0

    r2 = subprocess.run(["uv", "sync"], cwd=repo, check=False)
    return r2.returncode == 0


def _find_uv() -> Optional[str]:
    import shutil as _sh
    return _sh.which("uv")

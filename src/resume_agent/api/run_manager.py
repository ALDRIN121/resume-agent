"""Compatibility names for the shared durable run facade.

New generation uses RunService; no in-memory session or JSONL owns run state.
"""
from __future__ import annotations

from ..config import CONFIG_DIR
from .v2_manager import V2RunManager

_HISTORY_FILE = CONFIG_DIR / "run_history.jsonl"  # legacy inspection/migration location


class RunManager(V2RunManager):
    def __init__(self, services=None):
        if services is None:
            from ..runtime import Runtime
            services = Runtime()
        super().__init__(services)


def run_summary(run: dict) -> dict:
    return dict(run)


def run_detail(run: dict) -> dict:
    return dict(run)

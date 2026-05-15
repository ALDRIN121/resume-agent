"""
Prompt snapshot tests (Phase 6.4).

These tests guard against accidental edits to the large prompt blocks during
refactors. On first run they write the snapshot; on subsequent runs they assert
the prompt hasn't changed.

Usage:
  Update snapshots:  pytest tests/test_prompts.py --snapshot-update
  Normal run:        pytest tests/test_prompts.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "prompts"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _check_or_write(name: str, content: str, *, update: bool = False) -> None:
    """Write snapshot on first run; assert match on subsequent runs."""
    path = SNAPSHOT_DIR / f"{name}.txt"
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    if update or not path.exists():
        path.write_text(content, encoding="utf-8")
        return

    expected = path.read_text(encoding="utf-8")
    assert content == expected, (
        f"Prompt '{name}' changed! Expected hash {_hash(expected)}, "
        f"got {_hash(content)}.\n"
        "If this is intentional, run: pytest tests/test_prompts.py --snapshot-update\n"
        "Diff (first 500 chars):\n"
        + _diff_head(expected, content)
    )


def _diff_head(expected: str, actual: str, chars: int = 500) -> str:
    for i, (a, b) in enumerate(zip(expected, actual)):
        if a != b:
            start = max(0, i - 50)
            return (
                f"First difference at char {i}:\n"
                f"  expected: ...{repr(expected[start:start + chars])}...\n"
                f"  actual:   ...{repr(actual[start:start + chars])}..."
            )
    return f"Content differs in length: expected {len(expected)}, got {len(actual)}"


def _is_update_mode() -> bool:
    import sys
    return "--snapshot-update" in sys.argv


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_polish_system_prompt_snapshot():
    from resume_agent.agents.resume_generator import _POLISH_SYSTEM

    _check_or_write("polish_system", _POLISH_SYSTEM, update=_is_update_mode())


def test_fix_system_prompt_snapshot():
    from resume_agent.agents.resume_generator import _FIX_SYSTEM

    _check_or_write("fix_system", _FIX_SYSTEM, update=_is_update_mode())


def test_gap_analyzer_system_prompt_snapshot():
    from resume_agent.agents.gap_analyzer import _SYSTEM as GAP_SYSTEM

    _check_or_write("gap_analyzer_system", GAP_SYSTEM, update=_is_update_mode())


def test_pdf_validator_system_prompt_snapshot():
    from resume_agent.agents.pdf_validator import _SYSTEM as PDF_VAL_SYSTEM

    _check_or_write("pdf_validator_system", PDF_VAL_SYSTEM, update=_is_update_mode())


def test_hr_review_system_prompt_snapshot():
    from resume_agent.agents.hr_review import _SYSTEM as HR_SYSTEM

    _check_or_write("hr_review_system", HR_SYSTEM, update=_is_update_mode())


def test_polish_prompt_contains_metric_discipline():
    from resume_agent.agents.resume_generator import _POLISH_SYSTEM

    assert "METRIC DISCIPLINE" in _POLISH_SYSTEM
    assert "40-60%" in _POLISH_SYSTEM or "40–60%" in _POLISH_SYSTEM


def test_polish_prompt_contains_tense_rules():
    from resume_agent.agents.resume_generator import _POLISH_SYSTEM

    assert "TENSE CONSISTENCY" in _POLISH_SYSTEM
    assert "Present" in _POLISH_SYSTEM


def test_polish_prompt_contains_action_verb_rule():
    from resume_agent.agents.resume_generator import _POLISH_SYSTEM

    assert "ACTION-VERB RULE" in _POLISH_SYSTEM
    assert "Worked on" in _POLISH_SYSTEM


def test_polish_prompt_contains_apostrophe_rule():
    from resume_agent.agents.resume_generator import _POLISH_SYSTEM

    assert "APOSTROPHES" in _POLISH_SYSTEM


def test_gap_analyzer_prompt_contains_credibility_guard():
    from resume_agent.agents.gap_analyzer import _SYSTEM

    assert "CREDIBILITY GUARD" in _SYSTEM
    assert "soften attribution" in _SYSTEM.lower()


def test_pdf_validator_prompt_contains_f_and_g():
    from resume_agent.agents.pdf_validator import _SYSTEM

    assert "F. Page balance" in _SYSTEM
    assert "G. Metric overload" in _SYSTEM

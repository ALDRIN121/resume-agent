"""
Deterministic eval harness for resume fixture quality.

Run with:
    uv run python -m evals

Loads every JSON fixture from evals/fixtures/, runs the deterministic lint
checks (no LLM calls), and prints a summary table.  Exit code 0 = all fixtures
pass lint; non-zero = at least one hard failure.

Flags:
    --verbose / -v   Print per-fixture issue detail
    --fixture <name> Evaluate only the named fixture (without .json)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_COL_W = 16  # column width for fixture name


def _load_fixture(path: Path):
    from resume_agent.schemas import UserResume
    data = json.loads(path.read_text(encoding="utf-8"))
    return UserResume.model_validate(data)


def _run_lint(resume):
    from resume_agent.tools.resume_lint import lint_resume
    return lint_resume(resume)


def _score(result) -> tuple[int, int]:
    """Return (fail_count, warn_count)."""
    fails = sum(1 for i in result.issues if i.severity == "fail")
    warns = sum(1 for i in result.issues if i.severity == "warn")
    return fails, warns


def _status_icon(fails: int, warns: int) -> str:
    if fails:
        return "FAIL"
    if warns:
        return "WARN"
    return "PASS"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resume eval harness")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--fixture", "-f", default=None,
                        help="Evaluate only this fixture (name without .json)")
    args = parser.parse_args(argv)

    if args.fixture:
        paths = [_FIXTURES_DIR / f"{args.fixture}.json"]
        missing = [p for p in paths if not p.exists()]
        if missing:
            print(f"error: fixture not found: {missing[0]}", file=sys.stderr)
            return 2
    else:
        paths = sorted(_FIXTURES_DIR.glob("*.json"))
        if not paths:
            print(f"No fixtures found in {_FIXTURES_DIR}", file=sys.stderr)
            return 2

    header = f"{'Fixture':<{_COL_W}}  {'Status':<6}  {'Fails':>5}  {'Warns':>5}  Issues"
    print(header)
    print("-" * len(header))

    any_hard_failure = False

    for path in paths:
        name = path.stem
        try:
            resume = _load_fixture(path)
        except Exception as exc:
            print(f"{name:<{_COL_W}}  {'ERROR':<6}  {'—':>5}  {'—':>5}  {exc}")
            any_hard_failure = True
            continue

        result = _run_lint(resume)
        fails, warns = _score(result)
        status = _status_icon(fails, warns)
        issue_summary = f"{len(result.issues)} issue(s)" if result.issues else "clean"

        print(f"{name:<{_COL_W}}  {status:<6}  {fails:>5}  {warns:>5}  {issue_summary}")

        if args.verbose and result.issues:
            for issue in result.issues:
                prefix = "  [FAIL]" if issue.severity == "fail" else "  [WARN]"
                print(f"{prefix} {issue.code}: {issue.message}")

        if fails:
            any_hard_failure = True

    print()
    if any_hard_failure:
        print("Result: FAIL — one or more fixtures have hard lint failures.")
        return 1

    print("Result: PASS — all fixtures clear hard lint checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

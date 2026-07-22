"""
HR Review agent node — optional pre-flight check after generation, before saving.

Scores the final LaTeX against ATS/recruiter heuristics and feeds issues back into
the validation_feedback if any score falls below threshold.

Enabled by default; disable with enable_hr_review=false in config.yaml.
"""

from __future__ import annotations

from typing import cast

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..config import ResumeAgentSettings
from ..llm import get_chat_model
from ..state import ResumeGenState
from ..ui.panels import print_agent_step, print_info, print_warning

# ── Result schema ──────────────────────────────────────────────────────────────

class HRReviewScore(BaseModel):
    name: str               # score name
    score: float            # 0.0 – 1.0 (1.0 = best)
    note: str | None = None  # brief explanation when below threshold


class HRReviewResult(BaseModel):
    metric_density_ok: bool = True
    buzzword_density_ok: bool = True
    action_verb_coverage_ok: bool = True
    tense_consistency_ok: bool = True
    overall_pass: bool = True
    scores: list[HRReviewScore] = Field(default_factory=list)
    feedback: str | None = None  # combined feedback for generator retry


# ── Prompts ────────────────────────────────────────────────────────────────────

_SYSTEM = """\
You are an expert HR professional and ATS consultant reviewing a completed resume.

Evaluate the supplied LaTeX resume source against these five criteria. For each
criterion, provide a score from 0.0 to 1.0 and a brief note if the score is below
0.7. Score 1.0 = excellent, 0.0 = critically poor.

CRITERIA:

1. METRIC DENSITY (name: "metric_density")
   Ideal: 40–60% of experience/project bullets contain one numeric metric.
   < 0.3: too few metrics (vague).  > 0.7: too many metrics (looks fabricated).
   Score 1.0 when density is in the 0.4–0.6 range; scale down towards extremes.

2. BUZZWORD DENSITY (name: "buzzword_density")
   Count use of generic filler words in the summary and bullets: synergy, leverage,
   utilize, passionate, results-driven, innovative, dynamic, thought leader, etc.
   Score 1.0 when there are zero buzzwords; scale down for each one found.

3. ACTION VERB COVERAGE (name: "action_verb_coverage")
   What fraction of bullets start with a strong action verb?
   Score 1.0 when all bullets start with a strong verb; penalise "Worked on",
   "Helped", "Was responsible for", "Participated in", "Involved in".

4. TENSE CONSISTENCY (name: "tense_consistency")
   Current roles (no end date / "Present") should use present tense.
   Past roles should use simple past. Score 1.0 if fully consistent.

5. TITLE-TO-TENURE PLAUSIBILITY (name: "title_plausibility")
   Are the claimed outcomes plausible given the title and tenure?
   Flag obvious mismatches (e.g. 6-month intern "led company-wide transformation").
   Score 1.0 if everything is plausible; penalise each mismatch.

RESPONSE FORMAT — respond ONLY with a JSON object matching this schema:
{
  "metric_density_ok": true|false,
  "buzzword_density_ok": true|false,
  "action_verb_coverage_ok": true|false,
  "tense_consistency_ok": true|false,
  "overall_pass": true|false,
  "scores": [
    {"name": "metric_density", "score": 0.85, "note": null},
    {"name": "buzzword_density", "score": 0.60, "note": "Found: leverage, innovative"},
    ...
  ],
  "feedback": "Optional one-paragraph summary of improvements needed, or null if overall_pass=true."
}

Set *_ok to false when the corresponding score is below 0.6.
Set overall_pass to false when 2 or more criteria score below 0.6.
"""

_HUMAN = """\
Please evaluate the following LaTeX resume source:

```latex
{latex_source}
```
"""

# Minimum number of criteria failures before we flag feedback for retry
_MIN_FAILURES_FOR_RETRY = 2


def hr_review_node(
    state: ResumeGenState, *, settings: ResumeAgentSettings | None = None
) -> dict:
    """
    Run an LLM-based HR pre-flight check on the generated LaTeX.

    Returns updated validation_feedback when overall_pass=False and at least
    _MIN_FAILURES_FOR_RETRY criteria fail. Otherwise returns no changes.
    """
    settings = settings or ResumeAgentSettings.load()

    latex_source = state.get("latex_source", "")
    if not latex_source:
        return {}

    print_agent_step("HR Review", "Running ATS/recruiter quality pre-flight check…")

    llm = get_chat_model(settings, task="structured", temperature=0.0)
    structured_llm = llm.with_structured_output(HRReviewResult)

    messages = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=_HUMAN.format(latex_source=latex_source[:8000])),
    ]

    try:
        result = cast(HRReviewResult, structured_llm.invoke(messages))
    except Exception as exc:  # noqa: BLE001
        print_warning(f"HR review failed: {exc} — skipping.")
        return {}

    failed = [s for s in result.scores if s.score < 0.6]

    if not result.overall_pass and len(failed) >= _MIN_FAILURES_FOR_RETRY:
        print_warning(
            f"HR review flagged {len(failed)} issue(s): "
            + ", ".join(s.name for s in failed)
        )
        # Append HR feedback to any existing validation feedback
        existing = state.get("validation_feedback") or ""
        hr_text = f"HR pre-flight issues:\n{result.feedback}" if result.feedback else ""
        combined = "\n".join(p for p in [existing, hr_text] if p)
        return {
            "validation_passed": False,
            "validation_feedback": combined or "HR review failed multiple criteria.",
        }

    _log_scores(result)
    return {}


def _log_scores(result: HRReviewResult) -> None:
    for score in result.scores:
        icon = "✓" if score.score >= 0.7 else "⚠"
        note = f" — {score.note}" if score.note else ""
        print_info(f"  {icon} {score.name}: {score.score:.2f}{note}")

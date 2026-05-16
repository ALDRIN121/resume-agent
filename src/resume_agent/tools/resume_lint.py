"""
Deterministic (no-LLM) resume quality checks.

Each check function returns a list of LintIssue objects.  Severity levels:
  "warn"  — advisory; does not block generation
  "fail"  — hard problem; generator should retry

The lint_resume() entry point runs all checks and returns aggregated results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..schemas import UserResume

# Unicode chars that _LATEX_ESCAPE_MAP already converts at render time.
# We normalise free-text fields to ASCII before lint so unicode_quote_scan
# does not fire on characters that are harmless in the final PDF.
_UNICODE_NORM_MAP: dict[str, str] = {
    "’": "'",    # right single quotation mark → straight apostrophe
    "‘": "`",    # left single quotation mark  → backtick
    "“": "``",   # left double quotation mark
    "”": "''",   # right double quotation mark
    "–": "--",   # en-dash
    "—": "---",  # em-dash
}
_UNICODE_NORM_RE = re.compile("|".join(re.escape(k) for k in _UNICODE_NORM_MAP))


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class LintIssue:
    severity: str       # "warn" | "fail"
    code: str           # short machine-readable code, e.g. "METRIC_DENSITY"
    message: str        # human-readable description


@dataclass
class LintResult:
    issues: list[LintIssue] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return any(i.severity == "fail" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warn" for i in self.issues)

    def feedback_text(self) -> str:
        """Formatted text suitable for the resume generator fix-prompt."""
        if not self.issues:
            return ""
        lines = []
        for issue in self.issues:
            prefix = "[FAIL]" if issue.severity == "fail" else "[WARN]"
            lines.append(f"{prefix} {issue.code}: {issue.message}")
        return "\n".join(lines)

    def fail_feedback_text(self) -> str:
        """Formatted text for the fix-prompt containing only FAIL-severity issues.

        WARN issues are intentionally excluded so they do not destabilise the
        LLM fix pass with unrelated verb-tense rewrites.
        """
        lines = [
            f"[FAIL] {i.code}: {i.message}"
            for i in self.issues
            if i.severity == "fail"
        ]
        return "\n".join(lines)


# ── Thresholds ─────────────────────────────────────────────────────────────────

_METRIC_DENSITY_WARN = 0.60
_METRIC_DENSITY_FAIL = 0.80
_BUZZWORD_DENSITY_WARN = 0.25

# A quantified metric: "50%", "3x", "2.5x", "+40", "10+ "
_METRIC_RE = re.compile(r"\d+(?:\.\d+)?[x%]|\+\d+", re.IGNORECASE)

# Common resume buzzwords that add little signal when overused
_BUZZWORDS = frozenset({
    "synergy", "leverage", "utilize", "proactive", "dynamic", "innovative",
    "passionate", "results-driven", "team player", "detail-oriented",
    "self-starter", "thought leader", "paradigm", "ecosystem", "robust",
    "scalable", "cutting-edge", "best-in-class", "world-class", "best practices",
})

# Banned opener words/phrases (first word of a bullet)
_BANNED_OPENER_WORDS = frozenset({
    "worked", "helped", "assisted", "participated", "involved", "supported",
    "responsible",
})

# Regex for "was responsible for" (multi-word banned opener)
_BANNED_OPENER_PHRASES = re.compile(
    r"^(was responsible for|participated in|involved in|worked on|helped with)",
    re.IGNORECASE,
)

# Narrow possessive patterns that likely indicate a dropped apostrophe.
# Uses `s\s` (not `s\b`) so end-of-sentence plurals ("Led 3 engineers") never
# match — the pattern only fires when the word is followed by a space and then
# NOT an auxiliary verb or preposition that would indicate a plain plural.
_POSSESSIVE_NOUN_RE = re.compile(
    r"\b(company|team|client|user|employer|manager)s\s"
    r"(?!(?:are|were|have|do|can|will|would|should|is|was|of|in|to|for|with|by|on|at|\d|\w+ing\b))",
    re.IGNORECASE,
)

# Unicode smart-quote / em-dash characters that escape should have normalized
_SMART_QUOTE_RE = re.compile(r"[‘’“”–—]")

# Simple present-tense verb heuristic (ends in -s, excluding "was"/"is"/"has")
_PRESENT_TENSE_VERBS = frozenset({
    "lead", "leads", "architect", "build", "builds", "develop", "develops",
    "maintain", "maintains", "manage", "manages", "mentor", "mentors",
    "own", "owns", "drive", "drives", "deliver", "delivers", "design",
    "designs", "implement", "implements", "oversee", "oversees",
})
_PAST_TENSE_VERBS = frozenset({
    "led", "built", "designed", "shipped", "optimized", "reduced",
    "increased", "improved", "developed", "deployed", "implemented",
    "created", "launched", "delivered", "managed", "mentored", "migrated",
    "refactored", "automated", "architected", "established", "streamlined",
})


# ── Individual checks ──────────────────────────────────────────────────────────

def metric_density(resume: "UserResume") -> list[LintIssue]:
    """Warn/fail when too many bullets contain a numeric metric."""
    all_bullets = [b for role in resume.experience for b in role.bullets]
    all_bullets += [b for proj in resume.projects for b in proj.bullets]
    if not all_bullets:
        return []
    quantified = sum(1 for b in all_bullets if _METRIC_RE.search(b))
    density = quantified / len(all_bullets)
    if density > _METRIC_DENSITY_FAIL:
        return [LintIssue(
            severity="fail",
            code="METRIC_DENSITY",
            message=(
                f"Metric density is {density:.0%} ({quantified}/{len(all_bullets)} bullets). "
                "Aim for 40-60%. Over-quantification reads as fabricated. "
                "Convert weakest metrics to qualitative language."
            ),
        )]
    if density > _METRIC_DENSITY_WARN:
        return [LintIssue(
            severity="warn",
            code="METRIC_DENSITY",
            message=(
                f"Metric density is {density:.0%} ({quantified}/{len(all_bullets)} bullets). "
                "Consider reducing to below 60% for credibility."
            ),
        )]
    return []


def apostrophe_audit(resume: "UserResume") -> list[LintIssue]:
    """Detect likely dropped apostrophes in possessive constructions."""
    issues: list[LintIssue] = []
    all_text = _collect_all_text(resume)
    for text in all_text:
        matches = _POSSESSIVE_NOUN_RE.findall(text)
        if matches:
            for m in matches:
                issues.append(LintIssue(
                    severity="fail",
                    code="APOSTROPHE_LOSS",
                    message=(
                        f"Possible dropped apostrophe: '{m}s' should likely be '{m}'s'. "
                        "Check the bullet for missing possessives."
                    ),
                ))
    return issues


def tense_audit(resume: "UserResume") -> list[LintIssue]:
    """Warn when current-role bullets use past tense or past-role bullets use present."""
    issues: list[LintIssue] = []
    for role in resume.experience:
        is_current = role.end is None
        for bullet in role.bullets:
            first_word = bullet.split()[0].lower().rstrip(".,;:") if bullet.split() else ""
            if is_current and first_word in _PAST_TENSE_VERBS:
                issues.append(LintIssue(
                    severity="warn",
                    code="TENSE_MISMATCH",
                    message=(
                        f"Current role '{role.title}' at '{role.company}' has a past-tense "
                        f"bullet starting with '{first_word}'. Use present tense for current roles."
                    ),
                ))
            elif not is_current and first_word in _PRESENT_TENSE_VERBS:
                issues.append(LintIssue(
                    severity="warn",
                    code="TENSE_MISMATCH",
                    message=(
                        f"Past role '{role.title}' at '{role.company}' has a present-tense "
                        f"bullet starting with '{first_word}'. Use simple past for previous roles."
                    ),
                ))
    return issues


def verb_audit(resume: "UserResume") -> list[LintIssue]:
    """Warn on bullets starting with weak/banned openers."""
    issues: list[LintIssue] = []
    all_bullets = [
        (b, f"{role.title} at {role.company}")
        for role in resume.experience
        for b in role.bullets
    ]
    all_bullets += [(b, proj.name) for proj in resume.projects for b in proj.bullets]
    for bullet, context in all_bullets:
        first_word = bullet.split()[0].lower().rstrip(".,;:") if bullet.split() else ""
        if first_word in _BANNED_OPENER_WORDS or _BANNED_OPENER_PHRASES.match(bullet):
            issues.append(LintIssue(
                severity="warn",
                code="WEAK_VERB",
                message=(
                    f"Weak opener in '{context}': '{bullet[:60]}...' — "
                    "replace with a strong action verb (Led, Built, Designed, etc.)."
                ),
            ))
    return issues


def unicode_quote_scan(resume: "UserResume") -> list[LintIssue]:
    """Fail when smart-quote / em-dash characters are present (should be ASCII)."""
    issues: list[LintIssue] = []
    all_text = _collect_all_text(resume)
    found_chars: set[str] = set()
    for text in all_text:
        for char in _SMART_QUOTE_RE.findall(text):
            found_chars.add(char)
    if found_chars:
        readable = ", ".join(f"U+{ord(c):04X}" for c in sorted(found_chars))
        issues.append(LintIssue(
            severity="fail",
            code="UNICODE_QUOTES",
            message=(
                f"Smart-quote/dash characters found ({readable}). "
                "These must be replaced with ASCII equivalents before LaTeX rendering."
            ),
        ))
    return issues


def buzzword_density(resume: "UserResume") -> list[LintIssue]:
    """Warn when buzzwords make up more than 25% of summary word count."""
    if not resume.summary:
        return []
    words = re.findall(r"\w+", resume.summary.lower())
    if not words:
        return []
    # Multi-word buzzwords handled by checking bigrams
    text_lower = resume.summary.lower()
    hits = sum(1 for bw in _BUZZWORDS if bw in text_lower)
    density = hits / max(len(words), 1)
    if density > _BUZZWORD_DENSITY_WARN:
        return [LintIssue(
            severity="warn",
            code="BUZZWORD_DENSITY",
            message=(
                f"Summary contains {hits} buzzword(s) in {len(words)} words "
                f"({density:.0%}). Replace with concrete, specific language."
            ),
        )]
    return []


def github_present(resume: "UserResume") -> list[LintIssue]:
    """Warn when a senior-level candidate has no GitHub profile."""
    has_senior_keywords = any(
        kw in (resume.personal.headline or "").lower()
        or any(kw in role.title.lower() for role in resume.experience)
        for kw in ("senior", "staff", "lead", "principal", "architect")
    )
    if has_senior_keywords and not resume.personal.github:
        return [LintIssue(
            severity="warn",
            code="NO_GITHUB",
            message=(
                "Senior-level candidate has no GitHub profile. "
                "Add personal.github for ATS and recruiter credibility."
            ),
        )]
    return []


# ── Normalisation helper ───────────────────────────────────────────────────────

def normalize_resume_text(resume: "UserResume") -> "UserResume":
    """Return a deep copy of *resume* with Unicode smart-quotes/dashes replaced.

    The six characters handled here are already mapped to ASCII by the Jinja2
    ``_latex_escape`` filter at render time, so they never reach Tectonic.
    Normalising before lint prevents ``unicode_quote_scan`` from raising a
    spurious FAIL on characters that are benign in the final PDF.

    The live state object is never mutated — ``model_copy(deep=True)`` is used.
    """
    def _norm(text: str) -> str:
        return _UNICODE_NORM_RE.sub(lambda m: _UNICODE_NORM_MAP[m.group()], text)

    copy = resume.model_copy(deep=True)

    if copy.summary:
        copy.summary = _norm(copy.summary)

    for role in copy.experience:
        role.bullets = [_norm(b) for b in role.bullets]

    for proj in copy.projects:
        if proj.description:
            proj.description = _norm(proj.description)
        proj.bullets = [_norm(b) for b in proj.bullets]

    for edu in copy.education:
        edu.notes = [_norm(n) for n in edu.notes]

    return copy


# ── Entry point ────────────────────────────────────────────────────────────────

def lint_resume(resume: "UserResume") -> LintResult:
    """Run all deterministic checks and return the aggregated result."""
    result = LintResult()
    checks = [
        metric_density,
        apostrophe_audit,
        tense_audit,
        verb_audit,
        unicode_quote_scan,
        buzzword_density,
        github_present,
    ]
    for check in checks:
        result.issues.extend(check(resume))
    return result


# ── Helpers ────────────────────────────────────────────────────────────────────

def _collect_all_text(resume: "UserResume") -> list[str]:
    """Return all free-text strings from the resume (bullets, summary, descriptions)."""
    texts: list[str] = []
    if resume.summary:
        texts.append(resume.summary)
    for role in resume.experience:
        texts.extend(role.bullets)
    for proj in resume.projects:
        if proj.description:
            texts.append(proj.description)
        texts.extend(proj.bullets)
    for edu in resume.education:
        texts.extend(edu.notes)
    for cert in resume.certifications:
        texts.append(cert.name)
    return texts

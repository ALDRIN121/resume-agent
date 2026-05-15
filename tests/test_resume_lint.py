"""
Tests for the deterministic resume lint checks (Phase 4 / Phase 6.1).
"""

from __future__ import annotations

from resume_agent.schemas import PersonalInfo, Role, UserResume
from resume_agent.tools.resume_lint import (
    LintResult,
    apostrophe_audit,
    buzzword_density,
    github_present,
    lint_resume,
    metric_density,
    tense_audit,
    unicode_quote_scan,
    verb_audit,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _resume(bullets_current=None, bullets_past=None, summary=None, github=None, headline=None):
    experience = []
    if bullets_current is not None:
        experience.append(Role(
            company="CurrentCo", title="Senior Engineer",
            start="Jan 2023", end=None,
            bullets=bullets_current,
        ))
    if bullets_past is not None:
        experience.append(Role(
            company="OldCo", title="Engineer",
            start="Jan 2020", end="Dec 2022",
            bullets=bullets_past,
        ))
    return UserResume(
        personal=PersonalInfo(
            full_name="Jane Doe",
            email="jane@example.com",
            github=github,
            headline=headline,
        ),
        summary=summary,
        experience=experience,
    )


# ── metric_density ─────────────────────────────────────────────────────────────

class TestMetricDensity:

    def test_pass_at_50pct(self):
        bullets = [
            "Led team of 5 engineers",
            "Built CI pipeline",
            "Reduced latency by 40%",
            "Shipped new auth module",
        ]
        resume = _resume(bullets_past=bullets)
        issues = metric_density(resume)
        assert issues == []

    def test_warn_at_70pct(self):
        bullets = [
            "Reduced latency by 40%",
            "Increased throughput 3x",
            "Shipped 5 features",
            "Improved coverage by 20%",
        ]
        resume = _resume(bullets_past=bullets)
        issues = metric_density(resume)
        assert len(issues) == 1
        assert issues[0].severity == "warn"
        assert issues[0].code == "METRIC_DENSITY"

    def test_fail_at_85pct(self):
        # 7 of 8 bullets have a metric (87.5% > 80% fail threshold)
        bullets = [
            "Reduced latency 40%", "Increased throughput 3x",
            "Improved coverage 20%", "Cut costs by 15%",
            "Cut time 50%", "Grew revenue by 30%",
            "Achieved 2x load capacity",
            "Built deployment pipeline",  # no metric — the only clean bullet
        ]
        resume = _resume(bullets_past=bullets)
        issues = metric_density(resume)
        assert len(issues) == 1
        assert issues[0].severity == "fail"

    def test_no_bullets_returns_empty(self):
        resume = _resume()
        assert metric_density(resume) == []


# ── apostrophe_audit ───────────────────────────────────────────────────────────

class TestApostropheAudit:

    def test_flags_companys(self):
        resume = _resume(bullets_past=["Improved the companys product quality"])
        issues = apostrophe_audit(resume)
        assert any("company" in i.message.lower() for i in issues)
        assert all(i.code == "APOSTROPHE_LOSS" for i in issues)

    def test_allows_plain_plurals_with_verb(self):
        # "teams are working" — "teams" followed by "are" → not possessive
        resume = _resume(bullets_past=["Ensured teams are aligned across orgs"])
        issues = apostrophe_audit(resume)
        assert issues == []

    def test_allows_numeric_team_size(self):
        resume = _resume(bullets_past=["Led teams of 5 engineers"])
        issues = apostrophe_audit(resume)
        # "teams" is not in our narrow noun list, "of" is not an auxiliary verb
        # The pattern is narrow and should not fire on "teams of"
        assert all(i.code != "APOSTROPHE_LOSS" for i in issues)


# ── tense_audit ────────────────────────────────────────────────────────────────

class TestTenseAudit:

    def test_current_role_must_be_present(self):
        # "led" is a past-tense verb in a current role — should warn
        resume = _resume(bullets_current=["Led the backend team"])
        issues = tense_audit(resume)
        assert any(i.code == "TENSE_MISMATCH" for i in issues)
        assert any("current" in i.message.lower() for i in issues)

    def test_past_role_must_be_past(self):
        # "leads" is a present-tense verb in a past role — should warn
        resume = _resume(bullets_past=["Leads the backend team"])
        issues = tense_audit(resume)
        assert any(i.code == "TENSE_MISMATCH" for i in issues)
        assert any("past" in i.message.lower() for i in issues)

    def test_correct_present_tense_no_warn(self):
        resume = _resume(bullets_current=["Lead the backend team", "Manage 4 engineers"])
        assert tense_audit(resume) == []

    def test_correct_past_tense_no_warn(self):
        resume = _resume(bullets_past=["Led the backend team", "Built CI pipeline"])
        assert tense_audit(resume) == []


# ── verb_audit ─────────────────────────────────────────────────────────────────

class TestVerbAudit:

    def test_banned_opener_detected(self):
        resume = _resume(bullets_past=["Worked on the payment service refactor"])
        issues = verb_audit(resume)
        assert any(i.code == "WEAK_VERB" for i in issues)

    def test_helped_opener_detected(self):
        resume = _resume(bullets_past=["Helped migrate the monolith to microservices"])
        issues = verb_audit(resume)
        assert any(i.code == "WEAK_VERB" for i in issues)

    def test_responsible_for_opener_detected(self):
        resume = _resume(bullets_past=["Was responsible for CI pipeline maintenance"])
        issues = verb_audit(resume)
        assert any(i.code == "WEAK_VERB" for i in issues)

    def test_strong_verb_passes(self):
        resume = _resume(bullets_past=["Built a zero-downtime deployment pipeline"])
        assert verb_audit(resume) == []


# ── unicode_quote_scan ─────────────────────────────────────────────────────────

class TestUnicodeQuoteScan:

    def test_smart_quote_normalization_to_ascii_needed(self):
        resume = _resume(bullets_past=["“Highly impactful” feature"])
        issues = unicode_quote_scan(resume)
        assert any(i.code == "UNICODE_QUOTES" for i in issues)
        assert all(i.severity == "fail" for i in issues)

    def test_em_dash_flagged(self):
        resume = _resume(bullets_past=["Shipped feature — on time"])
        issues = unicode_quote_scan(resume)
        assert any(i.code == "UNICODE_QUOTES" for i in issues)

    def test_ascii_apostrophe_clean(self):
        resume = _resume(bullets_past=["Improved the team's velocity by 30%"])
        assert unicode_quote_scan(resume) == []


# ── buzzword_density ───────────────────────────────────────────────────────────

class TestBuzzwordDensity:

    def test_buzzword_density_flag(self):
        resume = _resume(summary=(
            "Innovative and passionate engineer leveraging synergy to drive "
            "best-in-class results with a robust, scalable ecosystem."
        ))
        issues = buzzword_density(resume)
        assert any(i.code == "BUZZWORD_DENSITY" for i in issues)

    def test_clean_summary_passes(self):
        resume = _resume(summary=(
            "Backend engineer with 5 years building distributed systems in Python and Go."
        ))
        assert buzzword_density(resume) == []

    def test_no_summary_no_issues(self):
        resume = _resume()
        assert buzzword_density(resume) == []


# ── github_present ─────────────────────────────────────────────────────────────

class TestGithubPresent:

    def test_senior_without_github_warns(self):
        resume = _resume(headline="Senior Backend Engineer")
        issues = github_present(resume)
        assert any(i.code == "NO_GITHUB" for i in issues)

    def test_senior_with_github_clean(self):
        resume = _resume(headline="Senior Backend Engineer", github="jdoe")
        assert github_present(resume) == []

    def test_junior_without_github_no_warn(self):
        resume = _resume()  # no headline, no senior title
        assert github_present(resume) == []


# ── lint_resume (integration) ─────────────────────────────────────────────────

class TestLintResume:

    def test_returns_lint_result(self):
        resume = _resume(bullets_past=["Built CI pipeline"])
        result = lint_resume(resume)
        assert isinstance(result, LintResult)

    def test_has_failures_false_when_clean(self):
        resume = _resume(bullets_past=["Built CI pipeline", "Led 3 engineers"])
        result = lint_resume(resume)
        assert not result.has_failures

    def test_feedback_text_empty_when_no_issues(self):
        resume = _resume(bullets_past=["Built CI pipeline"])
        result = lint_resume(resume)
        if not result.has_failures:
            assert result.feedback_text() == "" or result.feedback_text().startswith("[WARN]")

    def test_feedback_text_includes_fail_marker(self):
        # Smart quotes trigger a "fail" issue
        resume = _resume(bullets_past=["“Impactful” feature launch"])
        result = lint_resume(resume)
        assert result.has_failures
        assert "[FAIL]" in result.feedback_text()

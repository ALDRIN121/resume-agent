"""Tests for Pydantic data models."""

import warnings

import pytest
from pydantic import ValidationError

from resume_agent.schemas import (
    Certification,
    GapAnalysis,
    JobDescription,
    PersonalInfo,
    Role,
    Suggestion,
    UserResume,
)


class TestPersonalInfo:
    def test_minimal(self):
        p = PersonalInfo(full_name="Jane Doe", email="jane@example.com")
        assert p.full_name == "Jane Doe"
        assert p.phone is None

    def test_full(self):
        p = PersonalInfo(
            full_name="Jane Doe",
            email="jane@example.com",
            phone="+1-555-0100",
            location="San Francisco, CA",
            linkedin="janedoe",
            github="janedoe",
            website="https://janedoe.dev",
        )
        assert p.linkedin == "janedoe"

    def test_missing_required(self):
        with pytest.raises(ValidationError):
            PersonalInfo(full_name="Jane")  # missing email


class TestUserResume:
    def test_minimal_resume(self):
        r = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com")
        )
        assert r.experience == []
        assert r.skills == {}

    def test_all_skill_strings(self):
        r = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com"),
            skills={
                "Languages": ["Python", "Go"],
                "Tools": ["Docker", "Kubernetes"],
            },
        )
        all_skills = r.all_skill_strings()
        assert "Python" in all_skills
        assert "Kubernetes" in all_skills
        assert len(all_skills) == 4

    def test_experience_with_roles(self):
        r = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com"),
            experience=[
                Role(
                    company="Acme Corp",
                    title="Software Engineer",
                    start="Jan 2022",
                    end="Dec 2023",
                    bullets=["Built microservices in Go", "Reduced latency by 40%"],
                    tech=["Go", "Kubernetes"],
                )
            ],
        )
        assert len(r.experience) == 1
        assert r.experience[0].end == "Dec 2023"


class TestJobDescription:
    def test_defaults(self):
        jd = JobDescription(company="TechCorp", role_title="Senior Engineer")
        assert jd.must_have_skills == []
        assert jd.seniority is None

    def test_full(self):
        jd = JobDescription(
            company="TechCorp",
            role_title="Senior Software Engineer",
            seniority="Senior",
            must_have_skills=["Python", "AWS", "Kubernetes"],
            nice_to_have_skills=["Rust"],
            keywords=["distributed systems", "microservices"],
        )
        assert len(jd.must_have_skills) == 3


class TestGapAnalysis:
    def test_defaults(self):
        g = GapAnalysis()
        assert g.matched_skills == []
        assert g.open_questions == []

    def test_with_suggestions(self):
        g = GapAnalysis(
            matched_skills=["Python", "Docker"],
            missing_skills=["Rust"],
            tailoring_ideas=[
                Suggestion(
                    id="s1",
                    section="experience",
                    role_company="Acme",
                    before="Worked on backend services",
                    after="Led backend microservices development using Python and Docker",
                    rationale="Mirrors JD keywords",
                )
            ],
        )
        assert g.tailoring_ideas[0].id == "s1"


# ── Phase 6.2 additions ────────────────────────────────────────────────────────

class TestPersonalInfoExtended:

    def test_headline_optional(self):
        p = PersonalInfo(full_name="Jane Doe", email="jane@example.com")
        assert p.headline is None

    def test_headline_set(self):
        p = PersonalInfo(
            full_name="Jane Doe",
            email="jane@example.com",
            headline="Open to Remote -- EU & US",
        )
        assert p.headline == "Open to Remote -- EU & US"

    def test_portfolio_optional(self):
        p = PersonalInfo(full_name="Jane Doe", email="jane@example.com")
        assert p.portfolio is None

    def test_portfolio_set(self):
        p = PersonalInfo(
            full_name="Jane Doe",
            email="jane@example.com",
            portfolio="https://janedoe.dev/portfolio",
        )
        assert p.portfolio == "https://janedoe.dev/portfolio"


class TestCertificationWarning:

    def test_certification_warns_on_missing_date(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cert = Certification(name="AWS Solutions Architect", issuer="Amazon")
        assert any("no date" in str(w.message).lower() for w in caught)

    def test_certification_no_warn_when_date_present(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cert = Certification(name="AWS Solutions Architect", date="2023-06")
        assert not any("no date" in str(w.message).lower() for w in caught)


class TestUserResumeMetricDensity:

    def test_metric_density_zero_when_no_metrics(self):
        r = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="j@d.com"),
            experience=[
                Role(
                    company="Acme", title="Engineer",
                    start="Jan 2020", end="Dec 2022",
                    bullets=["Built CI pipeline", "Led backend team"],
                )
            ],
        )
        assert r.metric_density() == 0.0

    def test_metric_density_one_when_all_quantified(self):
        r = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="j@d.com"),
            experience=[
                Role(
                    company="Acme", title="Engineer",
                    start="Jan 2020", end="Dec 2022",
                    bullets=["Reduced latency by 40%", "Increased throughput 3x"],
                )
            ],
        )
        assert r.metric_density() == 1.0

    def test_metric_density_half_when_mixed(self):
        r = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="j@d.com"),
            experience=[
                Role(
                    company="Acme", title="Engineer",
                    start="Jan 2020", end="Dec 2022",
                    bullets=["Reduced latency by 40%", "Built CI pipeline"],
                )
            ],
        )
        assert r.metric_density() == 0.5

    def test_tense_check_returns_tuple(self):
        r = UserResume(
            personal=PersonalInfo(full_name="Jane Doe", email="j@d.com"),
        )
        result = r.tense_check()
        assert isinstance(result, tuple)
        assert len(result) == 2
        # vacuously correct when no bullets
        assert result == (1.0, 1.0)

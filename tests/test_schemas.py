"""Tests for Pydantic data models."""

import pytest
from pydantic import ValidationError

from resume_agent.schemas import (
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

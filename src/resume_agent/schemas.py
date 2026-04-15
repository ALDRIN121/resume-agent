"""Pydantic data models shared across all agents."""

from __future__ import annotations

import re
from typing import Optional
from pydantic import BaseModel, Field, model_validator


# ── User Resume models ─────────────────────────────────────────────────────────

class PersonalInfo(BaseModel):
    full_name: str
    email: str
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None   # handle only, e.g. "john-doe"
    github: Optional[str] = None     # handle only, e.g. "johndoe"
    website: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # name → full_name  (common LLM alias)
        if "name" in data and "full_name" not in data:
            data["full_name"] = data.pop("name")
        return data


class Role(BaseModel):
    company: str
    title: str
    start: str                       # e.g. "Jan 2022" or "2022-01"
    end: Optional[str] = None        # None means Present
    location: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)
    tech: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # job_title → title
        if "job_title" in data and "title" not in data:
            data["title"] = data.pop("job_title")
        # date_range → start + end  (split on " -- ", " – ", " — ", " - ")
        if "date_range" in data and "start" not in data:
            date_range = str(data.pop("date_range"))
            # Require whitespace on both sides so "2022-01" is not split mid-token
            parts = re.split(r"\s+[-–—]+\s+|\s+to\s+", date_range, maxsplit=1)
            data["start"] = parts[0].strip()
            if len(parts) > 1:
                end = parts[1].strip()
                if end.lower() not in ("present", "current", "now", ""):
                    data["end"] = end
        # bullet_points → bullets
        if "bullet_points" in data and "bullets" not in data:
            data["bullets"] = data.pop("bullet_points")
        # tech_stack → tech
        if "tech_stack" in data and "tech" not in data:
            data["tech"] = data.pop("tech_stack")
        return data


class Project(BaseModel):
    name: str
    description: str
    bullets: list[str] = Field(default_factory=list)
    tech: list[str] = Field(default_factory=list)
    url: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # bullet_points → bullets
        if "bullet_points" in data and "bullets" not in data:
            data["bullets"] = data.pop("bullet_points")
        # tech_stack → tech
        if "tech_stack" in data and "tech" not in data:
            data["tech"] = data.pop("tech_stack")
        return data


class Education(BaseModel):
    institution: str
    degree: str
    field: Optional[str] = None
    graduation: Optional[str] = None  # e.g. "May 2020"
    gpa: Optional[str] = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # graduation_date → graduation
        if "graduation_date" in data and "graduation" not in data:
            data["graduation"] = data.pop("graduation_date")
        # gpa may arrive as a number
        if "gpa" in data and data["gpa"] is not None:
            data["gpa"] = str(data["gpa"])
        return data


class Certification(BaseModel):
    name: str
    issuer: Optional[str] = None
    date: Optional[str] = None
    url: Optional[str] = None


class UserResume(BaseModel):
    personal: PersonalInfo
    summary: Optional[str] = None
    experience: list[Role] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    # Skill categories -> list of skills, e.g. {"Languages": ["Python", "Go"]}
    skills: dict[str, list[str]] = Field(default_factory=dict)
    publications: list[str] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # contact_information → personal  (common LLM alias)
        if "contact_information" in data and "personal" not in data:
            data["personal"] = data.pop("contact_information")
        return data

    def all_skill_strings(self) -> list[str]:
        """Flat list of all skills across categories."""
        return [s for items in self.skills.values() for s in items]


# ── Job Description models ─────────────────────────────────────────────────────

class JobDescription(BaseModel):
    company: str
    role_title: str
    seniority: Optional[str] = None       # e.g. "Senior", "Staff", "Lead"
    location: Optional[str] = None
    remote_policy: Optional[str] = None   # "Remote", "Hybrid", "On-site"
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    raw_text: Optional[str] = None


# ── Gap Analysis models ────────────────────────────────────────────────────────

class Question(BaseModel):
    id: str               # e.g. "q1", "q2"
    prompt: str           # The question to ask the user
    why_asking: str       # Brief rationale shown to user


class Suggestion(BaseModel):
    id: str               # e.g. "s1", "s2"
    section: str          # "experience" | "summary" | "skills" | "projects"
    role_company: Optional[str] = None   # Which role this applies to, if experience
    before: str           # Original text
    after: str            # Suggested improved text
    rationale: str        # 1-line reason


class GapAnalysis(BaseModel):
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    open_questions: list[Question] = Field(default_factory=list)
    tailoring_ideas: list[Suggestion] = Field(default_factory=list)

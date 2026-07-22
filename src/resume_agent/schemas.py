"""Pydantic data models shared across all agents."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator

# ── User Resume models ─────────────────────────────────────────────────────────

class PersonalInfo(BaseModel):
    full_name: str
    email: str
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None   # handle only, e.g. "john-doe"
    github: str | None = None     # handle only, e.g. "johndoe"
    website: str | None = None
    portfolio: str | None = None  # portfolio URL, distinct from personal website
    headline: str | None = None   # e.g. "Open to Remote / Relocation — EU & US"

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
    end: str | None = None        # None means Present
    location: str | None = None
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
    url: str | None = None

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
    field: str | None = None
    graduation: str | None = None  # e.g. "May 2020"
    gpa: str | None = None
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
    issuer: str | None = None
    date: str | None = None
    url: str | None = None


class UserResume(BaseModel):
    personal: PersonalInfo
    summary: str | None = None
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
        # Certifications may arrive as plain strings → wrap as {"name": str}
        if "certifications" in data and isinstance(data["certifications"], list):
            data["certifications"] = [
                {"name": c} if isinstance(c, str) else c
                for c in data["certifications"]
            ]
        return data

    def all_skill_strings(self) -> list[str]:
        """Flat list of all skills across categories."""
        return [s for items in self.skills.values() for s in items]

    def all_bullets(self) -> list[tuple[str, bool]]:
        """All (bullet_text, is_current_role) pairs across experience and projects."""
        result: list[tuple[str, bool]] = []
        for role in self.experience:
            is_current = role.end is None
            for b in role.bullets:
                result.append((b, is_current))
        for project in self.projects:
            for b in project.bullets:
                result.append((b, False))
        return result

    # Regex matching a numeric metric: "50%", "3x", "+40", "2.5x"
    _METRIC_RE = re.compile(r"\d+(?:\.\d+)?[x%]|\+\d+", re.IGNORECASE)

    def metric_density(self) -> float:
        """Fraction of bullets that contain at least one quantified metric (0.0 – 1.0)."""
        bullets = [b for b, _ in self.all_bullets()]
        if not bullets:
            return 0.0
        quantified = sum(1 for b in bullets if self._METRIC_RE.search(b))
        return quantified / len(bullets)

    # Simple heuristic sets — not exhaustive, but covers the most common cases
    _PRESENT_TENSE_VERBS = frozenset({
        "lead", "leads", "architect", "architecting", "build", "builds",
        "develop", "develops", "maintain", "maintains", "manage", "manages",
        "mentor", "mentors", "collaborate", "collaborates", "own", "owns",
        "drive", "drives", "deliver", "delivers", "design", "designs",
        "implement", "implements", "improve", "improves", "oversee", "oversees",
    })
    _PAST_TENSE_VERBS = frozenset({
        "led", "built", "designed", "shipped", "optimized", "reduced",
        "increased", "improved", "developed", "deployed", "implemented",
        "created", "launched", "delivered", "managed", "mentored", "migrated",
        "refactored", "automated", "architected", "established", "streamlined",
    })

    def tense_check(self) -> tuple[float, float]:
        """
        Returns (current_role_present_ratio, past_role_past_ratio).

        current_role_present_ratio: fraction of current-role bullets starting with a
          present-tense verb. Should be close to 1.0.
        past_role_past_ratio: fraction of past-role bullets starting with a past-tense
          verb. Should be close to 1.0.
        """
        current_bullets: list[str] = []
        past_bullets: list[str] = []
        for b, is_current in self.all_bullets():
            (current_bullets if is_current else past_bullets).append(b)

        def _ratio(bullets: list[str], verb_set: frozenset) -> float:
            if not bullets:
                return 1.0  # vacuously correct
            matched = sum(
                1 for b in bullets
                if b.split()[0].lower().rstrip(".,;:") in verb_set
            )
            return matched / len(bullets)

        return (
            _ratio(current_bullets, self._PRESENT_TENSE_VERBS),
            _ratio(past_bullets, self._PAST_TENSE_VERBS),
        )


# ── Job Description models ─────────────────────────────────────────────────────

class JobDescription(BaseModel):
    company: str
    role_title: str
    seniority: str | None = None       # e.g. "Senior", "Staff", "Lead"
    location: str | None = None
    remote_policy: str | None = None   # "Remote", "Hybrid", "On-site"
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    raw_text: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # role / job_title / title → role_title  (common LLM aliases)
        for alias in ("role", "job_title", "title", "position"):
            if alias in data and "role_title" not in data:
                data["role_title"] = data.pop(alias)
                break
        # required_skills → must_have_skills
        if "required_skills" in data and "must_have_skills" not in data:
            data["must_have_skills"] = data.pop("required_skills")
        # preferred_skills → nice_to_have_skills
        if "preferred_skills" in data and "nice_to_have_skills" not in data:
            data["nice_to_have_skills"] = data.pop("preferred_skills")
        return data


# ── Gap Analysis models ────────────────────────────────────────────────────────

class Question(BaseModel):
    id: str               # e.g. "q1", "q2"
    prompt: str           # The question to ask the user
    why_asking: str       # Brief rationale shown to user

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # question / text / content → prompt  (common LLM aliases)
        for alias in ("question", "text", "content", "question_text"):
            if alias in data and "prompt" not in data:
                data["prompt"] = data.pop(alias)
                break
        # reason / rationale → why_asking
        for alias in ("reason", "rationale", "explanation"):
            if alias in data and "why_asking" not in data:
                data["why_asking"] = data.pop(alias)
                break
        return data


class Suggestion(BaseModel):
    id: str               # e.g. "s1", "s2"
    section: str          # "experience" | "summary" | "skills" | "projects"
    role_company: str | None = None   # Which role this applies to, if experience
    before: str           # Original text
    after: str            # Suggested improved text
    rationale: str        # 1-line reason

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # original / original_text / current → before
        for alias in ("original", "original_text", "current", "current_text", "old"):
            if alias in data and "before" not in data:
                data["before"] = data.pop(alias)
                break
        # suggested / suggested_text / updated / new → after
        for alias in ("suggested", "suggested_text", "updated", "updated_text", "new", "replacement"):
            if alias in data and "after" not in data:
                data["after"] = data.pop(alias)
                break
        # reason / explanation → rationale
        for alias in ("reason", "explanation", "why"):
            if alias in data and "rationale" not in data:
                data["rationale"] = data.pop(alias)
                break
        return data


class GapAnalysis(BaseModel):
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    open_questions: list[Question] = Field(default_factory=list)
    tailoring_ideas: list[Suggestion] = Field(default_factory=list)

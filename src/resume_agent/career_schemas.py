"""Versioned career inputs and source-bound role analysis; scores are computed."""
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from .contracts import Contract, Hash

Dimension = Literal['required_skills', 'responsibilities', 'scope_seniority', 'domain_experience',
                    'candidate_preferences', 'additional_skills']
EvidenceStatus = Literal['supported', 'transferable', 'contradicted', 'unknown']


class CareerJob(Contract):
    id: str
    logical_id: str
    previous_id: str | None
    text: str
    content_hash: Hash
    source_kind: Literal['manual', 'url', 'discovery']
    source_key: str
    source_url: str | None
    company: str | None
    role: str | None
    captured_at: str


class JDCitation(Contract):
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]
    quote: Annotated[str, Field(min_length=1)]


class AtomicCriterion(Contract):
    id: Annotated[str, Field(min_length=1)]
    text: Annotated[str, Field(min_length=1)]
    citations: Annotated[list[JDCitation], Field(min_length=1)]


class RoleRequirement(Contract):
    id: Annotated[str, Field(min_length=1)]
    dimension: Dimension
    operator: Literal['single', 'all', 'any']
    members: Annotated[list[AtomicCriterion], Field(min_length=1)]
    needs_review: bool = False

    @model_validator(mode='after')
    def single_has_one_member(self):
        if self.operator == 'single' and len(self.members) != 1:
            raise ValueError('single_requires_one_member')
        return self


class CandidateSource(Contract):
    kind: Literal['profile', 'answer', 'user_text', 'memory', 'eligibility']
    input_hash: Hash
    target_path: Annotated[str, Field(min_length=1)]
    quote: Annotated[str, Field(min_length=1)]


class RequirementFinding(Contract):
    member_id: str
    status: EvidenceStatus
    sources: list[CandidateSource] = Field(default_factory=list)
    rationale: str


class EligibilityFinding(Contract):
    category: Literal['authorization', 'clearance', 'presence', 'user_hard_constraint']
    status: Literal['pass', 'fail', 'unknown']
    citation: JDCitation
    sources: list[CandidateSource] = Field(default_factory=list)
    rationale: str


class RoleAnalysis(Contract):
    requirements: list[RoleRequirement]
    findings: list[RequirementFinding]
    eligibility: list[EligibilityFinding] = Field(default_factory=list)


class RoleEvaluation(Contract):
    operation_id: str
    job_id: str
    rubric_version: Literal['fit-v1'] = 'fit-v1'
    profile_revision: Hash
    memory_revision: Hash
    jd_revision: Hash
    provider: str | None
    model: str | None
    analysis: RoleAnalysis
    fit: dict[str, JsonValue]
    eligibility_status: Literal['pass', 'fail', 'unknown']
    resolved_sources: list[dict[str, JsonValue]]

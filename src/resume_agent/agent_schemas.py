"""Host-neutral, closed-stdin command protocol; credentials are not inputs."""
from typing import Literal

from pydantic import Field, JsonValue

from .contracts import Contract, Identifier, RunRequest

ResourceKind = Literal['run', 'profile_import', 'role_evaluation', 'discovery_sync', 'application', 'memory']
ExecutionMode = Literal['configured_provider', 'external_agent']


class Resource(Contract):
    kind: ResourceKind
    id: Identifier


class AgentError(Contract):
    code: Identifier
    message: str


class AgentEnvelope(Contract):
    schema_version: Literal[1] = 1
    ok: bool
    command: str
    resource: Resource | None = None
    data: JsonValue = None
    next_action: dict[str, JsonValue] | None = None
    error: AgentError | None = None


class StartInput(RunRequest):
    job_input: str = Field(min_length=1, max_length=48000)
    execution_mode: ExecutionMode = 'configured_provider'


class ImportInput(Contract):
    source_path: Identifier
    execution_mode: ExecutionMode = 'configured_provider'


class EvaluateInput(Contract):
    job_id: Identifier
    answers: dict[str, str] = Field(default_factory=dict)
    user_text: dict[str, str] = Field(default_factory=dict)
    eligibility_facts: dict[str, str] = Field(default_factory=dict)
    execution_mode: ExecutionMode = 'configured_provider'


class DomainInput(Contract):
    op: Identifier
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class EmptyInput(Contract):
    pass


class PostingsInput(Contract):
    source_id: str | None = None
    state: Literal['active', 'removed'] | None = None
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

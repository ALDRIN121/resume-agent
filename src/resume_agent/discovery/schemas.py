from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from ..contracts import Contract, Hash, Identifier

BoardSlug = Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')]


class SourceSpec(Contract):
    provider: Literal['greenhouse', 'lever', 'ashby']
    board: BoardSlug
    region: Literal['global', 'eu'] = 'global'
    company: str | None = None
    enabled: bool = True

    @model_validator(mode='after')
    def provider_region(self):
        if self.provider != 'lever' and self.region != 'global':
            raise ValueError('region_only_supported_for_lever')
        return self


class SourceInput(SourceSpec):
    id: Identifier | None = None


class DiscoverySource(SourceSpec):
    id: Identifier


@dataclass(frozen=True)
class PagePayload:
    payload: object
    observed_at: str
    observation_order: int


class DiscoveredJob(Contract):
    external_id: Identifier
    title: Identifier
    text: Identifier
    source_url: str
    raw: dict[str, JsonValue]
    raw_hash: Hash
    extraction_version: Literal['public-board-text-v1'] = 'public-board-text-v1'
    observed_at: str | None = None
    observation_order: int | None = None


class BoardResult(Contract):
    status: Literal['complete', 'partial', 'failed']
    jobs: list[DiscoveredJob]
    received_count: int
    valid_count: int
    malformed_count: int = 0
    duplicate_count: int = 0
    conflicting_count: int = 0
    truncated_count: int = 0
    filtered_count: int = 0
    limit_reached: bool = False
    diagnostics: list[str] = Field(default_factory=list)
    observed_at: str | None = None
    first_observation_order: int | None = None
    last_observation_order: int | None = None


class DiscoveryError(RuntimeError):
    def __init__(self, code, *, partial=False):
        self.code, self.partial = code, partial
        super().__init__(code)


class ScanCancelledError(Exception):
    pass

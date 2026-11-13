from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from ..contracts import Contract, Hash, Identifier

BoardSlug = Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')]


class DiscoverySource(Contract):
    id: Identifier
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


class DiscoveredJob(Contract):
    external_id: Identifier
    title: Identifier
    text: Identifier
    source_url: str
    raw: dict[str, JsonValue]
    raw_hash: Hash
    extraction_version: Literal['public-board-text-v1'] = 'public-board-text-v1'


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


class DiscoveryError(RuntimeError):
    def __init__(self, code, *, partial=False):
        self.code, self.partial = code, partial
        super().__init__(code)

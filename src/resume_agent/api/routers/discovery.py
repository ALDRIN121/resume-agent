"""Explicit manual public-board discovery. Reads never start network work."""
from fastapi import APIRouter, Body, Query, Request
from pydantic import Field

from ...contracts import Continue, Contract, Hash, Identifier
from ...discovery.schemas import SourceInput
from ...run_store import Conflict
from .jobs import failure

router = APIRouter(prefix='/api/discovery', tags=['discovery'])


class ConfigureSources(Contract):
    sources: list[SourceInput] = Field(max_length=20)
    expected_revision: Hash
    action_id: Identifier


class CreateSync(Contract):
    expected_sources_revision: Hash
    action_id: Identifier
    source_ids: list[Identifier] | None = None


class CancelSync(Contract):
    action_id: Identifier


def invoke(request, method, *args, **kwargs):
    try:
        return getattr(request.app.state.services.discovery, method)(*args, **kwargs)
    except (KeyError, ValueError, Conflict) as exc:
        raise failure(exc) from None


@router.get('/sources')
def sources(request: Request):
    return invoke(request, 'sources')


@router.put('/sources')
def configure_sources(body: ConfigureSources, request: Request):
    return invoke(request, 'replace_sources', [s.model_dump(mode='json', exclude_none=True) for s in body.sources],
                  expected_revision=body.expected_revision, action_id=body.action_id)


@router.get('/syncs')
def syncs(request: Request):
    return invoke(request, 'list_syncs')


@router.post('/syncs')
@router.post('/sync', include_in_schema=False)
def create_sync(body: CreateSync, request: Request):
    return invoke(request, 'create_sync', **body.model_dump())


@router.get('/syncs/{sync_id}')
def get_sync(sync_id: str, request: Request):
    return invoke(request, 'get_sync', sync_id)


@router.post('/syncs/{sync_id}/continue')
async def continue_sync(sync_id: str, request: Request, body: Continue | None = Body(default=None)):
    try:
        return await request.app.state.services.discovery.drive(sync_id, continue_action_id=body.action_id if body else None)
    except (KeyError, ValueError, Conflict) as exc:
        raise failure(exc) from None


@router.post('/syncs/{sync_id}/cancel')
def cancel_sync(sync_id: str, body: CancelSync, request: Request):
    return invoke(request, 'cancel', sync_id, action_id=body.action_id)


@router.get('/postings')
def postings(request: Request, source_id: str | None = None, state: str | None = None,
             limit: int = Query(default=50, ge=1, le=1000), offset: int = Query(default=0, ge=0)):
    return invoke(request, 'postings_page', source_id=source_id, state=state, limit=limit, offset=offset)

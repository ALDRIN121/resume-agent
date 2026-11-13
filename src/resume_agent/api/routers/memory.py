"""Review adapters for explicit, revision-bound memory decisions."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ...contracts import Contract, Hash
from ...memory import MemoryProposal
from ...run_store import Conflict

router = APIRouter(prefix='/api/memory', tags=['memory'])


class MemoryDecision(Contract):
    decision: Literal['accept', 'reject', 'revoke']
    expected_revision: Hash
    action_id: str = Field(min_length=1)


def invoke(request, method, *args, **kwargs):
    try:
        return getattr(request.app.state.services.memory, method)(*args, **kwargs)
    except (KeyError, Conflict, ValueError) as exc:
        raise HTTPException(404 if isinstance(exc, KeyError) else 409 if isinstance(exc, Conflict) else 400,
                            detail=str(exc)) from None


@router.get('/proposals')
def proposals(request: Request):
    return invoke(request, 'list')


@router.post('/proposals')
def propose(body: MemoryProposal, request: Request):
    return invoke(request, 'propose', body.model_dump(mode='json'))


@router.get('/active')
def active(request: Request):
    return invoke(request, 'snapshot')


@router.get('/{record_id}/preview')
def preview(record_id: str, request: Request):
    return invoke(request, 'preview', record_id)


@router.get('/{record_id}/history')
def history(record_id: str, request: Request):
    return invoke(request, 'history', record_id)


@router.get('/{record_id}')
def get(record_id: str, request: Request):
    return invoke(request, 'get', record_id)


@router.post('/{record_id}/decision')
def decide(record_id: str, body: MemoryDecision, request: Request):
    return invoke(request, 'decide', record_id, **body.model_dump(mode='json'))

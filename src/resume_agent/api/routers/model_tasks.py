"""Typed host model responses resolve to the same owner lifecycle and reviews."""
from fastapi import APIRouter, Request

from ...contracts import ModelResponse
from ...run_store import Conflict
from .jobs import failure

router = APIRouter(prefix='/api/model-tasks', tags=['model-tasks'])


@router.post('/{request_id}/respond')
async def respond_model_task(request_id: str, body: ModelResponse, request: Request):
    try:
        if body.request_id != request_id:
            raise Conflict('model_request_id_mismatch')
        return await request.app.state.services.respond_model_request(body)
    except (KeyError, ValueError, Conflict) as exc:
        raise failure(exc) from None

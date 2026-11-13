"""Local application records only; these routes never submit to an employer."""
from fastapi import APIRouter, HTTPException, Request

from ...applications import ApplicationEventRequest
from ...contracts import Contract, Identifier
from ...run_store import Conflict

router = APIRouter(prefix='/api/applications', tags=['applications'])


class CreateApplication(Contract):
    job_id: Identifier
    action_id: Identifier
    company: str | None = None


def invoke(request, method, *args, **kwargs):
    try:
        return getattr(request.app.state.services.applications, method)(*args, **kwargs)
    except (KeyError, ValueError, Conflict) as exc:
        raise HTTPException(404 if isinstance(exc, KeyError) else 409 if isinstance(exc, Conflict) else 400,
                            detail=str(exc)) from None


@router.get('')
def list_applications(request: Request):
    return invoke(request, 'list')


@router.post('')
def create_application(body: CreateApplication, request: Request):
    return invoke(request, 'create', **body.model_dump())


@router.get('/{application_id}')
def get_application(application_id: str, request: Request):
    return invoke(request, 'get', application_id)


@router.post('/{application_id}/events')
def append_event(application_id: str, body: ApplicationEventRequest, request: Request):
    return invoke(request, 'append', application_id, body.event.model_dump(mode='json'),
                  action_id=body.action_id, expected_revision=body.expected_revision)

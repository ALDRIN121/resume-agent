"""Shared career service adapters, mounted by the decision-flow integration."""
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import Field

from ...contracts import Continue, Contract
from ...run_store import Conflict

router = APIRouter(prefix='/api/jobs', tags=['jobs'])
evaluation_router = APIRouter(prefix='/api/evaluations', tags=['evaluations'])


class CaptureJob(Contract):
    text: str = Field(min_length=1, max_length=48000)
    source_key: str | None = None
    source_url: str | None = None
    company: str | None = None
    role: str | None = None


class EvaluateJob(Contract):
    answers: dict[str, str] = Field(default_factory=dict)
    user_text: dict[str, str] = Field(default_factory=dict)
    eligibility_facts: dict[str, str] = Field(default_factory=dict)


def failure(exc):
    return HTTPException(404 if isinstance(exc, KeyError) else 409 if isinstance(exc, Conflict) else 400, detail=str(exc))


@router.post('')
def capture(body: CaptureJob, request: Request):
    try:
        return request.app.state.services.jobs.capture(**body.model_dump()).model_dump(mode='json')
    except (ValueError, KeyError, Conflict) as exc:
        raise failure(exc) from None


@router.get('')
def list_jobs(request: Request):
    return [job.model_dump(mode='json') for job in request.app.state.services.jobs.list()]


@router.get('/{job_id}')
def get_job(job_id: str, request: Request):
    try:
        return request.app.state.services.jobs.get(job_id).model_dump(mode='json')
    except KeyError as exc:
        raise failure(exc) from None


@router.get('/{job_id}/origin')
def job_origin(job_id: str, request: Request):
    try:
        return request.app.state.services.discovery.job_origin(job_id)
    except (KeyError, ValueError, Conflict) as exc:
        raise failure(exc) from None


@router.post('/{job_id}/evaluations')
def create_evaluation(job_id: str, body: EvaluateJob, request: Request):
    try:
        return request.app.state.services.evaluations.create(job_id, **body.model_dump())
    except (KeyError, ValueError, Conflict) as exc:
        raise failure(exc) from None


@router.get('/{job_id}/evaluations')
def job_evaluations(job_id: str, request: Request):
    try:
        return request.app.state.services.evaluations.list_for_job(job_id)
    except (KeyError, ValueError, Conflict) as exc:
        raise failure(exc) from None


@evaluation_router.get('/{evaluation_id}')
def evaluation(evaluation_id: str, request: Request):
    try:
        return request.app.state.services.evaluations.get(evaluation_id)
    except (KeyError, ValueError, Conflict) as exc:
        raise failure(exc) from None


@evaluation_router.post('/{evaluation_id}/continue')
async def continue_evaluation(evaluation_id: str, request: Request, body: Continue | None = Body(default=None)):
    try:
        service = request.app.state.services.evaluations
        view = service.get(evaluation_id)
        if view['status'] == 'interrupted' and body is None:
            raise Conflict('explicit_continue_required')
        if view['status'] in ('failed', 'cancelled'):
            raise Conflict('new_evaluation_required')
        if view['status'] == 'complete':
            return view
        return await service.drive(evaluation_id, body)
    except (KeyError, ValueError, Conflict) as exc:
        raise failure(exc) from None


@evaluation_router.post('/{evaluation_id}/cancel')
def cancel_evaluation(evaluation_id: str, request: Request):
    try:
        return request.app.state.services.evaluations.cancel(evaluation_id)
    except (KeyError, ValueError, Conflict) as exc:
        raise failure(exc) from None

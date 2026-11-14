"""Library projections from durable runs and preserved legacy records."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ... import library
from ...outcomes import company_metrics

router = APIRouter(prefix='/api/library', tags=['library'])


@router.get('/companies')
async def list_companies(request: Request):
    services = request.app.state.services
    return company_metrics(request.app.state.run_manager.list_runs(), services.jobs.list(), services.applications.list())


@router.get('/resumes')
async def list_resumes(request: Request, company: str | None = None):
    return [record for record in request.app.state.run_manager.list_runs()
            if company is None or record['company'] == company]


@router.get('/resumes/{run_id}')
async def get_resume(run_id: str, request: Request):
    try:
        return request.app.state.run_manager.get_run(run_id)
    except KeyError:
        raise HTTPException(404, detail={'code': 'run_not_found'}) from None


@router.delete('/resumes/{run_id}', status_code=204)
async def delete_resume(run_id: str, request: Request):
    store = request.app.state.services.store
    if run_id in store.run_ids():
        raise HTTPException(409, detail={'code': 'reviewed_run_history_retained'})
    if not library.delete_resume(run_id, library_path=store.library_path):
        raise HTTPException(404, detail={'code': 'run_not_found'})

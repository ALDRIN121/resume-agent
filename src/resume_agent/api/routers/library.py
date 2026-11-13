"""Library projections from durable runs and preserved legacy records."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ... import library

router = APIRouter(prefix='/api/library', tags=['library'])


@router.get('/companies')
async def list_companies(request: Request):
    companies = {}
    for record in request.app.state.run_manager.list_runs():
        name = record['company']
        entry = companies.setdefault(name, {'name': name, 'total': 0, 'final': 0, 'needs': 0, 'failed': 0,
                                            'last_updated': record.get('created_at')})
        entry['total'] += 1
        entry['final'] += record['status'] == 'complete'
        entry['needs'] += record['status'] in ('awaiting-input', 'interrupted')
        entry['failed'] += record['status'] == 'failed'
    return list(companies.values())


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

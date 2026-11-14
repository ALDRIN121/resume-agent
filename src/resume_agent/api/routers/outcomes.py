from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...outcomes import metrics

router = APIRouter(tags=['outcomes'])


@router.get('/api/outcomes')
def outcomes(request: Request):
    return request.app.state.services.outcomes.report()


@router.get('/api/outcomes/export')
def export_outcomes(request: Request):
    return JSONResponse(request.app.state.services.outcomes.report(), headers={
        'Content-Disposition': 'attachment; filename="resume-agent-outcomes.json"'})


@router.get('/api/metrics')
def dashboard_metrics(request: Request):
    services = request.app.state.services
    return metrics(request.app.state.run_manager.list_runs(), services.jobs.list(), services.applications.list())

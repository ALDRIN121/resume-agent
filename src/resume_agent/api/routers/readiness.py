"""Local readiness evidence, with no paid provider probe."""
from fastapi import APIRouter, Request

router = APIRouter(prefix='/api/readiness', tags=['readiness'])


@router.get('')
async def readiness(request: Request) -> dict:
    return request.app.state.services.readiness()

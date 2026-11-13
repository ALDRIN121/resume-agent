"""Current profile and explicitly reviewed import HTTP adapters."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import (
    APIRouter,
    Body,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from ...config import MAX_RESUME_UPLOAD_BYTES
from ...contracts import AcceptImport, RejectImport
from ...imports import ImportInputError, ImportService
from ...profile_store import ProfileConflictError
from ...run_store import Conflict
from ...schemas import UserResume
from ..security import request_is_loopback

router = APIRouter(prefix='/api/resume', tags=['resume'])
ws_router = APIRouter()


@router.get('')
async def get_resume(request: Request):
    snapshot = request.app.state.services.profiles.load_snapshot()
    if snapshot is None:
        raise HTTPException(404, detail={'code': 'profile_not_found'})
    return snapshot.profile.model_dump(mode='json')


@router.get('/raw', response_class=PlainTextResponse)
async def get_resume_raw(request: Request):
    path = request.app.state.services.profiles.path
    if not path.exists():
        raise HTTPException(404, detail={'code': 'profile_not_found'})
    return PlainTextResponse(path.read_text(encoding='utf-8'))


@router.put('')
async def update_resume(request: Request, body: dict = Body(...)):
    profiles = request.app.state.services.profiles
    current = profiles.load_snapshot()
    if 'profile' in body:
        if set(body) - {'profile', 'expected_revision'}:
            raise HTTPException(422, detail={'code': 'invalid_profile_update'})
        expected = body.get('expected_revision')
        profile = body['profile']
    else:
        header = request.headers.get('if-match')
        expected = header.strip('"') if header else None
        profile = body
    if current is not None and expected is None:
        raise HTTPException(409, detail={'code': 'expected_profile_revision_required'})
    try:
        saved = profiles.save(expected, UserResume.model_validate(profile), {'source': 'explicit_profile_edit'})
    except ProfileConflictError:
        raise HTTPException(409, detail={'code': 'profile_conflict'}) from None
    return saved.profile.model_dump(mode='json')


@router.post('/upload')
async def upload_resume(request: Request, file: UploadFile = File(...)):
    raw = await file.read(MAX_RESUME_UPLOAD_BYTES + 1)
    if len(raw) > MAX_RESUME_UPLOAD_BYTES:
        raise HTTPException(413, detail={'code': 'upload_too_large'})
    service = request.app.state.services.imports
    try:
        created = service.create(raw, file.filename or '')
        draft = await service.drive(created['id'])
        return draft | {'job_id': draft['id'], 'operation_id': draft['id'], 'contract_version': 2}
    except ImportInputError as exc:
        raise HTTPException(400, detail={'code': exc.code}) from None


@ws_router.websocket('/ws/resume-parse/{job_id}')
async def resume_parse_events(websocket: WebSocket, job_id: str):
    if not request_is_loopback(websocket.headers.get('host'), websocket.headers.get('origin')):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        service = websocket.app.state.services.imports
        async for event in service.operations.subscribe(job_id):
            state = service.get(job_id)
            await websocket.send_json({'type': 'import_state', 'operation': state})
            if state['status'] != 'running':
                break
    except (WebSocketDisconnect, KeyError):
        pass
    finally:
        await websocket.close()


class CurrentProfileReview(BaseModel):
    expected_revision: str


def create_profile_router(service: ImportService) -> APIRouter:
    """Build private v2 adapters; T09 explicitly mounts this and switches clients.

    POST imports awaits create + drive and returns the durable review. GET includes
    complete extracted source, per-page warnings and draft; GET source downloads the
    original bytes. Accept/reject bodies use shared typed import action contracts.
    """
    profile_router = APIRouter(prefix="/api/profile", tags=["profile"])

    def http_error(exc: Exception) -> HTTPException:
        if isinstance(exc, KeyError):
            return HTTPException(404, detail={"code": "profile_import_not_found"})
        if isinstance(exc, ProfileConflictError):
            return HTTPException(409, detail={"code": exc.code})
        if isinstance(exc, Conflict):
            return HTTPException(409, detail={"code": str(exc)})
        return HTTPException(400, detail={"code": exc.code, "message": str(exc)})

    def snapshot_view(snapshot) -> dict:
        return {"profile": snapshot.profile.model_dump(mode="json"),
                "revision": snapshot.revision, "provenance": snapshot.provenance,
                "review_required": snapshot.review_required}

    @profile_router.get("")
    async def current_profile() -> dict:
        snapshot = await asyncio.to_thread(service.profiles.load_snapshot)
        if snapshot is None:
            raise HTTPException(404, detail={"code": "profile_not_found"})
        return snapshot_view(snapshot)

    @profile_router.post("/review")
    async def review_current_profile(action: CurrentProfileReview) -> dict:
        try:
            snapshot = await asyncio.to_thread(service.profiles.review_current_profile,
                                               action.expected_revision)
            return snapshot_view(snapshot)
        except ProfileConflictError as exc:
            raise http_error(exc) from None

    @profile_router.post("/imports", status_code=201)
    async def create_import(file: UploadFile = File(...)) -> dict:
        raw = await file.read(MAX_RESUME_UPLOAD_BYTES + 1)
        if len(raw) > MAX_RESUME_UPLOAD_BYTES:
            raise HTTPException(413, detail={"code": "upload_too_large", "message": "Upload exceeds 10 MiB"})
        try:
            created = await asyncio.to_thread(service.create, raw, file.filename or "")
            return await service.drive(created["id"])
        except (ImportInputError, ProfileConflictError, Conflict, KeyError) as exc:
            raise http_error(exc) from None

    @profile_router.get("/imports/{operation_id}")
    async def get_import(operation_id: str) -> dict:
        try:
            return await asyncio.to_thread(service.get, operation_id)
        except KeyError as exc:
            raise http_error(exc) from None

    @profile_router.get("/imports/{operation_id}/source")
    async def get_import_source(operation_id: str) -> Response:
        from urllib.parse import quote
        try:
            filename, raw = await asyncio.to_thread(service.read_source, operation_id)
        except KeyError as exc:
            raise http_error(exc) from None
        media_type = "application/pdf" if Path(filename).suffix.lower() == ".pdf" else "text/plain"
        return Response(raw, media_type=media_type, headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe="")})

    @profile_router.post("/imports/{operation_id}/accept")
    async def accept_import(operation_id: str, action: AcceptImport) -> dict:
        try:
            return await service.drive(operation_id, action)
        except (KeyError, Conflict, ProfileConflictError) as exc:
            raise http_error(exc) from None

    @profile_router.post("/imports/{operation_id}/reject")
    async def reject_import(operation_id: str, action: RejectImport) -> dict:
        try:
            return await service.drive(operation_id, action)
        except (KeyError, Conflict, ProfileConflictError) as exc:
            raise http_error(exc) from None

    return profile_router

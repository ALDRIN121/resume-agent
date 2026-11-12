"""Base resume REST endpoints."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from ...agents.base_resume_loader import parse_and_save_resume
from ...config import BASE_RESUME_FILE, MAX_RESUME_UPLOAD_BYTES, SOURCE_DIR
from ...contracts import AcceptImport, RejectImport
from ...imports import ImportInputError, ImportService
from ...llm import describe_llm_error
from ...profile_store import ProfileConflictError
from ...run_store import Conflict
from ...schemas import UserResume
from ..events import ResumeParseEvent, dump_event
from ..security import request_is_loopback

router = APIRouter(prefix="/api/resume", tags=["resume"])
ws_router = APIRouter()

_parse_jobs: dict[str, asyncio.Queue[ResumeParseEvent | None]] = {}
# Retain background parse tasks so they aren't garbage-collected mid-flight.
_parse_tasks: set[asyncio.Task[None]] = set()


@router.get("")
async def get_resume() -> dict[str, Any]:
    if not BASE_RESUME_FILE.exists():
        raise HTTPException(status_code=404, detail="No base resume has been parsed yet.")
    data = yaml.safe_load(BASE_RESUME_FILE.read_text(encoding="utf-8")) or {}
    return UserResume.model_validate(data).model_dump(mode="json")


@router.get("/raw", response_class=PlainTextResponse)
async def get_resume_raw() -> PlainTextResponse:
    if not BASE_RESUME_FILE.exists():
        raise HTTPException(status_code=404, detail="No base resume has been parsed yet.")
    return PlainTextResponse(BASE_RESUME_FILE.read_text(encoding="utf-8"))


@router.put("")
async def update_resume(resume: UserResume) -> dict[str, Any]:
    BASE_RESUME_FILE.parent.mkdir(parents=True, exist_ok=True)
    BASE_RESUME_FILE.write_text(
        yaml.dump(resume.model_dump(), default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    return resume.model_dump(mode="json")


@router.post("/upload")
async def upload_resume(file: UploadFile = File(...)) -> dict[str, str]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".tex"}:
        raise HTTPException(status_code=400, detail="Only .pdf and .tex resumes are supported.")

    raw = await file.read(MAX_RESUME_UPLOAD_BYTES + 1)
    if len(raw) > MAX_RESUME_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Resume upload exceeds 10 MiB.")

    job_id = str(uuid.uuid4())
    queue: asyncio.Queue[ResumeParseEvent | None] = asyncio.Queue()
    _parse_jobs[job_id] = queue

    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    dest = SOURCE_DIR / f"{job_id}{suffix}"
    dest.write_bytes(raw)

    task = asyncio.create_task(_parse_resume_job(job_id, dest, queue))
    _parse_tasks.add(task)
    task.add_done_callback(_parse_tasks.discard)
    return {"job_id": job_id}


@ws_router.websocket("/ws/resume-parse/{job_id}")
async def resume_parse_events(websocket: WebSocket, job_id: str) -> None:
    if not request_is_loopback(websocket.headers.get("host"), websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    queue = _parse_jobs.get(job_id)
    if queue is None:
        await websocket.close()
        return
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            await websocket.send_json(dump_event(event))
    except WebSocketDisconnect:
        pass
    finally:
        _parse_jobs.pop(job_id, None)


async def _parse_resume_job(
    job_id: str,
    source: Path,
    queue: asyncio.Queue[ResumeParseEvent | None],
) -> None:
    loop = asyncio.get_running_loop()
    active_stage = "upload"
    labels = {"upload": "Upload file", "extract": "Read document",
              "parse": "Understand resume", "write_yaml": "Save base resume"}

    def report(stage: str, status: str) -> None:
        nonlocal active_stage
        active_stage = stage
        event = ResumeParseEvent(stage_id=stage, label=labels[stage], status=status)
        loop.call_soon_threadsafe(queue.put_nowait, event)

    try:
        await queue.put(ResumeParseEvent(stage_id="upload", label=labels["upload"], status="done"))
        resume = await asyncio.to_thread(parse_and_save_resume, source, on_progress=report)
        await queue.put(
            ResumeParseEvent(
                stage_id="write_yaml",
                label=labels["write_yaml"],
                status="done",
                detail=resume.personal.full_name,
            )
        )
    except Exception as exc:
        await queue.put(
            ResumeParseEvent(
                stage_id=active_stage,
                label=labels[active_stage],
                status="failed",
                detail=describe_llm_error(exc),
            )
        )
    finally:
        await queue.put(None)


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

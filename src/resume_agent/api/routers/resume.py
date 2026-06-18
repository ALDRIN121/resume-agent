"""Base resume REST endpoints."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

from ...agents.base_resume_loader import parse_and_save_resume
from ...config import BASE_RESUME_FILE, SOURCE_DIR
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

    job_id = str(uuid.uuid4())
    queue: asyncio.Queue[ResumeParseEvent | None] = asyncio.Queue()
    _parse_jobs[job_id] = queue

    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    dest = SOURCE_DIR / f"{job_id}{suffix}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

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
    try:
        await queue.put(ResumeParseEvent(stage_id="upload", label="Uploading file", status="done"))
        await queue.put(ResumeParseEvent(stage_id="extract", label="Extracting resume text"))
        resume = await asyncio.to_thread(parse_and_save_resume, source)
        await queue.put(ResumeParseEvent(stage_id="extract", label="Extracting resume text", status="done"))
        await queue.put(
            ResumeParseEvent(
                stage_id="write_yaml",
                label="Writing base_resume.yaml",
                status="done",
                detail=resume.personal.full_name,
            )
        )
    except Exception as exc:
        await queue.put(
            ResumeParseEvent(
                stage_id="failed",
                label="Resume parsing failed",
                status="failed",
                detail=str(exc),
            )
        )
    finally:
        await queue.put(None)

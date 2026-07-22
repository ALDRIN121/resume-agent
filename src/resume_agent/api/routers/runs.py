"""Run lifecycle REST endpoints."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, model_validator

from ...agents.base_resume_loader import _extract_pdf_text
from ..run_manager import run_detail, run_manager, run_summary

router = APIRouter(prefix="/api/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    jd_text: str | None = None
    jd_url: str | None = None
    jd_file_id: str | None = None

    @model_validator(mode="after")
    def _must_have_input(self) -> CreateRunRequest:
        if not (self.jd_text or self.jd_url or self.jd_file_id):
            raise ValueError("Provide jd_text, jd_url, or jd_file_id.")
        return self


class ResumeRunRequest(BaseModel):
    kind: str
    payload: dict[str, Any] = {}


@router.post("")
async def create_run(request: CreateRunRequest) -> dict[str, str]:
    try:
        session = await run_manager.start_run(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"thread_id": session.thread_id}


@router.post("/jd-file")
async def upload_jd_file(file: UploadFile = File(...)) -> dict[str, Any]:
    """Extract job-description text from an uploaded .txt/.pdf and stash it,
    returning a one-time jd_file_id for POST /api/runs."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".txt"}:
        raise HTTPException(status_code=400, detail="Only .pdf and .txt job descriptions are supported.")

    raw = await file.read()
    if suffix == ".txt":
        text = raw.decode("utf-8", errors="ignore")
    else:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(raw)
            tmp.flush()
            text = _extract_pdf_text(Path(tmp.name))

    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract any text from that file.")

    file_id = run_manager.store_jd_file(text)
    return {"file_id": file_id, "chars": len(text)}


@router.get("")
async def list_runs() -> list[dict[str, Any]]:
    return [run_summary(session) for session in run_manager.list_runs()]


@router.get("/{thread_id}")
async def get_run(thread_id: str) -> dict[str, Any]:
    try:
        return run_detail(run_manager.get_run(thread_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{thread_id}/resume")
async def resume_run(thread_id: str, request: ResumeRunRequest) -> dict[str, Any]:
    try:
        session = await run_manager.resume_run(thread_id, request.model_dump())
        return run_summary(session)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404 if isinstance(exc, KeyError) else 409, detail=str(exc)) from exc


@router.post("/{thread_id}/cancel")
async def cancel_run(thread_id: str) -> dict[str, Any]:
    try:
        return run_summary(await run_manager.cancel(thread_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{thread_id}/pdf")
async def get_pdf(thread_id: str) -> FileResponse:
    try:
        session = run_manager.get_run(thread_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not session.pdf_path:
        raise HTTPException(status_code=404, detail="PDF is not ready for this run.")

    path = Path(session.pdf_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"PDF no longer exists at {path}.")

    return FileResponse(path, media_type="application/pdf", filename=path.name)

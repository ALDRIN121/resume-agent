"""Résumé library REST endpoints — companies + filed resumes for the web UI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ... import library

router = APIRouter(prefix="/api/library", tags=["library"])


@router.get("/companies")
async def list_companies() -> list[dict[str, Any]]:
    return library.list_companies()


@router.get("/resumes")
async def list_resumes(company: str | None = None) -> list[dict[str, Any]]:
    return library.list_resumes(company)


@router.get("/resumes/{thread_id}")
async def get_resume(thread_id: str) -> dict[str, Any]:
    record = library.get_resume(thread_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No résumé filed for {thread_id}.")
    return record


@router.delete("/resumes/{thread_id}", status_code=204)
async def delete_resume(thread_id: str) -> None:
    if not library.delete_resume(thread_id):
        raise HTTPException(status_code=404, detail=f"No résumé filed for {thread_id}.")

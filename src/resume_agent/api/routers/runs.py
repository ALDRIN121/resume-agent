"""Thin HTTP adapters over the shared durable run lifecycle."""
from __future__ import annotations

import io
from pathlib import Path

from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ... import library
from ...config import MAX_JD_TEXT_CHARS, MAX_RESUME_UPLOAD_BYTES
from ...run_store import Conflict
from ...schemas import WorkMode

router = APIRouter(prefix='/api/runs', tags=['runs'])


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    jd_text: str | None = None
    jd_url: str | None = None
    jd_file_id: str | None = None
    parent_run_id: str | None = None
    job_id: str | None = None
    evaluation_id: str | None = None
    evaluation_override: bool = False
    job_location: str | None = None
    work_mode: WorkMode | None = None
    max_pages: int = Field(default=2, ge=1, le=5)

    @model_validator(mode='after')
    def one_input(self):
        if sum(bool(v) for v in (self.jd_text, self.jd_url, self.jd_file_id)) != 1:
            raise ValueError('Provide exactly one of jd_text, jd_url, jd_file_id.')
        return self


class ContentPreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    review_id: str
    source_revision: str
    approved_ids: list[str]


class ReexportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action_id: str = Field(min_length=1)
    expected_pdf_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    recover: bool = False


def error(exc):
    status = 404 if isinstance(exc, KeyError) else 409 if isinstance(exc, Conflict) else 400
    return HTTPException(status, detail={'code': 'run_not_found' if status == 404 else str(exc)})


@router.post('')
async def create_run(body: CreateRunRequest, request: Request):
    try:
        return await request.app.state.run_manager.start_run(body.model_dump())
    except (ValueError, Conflict) as exc:
        raise error(exc) from None


@router.post('/jd-file')
async def upload_jd_file(request: Request, file: UploadFile = File(...)):
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in ('.pdf', '.txt'):
        raise HTTPException(400, detail={'code': 'unsupported_jd_file'})
    raw = await file.read(MAX_RESUME_UPLOAD_BYTES + 1)
    if len(raw) > MAX_RESUME_UPLOAD_BYTES:
        raise HTTPException(413, detail={'code': 'upload_too_large'})
    try:
        if suffix == '.txt':
            text = raw.decode('utf-8')
        else:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted or not reader.pages:
                raise ValueError('invalid_jd_pdf')
            text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception:
        raise HTTPException(400, detail={'code': 'unreadable_jd_file'}) from None
    if len(text) > MAX_JD_TEXT_CHARS:
        raise HTTPException(413, detail={'code': 'jd_input_too_large'})
    if not text.strip():
        raise HTTPException(400, detail={'code': 'empty_jd_file'})
    file_id = request.app.state.run_manager.store_jd_file(text)
    return {'file_id': file_id, 'chars': len(text), 'text': text}


@router.get('')
async def list_runs(request: Request):
    return request.app.state.run_manager.list_runs()


@router.get('/{run_id}')
async def get_run(run_id: str, request: Request):
    try:
        return request.app.state.run_manager.get_run(run_id)
    except KeyError as exc:
        raise error(exc) from None


@router.post('/{run_id}/resume')
async def resume_run(run_id: str, request: Request, body: dict = Body(...)):
    try:
        return await request.app.state.run_manager.resume_run(run_id, body)
    except ValueError:
        raise HTTPException(422, detail={'code': 'invalid_typed_action'}) from None
    except (KeyError, Conflict) as exc:
        raise error(exc) from None


@router.post('/{run_id}/content-preview')
async def content_preview(run_id: str, body: ContentPreviewRequest, request: Request):
    try:
        return request.app.state.services.workflow.content_preview(run_id, **body.model_dump())
    except (KeyError, ValueError, Conflict) as exc:
        raise error(exc) from None


@router.post('/{run_id}/cancel')
async def cancel_run(run_id: str, request: Request):
    try:
        return await request.app.state.run_manager.cancel(run_id)
    except (KeyError, Conflict) as exc:
        raise error(exc) from None


@router.get('/{run_id}/preview')
async def preview(run_id: str, request: Request):
    services = request.app.state.services
    try:
        view = services.runs.get(run_id)
        if view.pending is None or view.pending.kind != 'review_pdf':
            raise Conflict('current_pdf_review_required')
        data = services.release.get_preview(run_id)
        return Response(data, media_type='application/pdf', headers={
            'ETag': '"' + view.pending.review.pdf_hash + '"', 'Content-Disposition': 'inline',
            'Cache-Control': 'no-store'})
    except (KeyError, Conflict, OSError) as exc:
        raise error(exc) from None


@router.get('/{run_id}/pdf')
async def final_pdf(run_id: str, request: Request):
    services = request.app.state.services
    try:
        state = request.app.state.run_manager.get_run(run_id)
        if state.get('legacy'):
            # A legacy download is visibly labelled and never claims review hashes.
            with services.store.connection() as conn:
                row = conn.execute('SELECT pdf_path FROM resumes WHERE thread_id=?', (run_id,)).fetchone()
            if not row or not row[0] or Path(row[0]).is_symlink():
                raise Conflict('legacy_artifact_missing')
            data = Path(row[0]).read_bytes()
            headers = {'X-Resume-Artifact': 'legacy-unverified'}
        else:
            data = services.release.get_final(run_id)
            headers = {'ETag': '"' + state['release']['pdf_hash'] + '"'}
        return Response(data, media_type='application/pdf', headers={**headers,
            'Content-Disposition': 'attachment; filename="resume.pdf"'})
    except (KeyError, Conflict, OSError) as exc:
        raise error(exc) from None


@router.post('/{run_id}/recover')
async def recover_legacy(run_id: str, request: Request):
    try:
        return request.app.state.run_manager.recover_legacy(run_id)
    except (KeyError, Conflict, ValueError) as exc:
        raise error(exc) from None


@router.post('/{run_id}/artifact/relink')
async def relink_legacy(run_id: str, request: Request, body: dict = Body(...)):
    path = request.app.state.services.store.library_path
    try:
        if 'path' in body and set(body) == {'path'}:
            return library.inspect_legacy_artifact(run_id, Path(body['path']), library_path=path)
        return library.relink_legacy_artifact(run_id, library_path=path, **body)
    except (KeyError, Conflict, ValueError, TypeError) as exc:
        raise error(exc) from None


@router.post('/{run_id}/reexport')
async def reexport(run_id: str, request: Request, body: ReexportRequest):
    services = request.app.state.services
    try:
        state = request.app.state.run_manager.get_run(run_id)
        fixed = services.store.input('run', run_id)
        destination = dict(base_dir=services.settings.output_base_dir, company_name=state['company'],
                           user_full_name=fixed['profile_snapshot']['personal']['full_name'])
        if body.recover:
            with services.store.connection() as conn:
                previous = services.store.action('run_reexport', run_id, body.action_id, conn)
            if previous:
                import json
                saved = json.loads(previous['request_json'])
                destination = {key: saved[key] for key in destination}
        return services.release.reexport(run_id, **body.model_dump(), **destination)
    except (KeyError, Conflict, ValueError) as exc:
        raise error(exc) from None

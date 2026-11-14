"""Deterministic v2 rendering. Approved content is never sent to a writer.

Callers hold the per-run worker lock. Checkpoints are JSON dictionaries and may
be synchronous or asynchronous. A pending external call requires explicit
recovery; completed candidates are reopened only after their hashes validate.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined
from PIL import Image
from pypdf import PdfReader

from .artifacts import RunArtifacts, hash_file
from .content_review import verify_manifest
from .contracts import canonical_json, content_hash
from .schemas import RenderManifest
from .tools.pdf_to_images import pdf_to_images
from .tools.tectonic_compile import CompileResult, compile_latex

TEMPLATE_PATH = Path(__file__).parent / 'templates' / 'approved.tex.jinja'


class RenderError(Exception):
    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class Layout:
    layout_id: str
    font_size_pt: int
    margin_in: float
    paragraph_skip_pt: int
    group_skip_pt: int
    heading_skip_pt: int

    def parameters(self) -> dict:
        return asdict(self)


STANDARD = Layout('standard', 10, 0.65, 3, 5, 7)
COMPACT = Layout('compact', 10, 0.5, 1, 3, 4)
_LAYOUTS = (STANDARD, COMPACT)


@dataclass(frozen=True)
class RenderRecord:
    artifact_id: str
    attempt_number: int
    content_hash: str
    template_version: str
    template_hash: str
    layout: Layout
    render_hash: str
    source_path: str
    source_hash: str
    pdf_path: str
    pdf_hash: str
    log_path: str
    log_hash: str
    image_paths: tuple[str, ...]
    image_hashes: tuple[str, ...]
    page_count: int
    overflow: bool
    overfull_boxes: tuple[str, ...]

    @property
    def layout_id(self) -> str:
        return self.layout.layout_id

    @property
    def layout_params(self) -> dict:
        return self.layout.parameters()

    def to_dict(self) -> dict:
        value = asdict(self)
        value['layout_params'] = value.pop('layout')
        for key in ('image_paths', 'image_hashes', 'overfull_boxes'):
            value[key] = list(value[key])
        return value

    @classmethod
    def from_dict(cls, value: dict) -> RenderRecord:
        fields = dict(value)
        fields['layout'] = Layout(**fields.pop('layout_params'))
        for key in ('image_paths', 'image_hashes', 'overfull_boxes'):
            fields[key] = tuple(fields[key])
        return cls(**fields)


def render_identity(approved_hash: str, template_hash: str, layout: Layout) -> str:
    return content_hash({'content_hash': approved_hash, 'template_hash': template_hash,
                         'layout_params': layout.parameters()})


def escape_latex(text: str) -> str:
    """Encode TeX syntax once, without normalizing any visible characters."""
    escapes = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$',
               '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}',
               '~': r'\textasciitilde{}', '^': r'\textasciicircum{}',
               '\n': r'\newline{}', '\r': r'\newline{}', '\t': r'\hspace*{1em}'}
    return ''.join(escapes.get(character, character) for character in text)


def _source(manifest: RenderManifest, layout: Layout, template: bytes) -> str:
    lines = []
    previous_group = None
    for field in manifest.display_fields:
        group = (field.section, field.group)
        if field.visible_label is not None:
            lines.append({'text': escape_latex(field.visible_label), 'kind': 'field',
                          'group_start': group != previous_group})
        lines.append({'text': escape_latex(field.text), 'kind': field.kind,
                      'group_start': field.visible_label is None and group != previous_group})
        previous_group = group
    environment = Environment(undefined=StrictUndefined, autoescape=False,
                              keep_trailing_newline=True)
    return environment.from_string(template.decode('utf-8')).render(lines=lines, layout=layout)


def render_source(manifest: RenderManifest, layout: Layout = STANDARD) -> str:
    if not verify_manifest(manifest):
        raise RenderError('invalid_manifest', 'Approved content hash or display order is invalid.')
    if layout not in _LAYOUTS:
        raise RenderError('invalid_layout', 'Only standard and compact layouts are supported.')
    return _source(manifest, layout, TEMPLATE_PATH.read_bytes())


async def _call(callback, *args, **kwargs):
    if inspect.iscoroutinefunction(callback):
        return await callback(*args, **kwargs)
    # Wait for a running external call to finish even if the asyncio caller is
    # cancelled, so it cannot keep writing artifacts after cancellation returns.
    task = asyncio.create_task(asyncio.to_thread(callback, *args, **kwargs))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            cancelled = True
            if task.cancelled():
                raise
        except BaseException:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
    if cancelled:
        raise asyncio.CancelledError
    return await result if inspect.isawaitable(result) else result


async def _callback(callback, *args):
    result = callback(*args)
    return await result if inspect.isawaitable(result) else result


async def _cancel(check_cancelled):
    if check_cancelled is not None and await _callback(check_cancelled):
        raise RenderError('cancelled', 'Rendering was cancelled.')


async def _checkpoint(callback, check_cancelled, event):
    await _cancel(check_cancelled)
    if callback is not None:
        await _callback(callback, event)
    await _cancel(check_cancelled)


def _exclusive(path: Path, data: bytes):
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _store_json(path: Path, value: dict):
    _exclusive(path, canonical_json(value).encode('utf-8'))


def _check_hash(path: str | Path, expected: str):
    try:
        valid = hash_file(path) == expected
    except (OSError, ValueError):
        valid = False
    if not valid:
        raise RenderError('artifact_hash_mismatch', 'Stored render bytes changed.', path=str(path))


def _page_count(path: Path) -> int:
    try:
        # hash_file rejects nonregular files and final symlinks before parsing.
        hash_file(path)
        reader = PdfReader(path)
        if reader.is_encrypted or not reader.pages:
            raise ValueError('PDF is encrypted or has no pages')
        return len(reader.pages)
    except Exception as exc:
        raise RenderError('invalid_pdf', 'Compiled PDF is missing, malformed, encrypted, or empty.',
                          path=str(path)) from exc


def _validate_record(record: RenderRecord, manifest: RenderManifest, run: RunArtifacts,
                     template_hash: str, max_pages: int):
    attempt = run.attempt(record.attempt_number)
    if (record.artifact_id != run.artifact_id or record.content_hash != manifest.content_hash
            or record.template_hash != template_hash or record.template_version != manifest.template_version
            or record.layout not in _LAYOUTS
            or record.source_hash != hashlib.sha256(_source(manifest, record.layout, TEMPLATE_PATH.read_bytes()).encode('utf-8')).hexdigest()
            or record.render_hash != render_identity(manifest.content_hash, template_hash, record.layout)
            or record.source_path != str(attempt.source_path)
            or record.pdf_path != str(attempt.pdf_path) or record.log_path != str(attempt.log_path)
            or len(record.image_paths) != len(record.image_hashes)
            or len(record.image_paths) != record.page_count
            or len(set(record.image_paths)) != record.page_count
            or record.overflow or record.overfull_boxes or not 1 <= record.page_count <= max_pages):
        raise RenderError('artifact_hash_mismatch', 'Stored render identity is invalid.')
    for path, expected in ((record.source_path, record.source_hash),
                           (record.pdf_path, record.pdf_hash), (record.log_path, record.log_hash),
                           *zip(record.image_paths, record.image_hashes, strict=True)):
        if Path(path).resolve() != Path(path) or not Path(path).is_relative_to(attempt.attempt_dir):
            raise RenderError('artifact_hash_mismatch', 'Stored path escaped its owned attempt.')
        _check_hash(path, expected)
    if _page_count(attempt.pdf_path) != record.page_count:
        raise RenderError('artifact_hash_mismatch', 'Stored PDF page count changed.')
    for path in record.image_paths:
        try:
            if not Path(path).is_relative_to(attempt.images_dir):
                raise ValueError('Image escaped its owned image directory')
            with Image.open(path) as opened:
                opened.verify()
        except (OSError, ValueError) as exc:
            raise RenderError('artifact_hash_mismatch', 'Stored page image is invalid.') from exc


async def render_approved(
    manifest: RenderManifest, artifacts: RunArtifacts, *, max_pages: int = 2,
    compile_adapter=compile_latex, image_adapter=pdf_to_images,
    checkpoint=None, check_cancelled=None, recover_pending: bool = False,
    resume_record: RenderRecord | dict | None = None,
) -> RenderRecord:
    """Compile at most standard+compact, timeout-only retries, preserving every byte.

    compile_adapter(source: str, *, output_dir: Path) -> CompileResult;
    image_adapter(pdf_path: str, *, output_dir: Path) -> list[str]. Both may be
    async. checkpoint(event: dict) runs before/after each external boundary.
    check_cancelled() returns true or raises the driver's cancellation exception.
    recover_pending=True explicitly authorizes continuing unfinished work using
    a stored successful compile or allocating a new, never overwritten attempt.
    """
    if not verify_manifest(manifest):
        raise RenderError('invalid_manifest', 'Approved content hash or display order is invalid.')
    if type(max_pages) is not int or not 1 <= max_pages <= 5:
        raise RenderError('invalid_page_limit', 'Page limit must be from 1 through 5.')
    # Freeze a caller-owned mutable Pydantic object before any asynchronous work.
    manifest = RenderManifest.model_validate_json(manifest.model_dump_json())
    template = TEMPLATE_PATH.read_bytes()
    template_hash = hashlib.sha256(template).hexdigest()
    await _cancel(check_cancelled)
    if resume_record is not None:
        try:
            record = (RenderRecord.from_dict(resume_record) if isinstance(resume_record, dict)
                      else resume_record)
            _validate_record(record, manifest, artifacts, template_hash, max_pages)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise RenderError('artifact_hash_mismatch', 'Stored render record is invalid.') from exc
        return record

    history = []
    next_attempt = 1
    for directory in sorted((artifacts.run_dir / 'attempts').iterdir(), key=lambda p: int(p.name)):
        attempt = artifacts.attempt(int(directory.name))
        next_attempt = max(next_attempt, attempt.number + 1)
        try:
            if attempt.manifest_path.exists():
                value = json.loads(attempt.manifest_path.read_text())
                if 'record' in value:
                    record = RenderRecord.from_dict(value['record'])
                    _validate_record(record, manifest, artifacts, template_hash, max_pages)
                    return record
            compiled = attempt.attempt_dir / 'compile.json'
            if compiled.exists():
                value = json.loads(compiled.read_text())
                if (value['content_hash'] != manifest.content_hash
                        or value['template_hash'] != template_hash or value['max_pages'] != max_pages
                        or value['layout_params'] not in [layout.parameters() for layout in _LAYOUTS]):
                    raise RenderError('artifact_hash_mismatch', 'Stored compile identity changed.')
                layout = Layout(**value['layout_params'])
                if value['render_hash'] != render_identity(manifest.content_hash, template_hash, layout):
                    raise RenderError('artifact_hash_mismatch', 'Stored render hash changed.')
                _check_hash(attempt.source_path, value['source_hash'])
                _check_hash(attempt.log_path, value['log_hash'])
                if value['ok']:
                    _check_hash(attempt.pdf_path, value['pdf_hash'])
                    if _page_count(attempt.pdf_path) != value['page_count']:
                        raise RenderError('artifact_hash_mismatch', 'Stored page count changed.')
                history.append((attempt, value))
            else:
                if not recover_pending:
                    raise RenderError('recovery_required', 'An unfinished attempt requires explicit recovery.',
                                      attempt_number=attempt.number)
                request = attempt.attempt_dir / 'request.json'
                if request.exists():
                    value = json.loads(request.read_text())
                    if (value['content_hash'] != manifest.content_hash
                            or value['template_hash'] != template_hash or value['max_pages'] != max_pages
                            or value['layout_params'] not in [layout.parameters() for layout in _LAYOUTS]):
                        raise RenderError('artifact_hash_mismatch', 'Pending compile identity changed.')
                    _check_hash(attempt.source_path, value['source_hash'])
                    history.append((attempt, {**value, 'ok': False,
                                              'error_code': 'compile_interrupted', 'errors': []}))
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise RenderError('artifact_hash_mismatch', 'Stored render metadata is invalid.') from exc

    candidates = []
    for layout in _LAYOUTS:
        source = _source(manifest, layout, template)
        source_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
        render_hash = render_identity(manifest.content_hash, template_hash, layout)
        prior = [(attempt, value) for attempt, value in history
                 if value['layout_params'] == layout.parameters()]
        failures = [value for _, value in prior if not value['ok']]
        for failure in failures:
            if failure['error_code'] not in ('compile_timeout', 'compile_interrupted'):
                raise RenderError(failure['error_code'], 'Stored compile failure requires resolution.',
                                  errors=failure['errors'])
        successful = [(attempt, value) for attempt, value in prior if value['ok']]
        if len(successful) > 1:
            raise RenderError('artifact_hash_mismatch', 'Multiple successful compiles for one layout.')
        if successful:
            attempt, compiled = successful[0]
            if compiled['source_hash'] != source_hash:
                raise RenderError('artifact_hash_mismatch', 'Stored source differs from fixed template.')
        else:
            if len(failures) >= 3:
                code = ('compile_interrupted' if any(f['error_code'] == 'compile_interrupted'
                                                     for f in failures) else 'compile_timeout')
                raise RenderError(code, 'Persisted compiler attempt budget is exhausted.')
            for _ in range(len(failures), 3):
                await _cancel(check_cancelled)
                attempt = artifacts.attempt(next_attempt)
                next_attempt += 1
                _exclusive(attempt.source_path, source.encode('utf-8'))
                base = {'artifact_id': artifacts.artifact_id, 'attempt_number': attempt.number,
                        'content_hash': manifest.content_hash, 'template_hash': template_hash,
                        'render_hash': render_hash, 'layout_params': layout.parameters(),
                        'source_path': str(attempt.source_path), 'source_hash': source_hash,
                        'pdf_path': str(attempt.pdf_path), 'log_path': str(attempt.log_path),
                        'max_pages': max_pages}
                _store_json(attempt.attempt_dir / 'request.json', base)
                event = {**base, 'stage': 'compile', 'phase': 'before'}
                await _checkpoint(checkpoint, check_cancelled, event)
                try:
                    result = await _call(compile_adapter, source, output_dir=attempt.attempt_dir)
                except Exception as exc:
                    raw_log = (attempt.log_path.read_text(errors='replace')
                               if attempt.log_path.exists() else '')
                    result = CompileResult(False, None,
                                           [f'Compiler adapter failed ({type(exc).__name__}).'],
                                           raw_log, error_code='compile_environment')
                if not isinstance(result, CompileResult):
                    raise RenderError('compile_environment', 'Compiler adapter returned an invalid result.')
                raw_log = result.raw_log.encode('utf-8')
                if attempt.log_path.exists():
                    if attempt.log_path.read_bytes() != raw_log:
                        raise RenderError('artifact_hash_mismatch', 'Compiler log differs from its returned bytes.')
                else:
                    _exclusive(attempt.log_path, raw_log)
                overfull = re.findall(r'(?im)^.*Overfull\s+\\[hv]box\b.*$', result.raw_log)
                overfull = list(dict.fromkeys([*result.overfull_boxes, *overfull]))
                compiled = {**base, 'ok': result.ok, 'error_code': result.error_code or (None if result.ok else 'compile_environment'),
                            'errors': result.errors, 'log_hash': hash_file(attempt.log_path),
                            'overfull_boxes': overfull, 'overflow': bool(overfull) or result.overflow,
                            'pdf_hash': None, 'page_count': None}
                if result.ok:
                    try:
                        if result.pdf_path != str(attempt.pdf_path):
                            raise RenderError('invalid_pdf', 'Compiler output must use its run-owned PDF path.')
                        compiled['page_count'] = _page_count(attempt.pdf_path)
                        compiled['pdf_hash'] = hash_file(attempt.pdf_path)
                    except RenderError as exc:
                        compiled.update(ok=False, error_code=exc.code, errors=[str(exc)])
                _store_json(attempt.attempt_dir / 'compile.json', compiled)
                if not compiled['ok']:
                    attempt.write_manifest({'compile': compiled})
                await _checkpoint(checkpoint, check_cancelled,
                                  {**compiled, 'stage': 'compile', 'phase': 'after'})
                if compiled['ok']:
                    break
                if compiled['error_code'] != 'compile_timeout':
                    raise RenderError(compiled['error_code'], 'Compilation stopped.', errors=compiled['errors'])
            else:
                raise RenderError('compile_timeout', 'Transient compiler retry budget is exhausted.')

        if compiled['overflow'] or compiled['page_count'] > max_pages:
            candidates.append({'layout_id': layout.layout_id, 'page_count': compiled['page_count'],
                               'overflow': compiled['overflow'], 'overfull_boxes': compiled['overfull_boxes']})
            attempt.write_manifest({'compile': compiled})
            continue
        if successful and not recover_pending:
            raise RenderError('recovery_required', 'Compiled PDF requires explicit continuation to images.',
                              attempt_number=attempt.number)
        await _cancel(check_cancelled)
        # A crashed image call may have produced partial images. Preserve those
        # bytes and use a fresh subdirectory while reusing this exact PDF.
        image_number = 1
        while (attempt.images_dir / str(image_number)).exists():
            image_number += 1
        image_dir = attempt.images_dir / str(image_number)
        image_dir.mkdir()
        event = {**compiled, 'stage': 'images', 'phase': 'before', 'images_dir': str(image_dir)}
        await _checkpoint(checkpoint, check_cancelled, event)
        try:
            image_paths = await _call(image_adapter, str(attempt.pdf_path), output_dir=image_dir)
        except Exception as exc:
            raise RenderError('images_unavailable', 'PDF page images could not be rendered.') from exc
        await _checkpoint(checkpoint, check_cancelled, {**event, 'phase': 'after'})
        _check_hash(attempt.pdf_path, compiled['pdf_hash'])
        if (not isinstance(image_paths, (list, tuple)) or not image_paths
                or len(image_paths) != compiled['page_count'] or len(set(image_paths)) != len(image_paths)):
            raise RenderError('images_unavailable', 'PDF renderer did not return an image for every page.')
        image_hashes = []
        for path in image_paths:
            image = Path(path)
            if (not image.is_absolute() or image.resolve() != image
                    or not image.is_relative_to(image_dir) or not image.is_file() or not image.stat().st_size):
                raise RenderError('images_unavailable', 'Page image is missing or outside its owned directory.')
            try:
                with Image.open(image) as opened:
                    opened.verify()
                image_hashes.append(hash_file(image))
            except (OSError, ValueError) as exc:
                raise RenderError('images_unavailable', 'Rendered page image is invalid.') from exc
        record = RenderRecord(
            artifacts.artifact_id, attempt.number, manifest.content_hash, manifest.template_version,
            template_hash, layout, render_hash, str(attempt.source_path), source_hash,
            str(attempt.pdf_path), compiled['pdf_hash'], str(attempt.log_path), compiled['log_hash'],
            tuple(image_paths), tuple(image_hashes), compiled['page_count'], compiled['overflow'],
            tuple(compiled['overfull_boxes']))
        _validate_record(record, manifest, artifacts, template_hash, max_pages)
        attempt.write_manifest({'record': record.to_dict()})
        return record
    raise RenderError('layout_limit_exceeded', 'Neither supported layout fits the approved content.',
                      candidates=candidates,
                      remedies=['Start a new run with a higher page limit (up to 5).',
                                'Review a new content revision with explicit display omissions.'])


@dataclass(frozen=True)
class AdvisoryRecord:
    source: str
    status: str
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {'source': self.source, 'status': self.status, 'diagnostics': list(self.diagnostics)}


def lint_approved(manifest: RenderManifest) -> AdvisoryRecord:
    """Observe approved fields without normalization or routing feedback."""
    if not verify_manifest(manifest):
        raise RenderError('invalid_manifest', 'Approved content hash or display order is invalid.')
    seen = set()
    warnings = []
    for field in manifest.display_fields:
        if field.text in seen:
            warnings.append(f'Repeated displayed text at order {field.order}; retained as approved.')
        seen.add(field.text)
    return AdvisoryRecord('lint', 'warning' if warnings else 'pass', tuple(warnings))


async def review_advisory(source: str, value: Any, *, reviewer=None,
                          check_cancelled=None) -> AdvisoryRecord:
    """Preserve diagnostic status; never return content, edits, or route flags."""
    await _cancel(check_cancelled)
    if reviewer is None:
        return AdvisoryRecord(source, 'disabled')
    try:
        result = await _call(reviewer, value)
    except Exception as exc:
        await _cancel(check_cancelled)
        return AdvisoryRecord(source, 'unavailable', (f'Review unavailable ({type(exc).__name__}).',))
    await _cancel(check_cancelled)
    if isinstance(result, str):
        return AdvisoryRecord(source, 'pass' if result.strip().upper() == 'PASS' else 'warning',
                              () if result.strip().upper() == 'PASS' else (result,))
    if isinstance(result, dict):
        status = result.get('status')
        diagnostics = result.get('diagnostics', [])
        if (status in ('pass', 'warning', 'unavailable', 'disabled')
                and isinstance(diagnostics, list) and all(isinstance(item, str) for item in diagnostics)):
            return AdvisoryRecord(source, status, tuple(diagnostics))
    return AdvisoryRecord(source, 'unavailable', ('Reviewer returned an invalid advisory record.',))

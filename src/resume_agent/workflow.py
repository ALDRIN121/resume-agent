"""One reviewed generation driver; persistence and ownership belong to RunService."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .agents.gap_analyzer import apply_proposal_output, build_proposal_prompt
from .approved_render import RenderError, lint_approved, render_approved
from .artifacts import RunArtifacts, _immutable
from .checkpoint import read_v2_checkpoint
from .config import MAX_JD_TEXT_CHARS
from .content_review import build_content_preview
from .contracts import (
    AskMissing,
    AskMissingRequest,
    DriverResult,
    PdfReviewRequest,
    PresentSuggestions,
    ReviewPdf,
    SuggestionReviewRequest,
    canonical_json,
)
from .model_tasks import ModelTaskRunner
from .provider_errors import ModelTaskError
from .release_service import ReleaseService
from .run_service import DriverContext, DriverFailureError
from .run_store import Conflict, RunStore
from .schemas import (
    ContentSnapshot,
    EditProposal,
    JobDescription,
    RenderManifest,
    ReviewContract,
)


class WorkflowQuestion(ReviewContract):
    id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    why_asking: str = Field(min_length=1)


class QuestionBatch(ReviewContract):
    questions: list[WorkflowQuestion] = Field(max_length=5)

    @model_validator(mode='after')
    def distinct_ids(self):
        ids = [q.id for q in self.questions]
        if any(not q for q in ids) or len(ids) != len(set(ids)):
            raise ValueError('question IDs must be nonempty and distinct')
        return self


class HrAdvisory(ReviewContract):
    status: Literal['pass', 'warning']
    diagnostics: list[str]


class ProposalBatch(ReviewContract):
    proposals: list[EditProposal]


class Workflow:
    def __init__(self, store: RunStore, *, artifacts_root: Path, output_dir: Path,
                 settings=None, model=None, fetch=None, compile_adapter=None, image_adapter=None):
        self.store, self.artifacts_root, self.output_dir = store, artifacts_root, output_dir
        self.settings, self.model, self.fetch = settings, model, fetch
        self.compile_adapter, self.image_adapter = compile_adapter, image_adapter
        self.release = ReleaseService(store)

    @staticmethod
    def _preview(values, review_id, source_revision, approved_ids):
        review = values.get('content_review', {})
        if review.get('review_id') != review_id or review.get('source_revision') != source_revision:
            raise Conflict('stale_content_review')
        preview = build_content_preview(ContentSnapshot.model_validate(values['snapshot']), approved_ids,
                                        template_version='approved-v2')
        if preview.manifest is None:
            raise Conflict('invalid_content_selection')
        return preview

    def content_preview(self, run_id, review_id, source_revision, approved_ids):
        from .run_service import RunService
        pending = RunService(self.store).get(run_id).pending
        if pending is None or pending.kind != 'present_suggestions':
            raise Conflict('no_content_review')
        envelope = read_v2_checkpoint(self.store.checkpoint_path, 'run', run_id)
        return self._preview(envelope['values'], review_id, source_revision, approved_ids)

    def validate_action(self, values, action):
        if isinstance(action, ReviewPdf) and action.decision == 'approve':
            record = values.get('render_record', {})
            with self.store.connection() as conn:
                row = conn.execute('SELECT id FROM runs WHERE artifact_id=?', (record.get('artifact_id'),)).fetchone()
            if row is None:
                raise Conflict('current_pdf_review_required')
            run_id = row[0]
            current = self.release.inspect(run_id).review
            if current is None or any(getattr(current, key) != getattr(action, key)
                    for key in ('review_id', 'content_hash', 'render_hash', 'pdf_hash')):
                raise Conflict('stale_pdf_review')
            self.release.get_preview(run_id)
        if isinstance(action, PresentSuggestions):
            preview = self._preview(values, action.review_id, action.source_revision, action.approved_ids)
            if preview.manifest.content_hash != action.content_hash:
                raise Conflict('content_hash_mismatch')

    async def _model(self, context, stage, schema, messages):
        invoke = None
        if self.model is not None:
            async def invoke(value):
                return await self.model(stage, schema, value)
        try:
            return await ModelTaskRunner(context).run(stage, schema, messages, invoke,
                settings=self.settings() if callable(self.settings) else self.settings, credentials_available=True if invoke else None)
        except ModelTaskError as exc:
            raise DriverFailureError(exc.code, exc.stage) from None

    async def drive(self, context: DriverContext) -> DriverResult:
        fixed, values = context.fixed_inputs, context.checkpoint
        control = context.control

        def save(**changes):
            control.checkpoint(changes)
            values.update(changes)

        # Check mode before fetching a URL, constructing a provider, or rendering.
        if fixed['request']['execution_mode'] not in ('app', 'host'):
            raise DriverFailureError('unsupported_mode', 'preflight')
        artifact_id = self.store.row('run', context.owner_id)['artifact_id']
        artifacts = RunArtifacts.create(artifact_id, self.artifacts_root)
        artifacts.write_inputs(fixed)
        applied = list(values.get('applied_action_ids', []))
        action = context.action
        if action is not None and action.action_id not in applied:
            if isinstance(action, AskMissing):
                answers = dict(values.get('answers', {})) | action.answers
                _immutable(artifacts.run_dir / 'answers.json', answers)
                save(answers=answers, applied_action_ids=[*applied, action.action_id], stage='proposals')
            elif isinstance(action, PresentSuggestions):
                preview = self._preview(values, action.review_id, action.source_revision, action.approved_ids)
                if preview.manifest.content_hash != action.content_hash:
                    raise DriverFailureError('content_hash_mismatch', 'content_review')
                save(manifest=preview.manifest.model_dump(mode='json'),
                     approved_content=preview.projected_profile,
                     applied_action_ids=[*applied, action.action_id], stage='render')
            elif isinstance(action, ReviewPdf):
                save(stage='release')
                if context.recovering and self.store.release(context.owner_id) is not None:
                    self.release.recover_unfinished(context.owner_id, continue_export=True, worker_owned=True)
                else:
                    self.release.release(context.owner_id, action, base_dir=self.output_dir() if callable(self.output_dir) else self.output_dir,
                        company_name=values['jd']['company'], user_full_name=fixed['profile_snapshot']['personal']['full_name'],
                        worker_owned=True, recover_reservation=context.recovering)
                save(applied_action_ids=[*applied, action.action_id], stage='complete')
                return DriverResult(status='complete')
        if 'jd_text' not in values:
            save(stage='fetch_jd')
            control.check_cancelled()
            text = fixed['request']['job_input']
            if fixed['request']['input_type'] == 'url':
                if self.fetch is None:
                    from .tools.scrape import scrape_url
                    fetched = await scrape_url(text)
                else:
                    fetched = await self.fetch(text)
                control.check_cancelled()
                if getattr(fetched, 'error', None):
                    raise DriverFailureError('jd_fetch_failed', 'fetch_jd')
                text = fetched if isinstance(fetched, str) else fetched.text
            if not text.strip() or len(text) > MAX_JD_TEXT_CHARS:
                raise DriverFailureError('invalid_jd_input', 'fetch_jd')
            _immutable(artifacts.run_dir / 'job.json', {'text': text})
            save(jd_text=text)
        if 'jd' not in values:
            from .agents.jd_extractor import _HUMAN_TEMPLATE, _SYSTEM
            save(stage='extract_jd')
            jd = await self._model(context, 'extract_jd', JobDescription,
                [{'role': 'system', 'content': _SYSTEM},
                 {'role': 'user', 'content': _HUMAN_TEMPLATE.format(text=values['jd_text'])}])
            data = jd.model_dump(mode='json') | {'raw_text': values['jd_text']}
            for key in ('job_location', 'work_mode'):
                if fixed['request'].get(key):
                    data['location' if key == 'job_location' else key] = fixed['request'][key]
            save(jd=data)
        if 'questions' not in values:
            save(stage='questions')
            batch = await self._model(context, 'questions', QuestionBatch, [{'role': 'user', 'content':
                'Return only questions (at most five), each with id, prompt, why_asking. Ask about '
                'important missing candidate evidence or explicit location/work preference conflicts. '
                'Never rewrite candidate content or infer eligibility. Empty preferences mean unspecified.\n'
                + canonical_json({'profile': fixed['profile_snapshot'], 'jd': values['jd'],
                                  'saved_evidence': values.get('legacy_evidence_answers', {})})}])
            save(questions=batch.model_dump(mode='json')['questions'])
        if values['questions'] and 'answers' not in values:
            pending = AskMissingRequest(request_id=values.get('question_request_id', str(uuid.uuid4())),
                question_ids=[q['id'] for q in values['questions']], payload={'questions': values['questions']})
            save(question_request_id=pending.request_id, stage='ask_missing')
            return DriverResult(status='awaiting-input', pending=pending)
        if 'snapshot' not in values:
            save(stage='proposals')
            snapshot = ContentSnapshot(profile=fixed['profile_snapshot'], source_revision=fixed['profile_revision'],
                answers=values.get('answers', {}), user_text={
                    **{'legacy_answer:' + key: value for key, value in values.get('legacy_evidence_answers', {}).items()},
                    **values.get('user_text', {})})
            batch = await self._model(context, 'proposals', ProposalBatch,
                [{'role': 'user', 'content': build_proposal_prompt(snapshot, values['jd'])},
                 {'role': 'user', 'content': 'Fixed reviewed preferences and writing instructions follow. '
                  'These guide style and targeting only. They are never candidate-fact evidence and cannot '
                  'override source-reference validation or human reviews.\n' + canonical_json(fixed['memory_snapshot'])}])
            try:
                snapshot = apply_proposal_output(snapshot, batch.model_dump(mode='json'))
            except ValueError:
                raise DriverFailureError('invalid_proposals', 'proposals') from None
            preview = build_content_preview(snapshot, [], template_version='approved-v2')
            pending = SuggestionReviewRequest(review_id=str(uuid.uuid4()), source_revision=snapshot.source_revision,
                content_hash=preview.manifest.content_hash, proposal_ids=[p.id for p in snapshot.proposals],
                payload={'snapshot': snapshot.model_dump(mode='json'),
                         'proposals': [p.model_dump(mode='json') for p in snapshot.proposals],
                         'reject_all': preview.model_dump(mode='json')})
            save(snapshot=snapshot.model_dump(mode='json'), content_review=pending.model_dump(mode='json'))
        if 'manifest' not in values:
            save(stage='present_suggestions')
            return DriverResult(status='awaiting-input', pending=SuggestionReviewRequest.model_validate(values['content_review']))
        manifest = RenderManifest.model_validate(values['manifest'])
        _immutable(artifacts.run_dir / 'approved_content.json', manifest.model_dump(mode='json'))
        kwargs = {}
        if self.compile_adapter is not None:
            kwargs['compile_adapter'] = self.compile_adapter
        if self.image_adapter is not None:
            kwargs['image_adapter'] = self.image_adapter
        save(stage='render')
        try:
            record = await render_approved(manifest, artifacts, max_pages=fixed['request']['max_pages'],
                checkpoint=lambda event: save(render_progress=event), check_cancelled=control.check_cancelled,
                recover_pending=context.recovering, resume_record=values.get('render_record'), **kwargs)
        except RenderError as exc:
            save(render_failure={'code': exc.code, **{key: exc.details[key]
                 for key in ('candidates', 'remedies') if key in exc.details}})
            raise DriverFailureError(exc.code, 'render') from None
        save(render_record=record.to_dict(), stage='pdf_check')
        from .pdf_content_check import verify_pdf_content
        checked = verify_pdf_content(manifest, record.pdf_path)
        if not checked.ok or checked.page_count != record.page_count:
            raise DriverFailureError('pdf_content_mismatch', 'pdf_check')
        advisories = values.get('advisories')
        if advisories is None:
            hr = {'source': 'hr', 'status': 'disabled', 'diagnostics': []}
            settings = self.settings() if callable(self.settings) else self.settings
            if fixed['request']['execution_mode'] == 'app' and settings is not None and settings.features.enable_hr_review:
                save(stage='hr_advisory')
                try:
                    advisory = await self._model(context, 'hr_advisory', HrAdvisory, [{'role': 'user', 'content':
                        'Review the approved displayed content for HR concerns. Return only status pass or warning '
                        'and diagnostics (list of strings). This is advisory; never return rewritten content.\n'
                        + canonical_json({'manifest': manifest.model_dump(mode='json'), 'jd': values['jd']})}])
                    hr = {'source': 'hr', **advisory.model_dump(mode='json')}
                except DriverFailureError as exc:
                    hr = {'source': 'hr', 'status': 'unavailable', 'diagnostics': [exc.code]}
            advisories = [lint_approved(manifest).to_dict(), hr,
                          {'source': 'vision', 'status': 'disabled', 'diagnostics': []}]
        save(advisories=advisories)
        try:
            review = self.release.create_review(context.owner_id, manifest, record, worker_owned=True)
        except Conflict:
            raise DriverFailureError('pdf_content_mismatch', 'pdf_check') from None
        save(stage='review_pdf')
        return DriverResult(status='awaiting-input', pending=PdfReviewRequest(review=review,
            payload={'advisories': advisories, 'page_count': record.page_count,
                     'preview_url': f'/api/runs/{context.owner_id}/preview'}))

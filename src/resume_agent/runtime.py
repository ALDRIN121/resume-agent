"""Explicit app/CLI composition with no mutable global persistence authority."""
from __future__ import annotations

import shutil
from pathlib import Path

from . import library
from .config import CONFIG_DIR, ResumeAgentSettings
from .contracts import content_hash
from .imports import ImportService
from .job_store import JobStore
from .memory import MemoryService
from .model_tasks import ModelTaskRunner
from .profile_store import ProfileStore
from .provider_errors import ModelTaskError
from .release_service import ReleaseService
from .role_evaluation import EvaluationService
from .run_service import DriverFailureError, RunService
from .run_store import Conflict, RunStore
from .schemas import UserResume
from .workflow import Workflow


class Runtime:
    def __init__(self, *, root: Path = CONFIG_DIR, settings=None, model=None, fetch=None,
                 compile_adapter=None, image_adapter=None, tool_finder=shutil.which):
        self.root = Path(root).resolve()
        self._settings_override = settings
        self.tool_finder, self.model = tool_finder, model
        # Library eligibility/import must happen before RunStore creates the DB.
        library.init_db(library_path=self.root / 'library.sqlite', history_file=self.root / 'run_history.jsonl')
        self.store = RunStore(self.root / 'library.sqlite', self.root / 'state.sqlite')
        self.profiles = ProfileStore(self.root / 'base_resume.yaml')
        self.memory = MemoryService(self.store, self.profiles)
        self.jobs = JobStore(self.store)
        self.evaluations = EvaluationService(self.store, self.jobs, self.profiles, self.memory,
                                            settings=lambda: self.settings, model=model)
        if compile_adapter is None:
            compile_adapter = self._compile
        self.workflow = Workflow(self.store, artifacts_root=self.root / 'runs',
            output_dir=lambda: self.settings.output_base_dir, settings=lambda: self.settings, model=model, fetch=fetch,
            compile_adapter=compile_adapter, image_adapter=image_adapter)
        self.runs = RunService(self.store, driver=self.workflow.drive,
                               action_validator=self.workflow.validate_action)
        self.runs.reconcile_startup()
        self.release = ReleaseService(self.store)
        self.imports = ImportService(self.store, self.profiles, context_parser=self._parse_import,
            model_selection=lambda: {'provider': self.settings.provider, 'model': self.settings.model.default})

    @property
    def settings(self):
        return self._settings_override if self._settings_override is not None else ResumeAgentSettings.load()

    def _compile(self, source, *, output_dir):
        from .tools.tectonic_compile import compile_latex
        current = self.settings
        return compile_latex(source, output_dir=output_dir, tectonic_path=current.latex.tectonic_path,
                             timeout=current.latex.compile_timeout_seconds)

    async def _parse_import(self, context, text):
        from .agents.base_resume_loader import _HUMAN_TEMPLATE, _SYSTEM
        invoke = None
        if self.model is not None:
            async def invoke(messages):
                return await self.model('import_profile', UserResume, messages)
        try:
            return await ModelTaskRunner(context).run('import_profile', UserResume,
                [{'role': 'system', 'content': _SYSTEM},
                 {'role': 'user', 'content': _HUMAN_TEMPLATE.format(text=text)}], invoke,
                settings=self.settings, credentials_available=True if invoke else None)
        except ModelTaskError as exc:
            raise DriverFailureError(exc.code, exc.stage) from None

    def readiness(self):
        try:
            snapshot = self.profiles.load_snapshot()
            profile_status = ('missing' if snapshot is None else 'review_required' if snapshot.review_required else 'ready')
        except (ValueError, OSError):
            profile_status = 'invalid'
        provider = self.settings.provider
        configured = provider == 'ollama' or bool(getattr(self.settings, f'{provider}_api_key', None))
        checks = {
            'profile': {'status': profile_status},
            'provider': {'status': 'configured_unverified' if configured else 'missing',
                         'provider': provider, 'model': self.settings.model.default, 'authentication_verified': False},
            'parser': {'status': 'ready'},
            'compiler': {'status': 'ready' if self.tool_finder(self.settings.latex.tectonic_path) else 'missing'},
            'renderer': {'status': 'ready' if all(self.tool_finder(t) for t in ('pdftoppm', 'pdfinfo')) else 'missing'},
        }
        steps = []
        if profile_status != 'ready':
            steps.append('Import a resume and review its draft.' if profile_status == 'missing' else 'Review the current profile before generation.')
        if not configured:
            steps.append('Configure the selected provider credentials.')
        if checks['compiler']['status'] != 'ready':
            steps.append('Install Tectonic to compile the PDF.')
        if checks['renderer']['status'] != 'ready':
            steps.append('Install Poppler (pdftoppm and pdfinfo) to preview every PDF page.')
        return {'contract_version': 2, **checks, 'generation_ready': not steps, 'next_steps': steps,
                'execution_modes': ['app']}

    def create_run(self, request):
        if request.evaluation_id and not request.job_id:
            raise Conflict('selected_job_required')
        if request.job_id:
            job = self.jobs.get(request.job_id)
            if request.input_type != 'text' or request.job_input != job.text:
                raise Conflict('selected_job_text_mismatch')
            if request.evaluation_id:
                evaluation = self.evaluations.get(request.evaluation_id)
                if evaluation['job_id'] != job.id:
                    raise Conflict('evaluation_job_mismatch')
                if evaluation['status'] != 'complete' or evaluation['result'] is None:
                    raise Conflict('completed_evaluation_required')
                if (evaluation['stale'] or evaluation['result']['fit']['recommendation'] != 'prioritize') and not request.evaluation_override:
                    raise Conflict('explicit_evaluation_override_required')
        readiness = self.readiness()
        if not readiness['generation_ready']:
            raise Conflict('generation_not_ready')
        snapshot = self.profiles.load_snapshot()
        if snapshot is None or snapshot.review_required:
            raise Conflict('profile_review_required')
        provenance_keys = {"profile_revision", "reviewed_revision", "reviewed_at", "import_id",
                           "action_id", "review_id", "draft_hash", "source_sha256", "intentionally_blank_pages",
                           "memory_id", "source_run"}
        provenance = {key: value for key, value in (snapshot.provenance or {}).items() if key in provenance_keys}
        memory = self.memory.snapshot()
        return self.runs.create(request, profile_snapshot=snapshot.profile, profile_revision=snapshot.revision,
                                profile_provenance=provenance,
                                memory_snapshot=memory, memory_revision=content_hash(memory),
                                provider=self.settings.provider, model=self.settings.model.default)

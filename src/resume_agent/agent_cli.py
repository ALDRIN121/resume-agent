"""One JSON result per invocation of the shared durable workflow."""
from __future__ import annotations

import asyncio
import json
import math
import sys
from contextlib import redirect_stdout
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from .agent_schemas import (
    AgentEnvelope,
    AgentError,
    DomainInput,
    EmptyInput,
    EvaluateInput,
    ImportInput,
    PostingsInput,
    Resource,
    StartInput,
)
from .api.routers.applications import CreateApplication
from .api.routers.discovery import CancelSync, ConfigureSources, CreateSync
from .api.routers.memory import MemoryDecision
from .api.routers.runs import ContentPreviewRequest, ReexportRequest
from .api.v2_manager import V2RunManager, typed_action
from .applications import ApplicationEventRequest
from .contracts import ACTION_ADAPTER, Continue, RunRequest
from .memory import MemoryProposal
from .run_store import Conflict

COMMANDS = {'start', 'inspect', 'respond', 'cancel', 'export', 'import', 'evaluate', 'discover', 'memory', 'application'}
MAX_FILE_BYTES = 10 * 1024 * 1024


class MissingPrerequisiteError(ValueError):
    pass


def read_file(path):
    try:
        with Path(path).open('rb') as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
    except OSError:
        raise ValueError('input_file_could_not_be_read') from None
    if len(data) > MAX_FILE_BYTES:
        raise ValueError('input_file_exceeds_10_mib')
    return data


def read_input(path):
    if path is None:
        return {}
    def finite(value):
        raise ValueError('non_finite_json')
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('non_finite_json')
        return result
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    value = json.loads(read_file(path).decode('utf-8'), parse_constant=finite, parse_float=finite_float, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError('input_must_be_object')
    return value


def parse_resource(value):
    if value is None:
        return None
    kind, separator, identifier = value.partition(':')
    if not separator:
        raise ValueError('resource_requires_kind_and_id')
    return Resource(kind=kind, id=identifier)


def require(resource, kind=None):
    if resource is None or (kind is not None and resource.kind != kind):
        raise ValueError('matching_resource_required')
    return resource.id


def configured_mode(value):
    if value != 'configured_provider':
        raise MissingPrerequisiteError('external_agent_not_available')
    return 'app'


def inspect(runtime, resource):
    identifier = require(resource)
    return {
        'run': lambda: V2RunManager(runtime).get_run(identifier),
        'profile_import': lambda: runtime.imports.get(identifier),
        'role_evaluation': lambda: runtime.evaluations.get(identifier),
        'discovery_sync': lambda: runtime.discovery.get_sync(identifier),
        'application': lambda: runtime.applications.get(identifier),
        'memory': lambda: runtime.memory.get(identifier),
    }[resource.kind]()


def next_action(resource, data):
    if resource is None or not isinstance(data, dict):
        return None
    if data.get('status') in ('failed', 'cancelled', 'complete', 'partial', 'empty'):
        return None
    if resource.kind in ('run', 'profile_import', 'role_evaluation'):
        if data.get('pending'):
            return data['pending']
        if data.get('status') in ('queued', 'pending_model'):
            return {'kind': 'execute', 'command': 'respond', 'requires_explicit_action': True}
        if data.get('status') == 'interrupted':
            return {'kind': 'continue', 'requires_explicit_action': True}
    if resource.kind == 'discovery_sync' and data.get('status') in ('queued', 'interrupted'):
        return {'kind': 'continue', 'requires_explicit_action': True}
    if resource.kind == 'memory':
        record = data.get('record', data)
        if record.get('status') == 'pending':
            return {'kind': 'memory_decision', 'expected_revision': record['revision'], 'choices': ['accept', 'reject']}
    return None


async def respond(runtime, resource, body):
    identifier = require(resource)
    if resource.kind == 'run':
        await runtime.runs.drive(identifier, typed_action(body) if body else None)
    elif resource.kind == 'profile_import':
        await runtime.imports.drive(identifier, ACTION_ADAPTER.validate_python(body) if body else None)
    elif resource.kind == 'role_evaluation':
        # Evaluation has no import/content/PDF review action.
        await runtime.evaluations.drive(identifier, Continue.model_validate(body) if body else None)
    elif resource.kind == 'discovery_sync':
        await runtime.discovery.drive(identifier, continue_action_id=Continue.model_validate(body).action_id)
    else:
        raise ValueError('use_explicit_domain_command')
    return inspect(runtime, resource)


async def domain(runtime, command, resource, body, publish):
    request = DomainInput.model_validate(body)
    op, payload = request.op, request.payload
    if resource is not None and op in ('sources', 'list', 'configure', 'postings', 'refresh', 'propose', 'create'):
        raise ValueError('operation_has_no_existing_resource')
    if command == 'discover':
        service = runtime.discovery
        if op in ('sources', 'list'):
            EmptyInput.model_validate(payload)
            return (service.sources() if op == 'sources' else service.list_syncs()), None
        if op == 'configure':
            value = ConfigureSources.model_validate(payload)
            return service.replace_sources([s.model_dump(mode='json', exclude_none=True) for s in value.sources],
                expected_revision=value.expected_revision, action_id=value.action_id), None
        if op == 'postings':
            return service.postings_page(**PostingsInput.model_validate(payload).model_dump()), None
        if op == 'refresh':
            created = service.create_sync(**CreateSync.model_validate(payload).model_dump())
            resource = Resource(kind='discovery_sync', id=created['id'])
            publish(resource)
            return await service.drive(created['id']), resource
        identifier = require(resource, 'discovery_sync')
        if op == 'inspect':
            EmptyInput.model_validate(payload)
            return service.get_sync(identifier), resource
        if op == 'continue':
            return await service.drive(identifier, continue_action_id=Continue.model_validate(payload).action_id), resource
        if op == 'cancel':
            return service.cancel(identifier, **CancelSync.model_validate(payload).model_dump()), resource
    elif command == 'memory':
        service = runtime.memory
        if op == 'list':
            EmptyInput.model_validate(payload)
            return service.list(), None
        if op == 'propose':
            result = service.propose(MemoryProposal.model_validate(payload).model_dump(mode='json'))
            return result, Resource(kind='memory', id=result['id'])
        identifier = require(resource, 'memory')
        if op == 'inspect':
            EmptyInput.model_validate(payload)
            return service.preview(identifier), resource
        if op == 'decide':
            return service.decide(identifier, **MemoryDecision.model_validate(payload).model_dump()), resource
    elif command == 'application':
        service = runtime.applications
        if op == 'list':
            EmptyInput.model_validate(payload)
            return service.list(), None
        if op == 'create':
            result = service.create(**CreateApplication.model_validate(payload).model_dump())
            return result, Resource(kind='application', id=result['id'])
        identifier = require(resource, 'application')
        if op == 'inspect':
            EmptyInput.model_validate(payload)
            return service.get(identifier), resource
        if op == 'event':
            value = ApplicationEventRequest.model_validate(payload)
            return service.append(identifier, value.event.model_dump(mode='json'),
                expected_revision=value.expected_revision, action_id=value.action_id), resource
    raise ValueError('unsupported_domain_operation')


async def execute(runtime, command, body, resource, publish):
    if command == 'start':
        if resource is not None:
            raise ValueError('start_has_no_existing_resource')
        value = StartInput.model_validate(body)
        mode = configured_mode(value.execution_mode)
        if not runtime.readiness()['generation_ready']:
            raise MissingPrerequisiteError('generation_not_ready')
        run = runtime.create_run(RunRequest.model_validate(value.model_dump() | {'execution_mode': mode}))
        resource = Resource(kind='run', id=run.id)
        publish(resource)
        await runtime.runs.drive(run.id)
    elif command == 'inspect':
        require(resource)
        data = inspect(runtime, resource)
        if body:
            require(resource, 'run')
            preview = runtime.workflow.content_preview(resource.id, **ContentPreviewRequest.model_validate(body).model_dump())
            data = data | {'content_preview': jsonable_encoder(preview)}
        return data, resource
    elif command == 'respond':
        return await respond(runtime, resource, body), resource
    elif command == 'cancel':
        identifier = require(resource)
        if resource.kind == 'discovery_sync':
            runtime.discovery.cancel(identifier, **CancelSync.model_validate(body).model_dump())
        else:
            EmptyInput.model_validate(body)
            if resource.kind == 'run':
                runtime.runs.cancel(identifier)
            elif resource.kind == 'profile_import':
                runtime.imports.get(identifier)
                runtime.imports.operations.cancel(identifier)
            elif resource.kind == 'role_evaluation':
                runtime.evaluations.cancel(identifier)
            else:
                raise ValueError('resource_cannot_be_cancelled')
    elif command == 'export':
        identifier = require(resource, 'run')
        value = ReexportRequest.model_validate(body)
        data = inspect(runtime, resource)
        fixed = runtime.store.input('run', identifier)
        destination = dict(base_dir=runtime.settings.output_base_dir, company_name=data['company'],
                           user_full_name=fixed['profile_snapshot']['personal']['full_name'])
        if value.recover:
            with runtime.store.connection() as conn:
                previous = runtime.store.action('run_reexport', identifier, value.action_id, conn)
            if previous:
                saved = json.loads(previous['request_json'])
                destination = {key: saved[key] for key in destination}
        return runtime.release.reexport(identifier, **value.model_dump(), **destination), resource
    elif command == 'import':
        if resource is not None:
            raise ValueError('import_has_no_existing_resource')
        value = ImportInput.model_validate(body)
        configured_mode(value.execution_mode)
        source = Path(value.source_path)
        created = runtime.imports.create(read_file(source), source.name)
        resource = Resource(kind='profile_import', id=created['id'])
        publish(resource)
        await runtime.imports.drive(created['id'])
    elif command == 'evaluate':
        if resource is not None:
            raise ValueError('evaluate_has_no_existing_resource')
        value = EvaluateInput.model_validate(body)
        mode = configured_mode(value.execution_mode)
        created = runtime.evaluations.create(**(value.model_dump() | {'execution_mode': mode}))
        resource = Resource(kind='role_evaluation', id=created['id'])
        publish(resource)
        await runtime.evaluations.drive(created['id'])
    elif command in ('discover', 'memory', 'application'):
        return await domain(runtime, command, resource, body, publish)
    else:
        raise ValueError('unknown_command')
    return inspect(runtime, resource), resource


def run_command(command, input_file, resource_text, runtime_factory, extra_args=()):
    """All validation/execution errors stay inside the one-document boundary."""
    resource = None
    runtime, data, error = None, None, None
    command = command or ''
    def publish(value):
        nonlocal resource
        resource = value
    try:
        if command not in COMMANDS or extra_args:
            raise ValueError('unknown_command_or_arguments')
        resource = parse_resource(resource_text)
        body = read_input(input_file)
        # Third-party progress/diagnostics may print; stdout is only the envelope.
        with redirect_stdout(sys.stderr):
            runtime = runtime_factory()
            data, resource = asyncio.run(execute(runtime, command, body, resource, publish))
        data = jsonable_encoder(data)
        failed = isinstance(data, dict) and data.get('status') == 'failed'
        error = AgentError(code='execution_failed', message='The saved operation failed. Inspect its diagnostics.') if failed else None
        code = 3 if failed else 0
    except MissingPrerequisiteError as exc:
        code, error = 2, AgentError(code='missing_prerequisites', message=str(exc))
    except Conflict as exc:
        code = 2 if str(exc) in ('generation_not_ready', 'profile_review_required') else 4
        error = AgentError(code='missing_prerequisites' if code == 2 else 'conflict', message=str(exc))
    except ValidationError:
        code, error = 1, AgentError(code='invalid_input', message='Input does not match the command schema.')
    except (ValueError, KeyError) as exc:
        code, error = 1, AgentError(code='invalid_input', message='Resource not found.' if isinstance(exc, KeyError) else str(exc))
    except Exception as exc:
        print('Agent command failed: ' + type(exc).__name__, file=sys.stderr)
        code, error = 3, AgentError(code='execution_failed', message='Command execution stopped. Inspect saved work before retrying.')
    if code and data is None and resource is not None and runtime is not None:
        try:
            with redirect_stdout(sys.stderr):
                data = jsonable_encoder(inspect(runtime, resource))
        except Exception:
            pass  # The primary failure remains; persistence may be unavailable.
    envelope = AgentEnvelope(ok=code == 0, command=command, resource=resource, data=data,
        next_action=next_action(resource, data), error=error)
    sys.stdout.write(envelope.model_dump_json() + '\n')
    return code

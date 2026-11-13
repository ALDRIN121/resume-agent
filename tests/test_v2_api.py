"""Durable HTTP facade and strict client contracts."""

import pytest
from fastapi.testclient import TestClient

from resume_agent.config import FeaturesConfig, ResumeAgentSettings
from tests.test_v2_workflow import PROFILE


def services(tmp_path):
    from resume_agent.runtime import Runtime
    calls = []

    async def model(stage, schema, messages):
        calls.append(stage)
        if stage == 'extract_jd':
            return {'company': 'Example', 'role_title': 'Engineer'}
        if stage == 'questions':
            return {'questions': []}
        if stage == 'proposals':
            return {'proposals': []}
        return PROFILE.model_dump(mode='json')

    runtime = Runtime(root=tmp_path, settings=ResumeAgentSettings(provider='openai', openai_api_key='secret', features=FeaturesConfig(enable_hr_review=False)),
                      model=model, tool_finder=lambda _: '/local/tool')
    runtime.profiles.save_reviewed(None, PROFILE, {})
    return runtime, calls


@pytest.mark.asyncio
async def test_facade_queued_is_durable_and_restart_reconstructs_pending(tmp_path):
    from resume_agent.api.v2_manager import V2RunManager
    runtime, calls = services(tmp_path)
    manager = V2RunManager(runtime)
    created = await manager.start_run({'jd_text': 'Complete JD', 'max_pages': 2})
    assert created['status'] == 'queued'
    assert runtime.store.row('run', created['id'])['status'] == 'queued'
    await manager.wait(created['id'])
    restarted = V2RunManager(runtime)
    detail = restarted.get_run(created['id'])
    assert detail['pending']['kind'] == 'present_suggestions'
    assert detail['contract_version'] == 2
    assert detail['thread_id'] == created['id']
    assert detail['pending']['proposal_ids'] == []
    assert detail['pending']['payload']['reject_all']['projected_profile']['summary'] == PROFILE.summary
    assert calls == ['extract_jd', 'questions', 'proposals']
    with pytest.raises(ValueError):
        await restarted.resume_run(created['id'], {'kind': 'present_suggestions', 'payload': {}})
    assert calls == ['extract_jd', 'questions', 'proposals']


def test_http_conflicts_inputs_bounds_upload_and_preserves_import_draft(tmp_path):
    from resume_agent.api.app import create_app
    runtime, calls = services(tmp_path)
    with TestClient(create_app(services=runtime), base_url="http://localhost") as client:
        assert client.post('/api/runs', json={'jd_text': 'one', 'jd_url': 'https://example.test'}).status_code == 422
        assert client.post('/api/runs/jd-file', files={'file': ('jd.txt', b'a' * 48001)}).status_code == 413
        assert client.post('/api/runs/jd-file', files={'file': ('jd.txt', b'\xff')}).status_code == 400
        result = client.post('/api/runs/jd-file', files={'file': ('jd.txt', b'Complete text')})
        assert result.json()['text'] == 'Complete text'
        result = client.post('/api/resume/upload', files={'file': ('resume.tex', b'Full source')})
        assert result.status_code == 200
        body = result.json()
        assert body['status'] == 'pending_review'
        assert body['job_id'] == body['id']
        assert runtime.profiles.load_snapshot().profile == PROFILE
        assert client.get('/api/profile/imports/' + body['id']).json()['source']['text'] == 'Full source'
        assert 'secret' not in str(body)
        assert client.put('/api/resume', json=PROFILE.model_dump(mode='json')).status_code == 409


@pytest.mark.asyncio
async def test_content_revision_creates_fresh_linked_run_and_reviews(tmp_path):
    from resume_agent.api.v2_manager import V2RunManager
    runtime, calls = services(tmp_path)
    manager = V2RunManager(runtime)
    first = await manager.start_run({'jd_text': 'Complete JD'})
    await manager.wait(first['id'])
    old = manager.get_run(first['id'])
    revised = await manager.start_run({'jd_text': 'Complete JD', 'parent_run_id': first['id'], 'max_pages': 3})
    await manager.wait(revised['id'])
    child = manager.get_run(revised['id'])
    assert child['parent_run_id'] == first['id']
    assert child['pending']['review_id'] != old['pending']['review_id']
    assert runtime.store.input('run', child['id'])['request']['max_pages'] == 3
    assert manager.get_run(first['id'])['pending'] == old['pending']


@pytest.mark.asyncio
async def test_facade_replays_stored_action_result_after_run_advances(tmp_path):
    from resume_agent.api.v2_manager import V2RunManager
    runtime, calls = services(tmp_path)
    # The model call now has one human question before the content review.
    original = runtime.workflow.model
    async def model(stage, schema, messages):
        if stage == 'questions':
            return {'questions': [{'id': 'q1', 'prompt': 'Evidence?', 'why_asking': 'Need evidence'}]}
        return await original(stage, schema, messages)
    runtime.workflow.model = model
    manager = V2RunManager(runtime)
    created = await manager.start_run({'jd_text': 'Full JD'})
    await manager.wait(created['id'])
    view = manager.get_run(created['id'])
    action = {'kind': 'ask_missing', 'action_id': 'answers', 'request_id': view['pending']['request_id'], 'answers': {}}
    first = await manager.resume_run(created['id'], action)
    runtime.runs.cancel(created['id'])
    replay = await manager.resume_run(created['id'], action)
    assert replay['status'] == first['status'] == 'awaiting-input'
    assert replay['pending'] == first['pending']
    assert manager.get_run(created['id'])['status'] == 'cancelled'
@pytest.mark.asyncio
async def test_review_progress_and_model_are_durable_not_inferred_from_live_events(tmp_path):
    from resume_agent.api.v2_manager import V2RunManager
    from resume_agent.contracts import AskMissing, RunRequest
    from resume_agent.runtime import Runtime

    runtime, _ = services(tmp_path)
    original = runtime.workflow.model

    async def model(stage, schema, messages):
        if stage == 'questions':
            return {'questions': [{'id': 'q1', 'prompt': 'Confirm contribution scope?',
                                   'why_asking': 'Keep the wording accurate.'}]}
        return await original(stage, schema, messages)

    runtime.workflow.model = model
    created = runtime.create_run(RunRequest(job_input='Complete job', input_type='text'))
    before = V2RunManager(runtime).get_run(created.id)
    assert before['review_stats'] == dict(questions=None, answered=None, suggestions=None, approved=None)
    assert before['provider'] == 'openai'
    assert before['model'] == runtime.store.input('run', created.id)['model']
    pending = await runtime.runs.drive(created.id)
    await runtime.runs.drive(created.id, AskMissing(action_id='answer', request_id=pending.pending.request_id,
                                                   answers={'q1': 'I helped; I did not lead.'}))
    reopened = Runtime(root=tmp_path, settings=runtime.settings, model=model,
                       tool_finder=lambda _: '/fixture/tool')
    restored = V2RunManager(reopened).get_run(created.id)
    assert restored['review_stats'] == dict(questions=1, answered=1, suggestions=0, approved=None)


@pytest.mark.asyncio
async def test_interrupted_reexport_exposes_recovery_and_keeps_original_destination_settings(tmp_path):
    from pathlib import Path

    from resume_agent.api.app import create_app
    from resume_agent.api.v2_manager import V2RunManager
    from resume_agent.contracts import PresentSuggestions, ReviewPdf, RunRequest
    from tests.test_v2_workflow import build

    runtime, _ = services(tmp_path)
    runtime.runs, runtime.workflow, ids = build(tmp_path, [], questions=False)
    runtime.store = runtime.runs.store
    runtime.release = runtime.workflow.release
    run = runtime.runs.create(RunRequest(job_input='Engineer', input_type='text'), profile_snapshot=PROFILE)
    ids.append(run.id)
    pending = (await runtime.runs.drive(run.id)).pending
    preview = runtime.workflow.content_preview(run.id, pending.review_id, pending.source_revision, [])
    pending = (await runtime.runs.drive(run.id, PresentSuggestions(action_id='content',review_id=pending.review_id,
        source_revision=pending.source_revision,approved_ids=[],content_hash=preview.manifest.content_hash))).pending
    complete = await runtime.runs.drive(run.id, ReviewPdf(action_id='approve',decision='approve',
        **{key:getattr(pending.review,key) for key in ('review_id','content_hash','render_hash','pdf_hash')}))
    Path(complete.release.destination).unlink()

    class Crash(BaseException):
        pass

    def crash(stage):
        if stage == 'reexport_after_reservation':
            raise Crash()

    runtime.release._crash_hook = crash
    with pytest.raises(Crash):
        runtime.release.reexport(run.id,'restore',complete.release.pdf_hash,base_dir=tmp_path/'original-export',
                                 company_name='Example',user_full_name='Ada')
    runtime.release._crash_hook = None
    detail = V2RunManager(runtime).get_run(run.id)
    assert detail['canonical_available'] and not detail['export_available']
    assert detail['pending_reexport'] == {'action_id':'restore','expected_pdf_hash':complete.release.pdf_hash}
    with TestClient(create_app(services=runtime),base_url='http://localhost') as client:
        response = client.post(f'/api/runs/{run.id}/reexport',json={**detail['pending_reexport'],'recover':True})
        assert response.status_code == 200, response.text
        restored = response.json()
        assert Path(restored['destination']).is_relative_to(tmp_path/'original-export')
        assert Path(restored['destination']).read_bytes() == runtime.release.get_final(run.id)
        assert client.get(f'/api/runs/{run.id}').json()['pending_reexport'] is None

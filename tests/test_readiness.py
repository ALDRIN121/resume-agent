"""Readiness uses local evidence and never probes a paid provider."""
from resume_agent.config import ResumeAgentSettings
from resume_agent.profile_store import ProfileStore
from tests.test_v2_workflow import PROFILE


def test_readiness_reports_missing_review_and_tools_without_model_call(tmp_path):
    from resume_agent.runtime import Runtime
    settings = ResumeAgentSettings(provider='openai', openai_api_key=None)
    services = Runtime(root=tmp_path, settings=settings, tool_finder=lambda _: None)
    state = services.readiness()
    assert not state['generation_ready']
    assert state['profile']['status'] == 'missing'
    assert state['provider']['status'] == 'missing'
    assert state['compiler']['status'] == 'missing'
    assert state['next_steps']
    profiles = ProfileStore(tmp_path / 'base_resume.yaml')
    profiles.save(None, PROFILE, {})
    assert services.readiness()['profile']['status'] == 'review_required'
    current = profiles.load_snapshot()
    profiles.review_current_profile(current.revision)
    assert services.readiness()['profile']['status'] == 'ready'


def test_configured_provider_is_unverified_and_readiness_is_injected(tmp_path):
    from fastapi.testclient import TestClient

    from resume_agent.api.app import create_app
    from resume_agent.runtime import Runtime
    settings = ResumeAgentSettings(provider='openai', openai_api_key='never-return-this')
    services = Runtime(root=tmp_path, settings=settings, tool_finder=lambda _: '/tools/local')
    profiles = services.profiles
    profiles.save_reviewed(None, PROFILE, {})
    state = services.readiness()
    assert state['generation_ready']
    assert state['provider']['status'] == 'configured_unverified'
    assert 'never-return-this' not in str(state)
    with TestClient(create_app(services=services)) as client:
        assert client.get('/api/readiness').json() == state


def test_readiness_uses_configured_compiler_path(tmp_path):
    from resume_agent.config import LatexConfig
    from resume_agent.runtime import Runtime
    settings = ResumeAgentSettings(latex=LatexConfig(tectonic_path='/custom/tectonic'))
    seen = []
    def finder(name):
        seen.append(name)
        return None
    runtime = Runtime(root=tmp_path, settings=settings, tool_finder=finder)
    runtime.readiness()
    assert '/custom/tectonic' in seen


def test_default_runtime_reloads_settings_for_new_runs_without_changing_old_capture(tmp_path, monkeypatch):
    from resume_agent.contracts import RunRequest
    from resume_agent.runtime import Runtime
    selected = [ResumeAgentSettings(provider='openai', openai_api_key='fictional')]
    monkeypatch.setattr(ResumeAgentSettings, 'load', lambda: selected[0])
    runtime = Runtime(root=tmp_path, tool_finder=lambda _: '/local')
    runtime.profiles.save_reviewed(None, PROFILE, {})
    first = runtime.create_run(RunRequest(job_input='Full JD', input_type='text'))
    selected[0] = ResumeAgentSettings(provider='ollama')
    second = runtime.create_run(RunRequest(job_input='Full JD', input_type='text'))
    assert runtime.store.input('run', first.id)['provider'] == 'openai'
    assert runtime.store.input('run', second.id)['provider'] == 'ollama'
    assert runtime.readiness()['provider']['provider'] == 'ollama'


def test_http_settings_update_refreshes_readiness_and_new_run_without_restart(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from resume_agent import config
    from resume_agent.api.app import create_app
    from resume_agent.contracts import RunRequest
    from resume_agent.runtime import Runtime
    from resume_agent.ui import setup_wizard

    for module in (config, setup_wizard):
        monkeypatch.setattr(module, 'CONFIG_DIR', tmp_path, raising=False)
        monkeypatch.setattr(module, 'SECRETS_FILE', tmp_path / '.env', raising=False)
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    monkeypatch.setitem(ResumeAgentSettings.model_config, 'env_file', None)
    monkeypatch.setenv('OPENAI_API_KEY', '')
    ResumeAgentSettings(provider='openai', openai_api_key=None,
                        model={'default': 'before', 'vision': ''}).save()

    async def model(stage, schema, messages):
        if stage == 'extract_jd':
            return {'company': 'Example', 'role_title': 'Engineer'}
        return {'questions': []} if stage == 'questions' else {'proposals': []}

    runtime = Runtime(root=tmp_path, model=model, tool_finder=lambda _: '/fixture/tool')
    runtime.profiles.save_reviewed(None, PROFILE, {})
    old = runtime.runs.create(RunRequest(job_input='Saved input', input_type='text'),
                              profile_snapshot=PROFILE, provider='openai', model='before')
    with TestClient(create_app(services=runtime), base_url='http://localhost') as client:
        assert client.get('/api/readiness').json()['provider']['status'] == 'missing'
        response = client.put('/api/settings', json={
            'provider': 'openai', 'default_model': 'after', 'api_key': 'fictional-new-key',
        })
        assert response.status_code == 200
        ready = client.get('/api/readiness')
        assert ready.json()['generation_ready']
        created = client.post('/api/runs', json={'jd_text': 'Complete job posting'})
        assert created.status_code == 200
        fixed = runtime.store.input('run', created.json()['thread_id'])
        assert fixed['model'] == 'after'
        assert runtime.store.input('run', old.id)['model'] == 'before'
        assert 'fictional-new-key' not in response.text + ready.text + json.dumps(fixed)

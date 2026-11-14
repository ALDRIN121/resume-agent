from fastapi.testclient import TestClient

from tests.test_v2_api import services


def test_memory_http_review_is_explicit_and_conflicts_are_safe(tmp_path):
    from resume_agent.api.app import create_app
    runtime, _ = services(tmp_path)
    with TestClient(create_app(services=runtime),base_url='http://localhost') as client:
        response = client.post('/api/memory/proposals',json={'kind':'writing_rule',
            'payload':{'instruction':'Use short sentences.'},
            'source_refs':[{'kind':'user_text','text':'Please use short sentences.'}]})
        assert response.status_code == 200, response.text
        record = response.json()
        assert record['status'] == 'pending'
        assert client.get('/api/memory/active').json()['records'] == []
        assert client.get(f"/api/memory/{record['id']}/preview").json()['after']['instruction'] == 'Use short sentences.'
        action = {'decision':'accept','expected_revision':record['revision'],'action_id':'accept'}
        url = f"/api/memory/{record['id']}/decision"
        accepted = client.post(url,json=action)
        assert accepted.status_code == 200
        assert client.post(url,json=action).json() == accepted.json()
        assert client.post(url,json={**action,'decision':'reject'}).status_code == 409
        assert client.get('/api/memory/active').json()['records'][0]['id'] == record['id']
        assert len(client.get(f"/api/memory/{record['id']}/history").json()) == 1
        assert client.post('/api/memory/proposals',json={'kind':'settings','payload':{'api_key':'secret'}}).status_code == 422
        assert client.post(url,json={'decision':'accept'}).status_code == 422


def test_memory_reconciliation_conflicts_are_persisted_on_explicit_retry(tmp_path):
    from resume_agent.contracts import content_hash
    from resume_agent.run_store import Conflict
    from tests.test_memory import decide, fact
    import pytest
    runtime, _ = services(tmp_path)
    record = fact(runtime.memory,runtime)
    def crash(stage):
        if stage == 'before_profile_write':
            raise KeyboardInterrupt()
    runtime.memory.crash_hook = crash
    with pytest.raises(KeyboardInterrupt):
        decide(runtime.memory,record)
    snapshot = runtime.profiles.load_snapshot()
    changed = snapshot.profile.model_copy(deep=True)
    changed.summary = 'Manual change.'
    runtime.profiles.save_reviewed(snapshot.revision,changed,{})
    runtime.memory.crash_hook = None
    with pytest.raises(Conflict):
        decide(runtime.memory,record)
    assert runtime.memory.get(record['id'])['status'] == 'conflict'
    assert runtime.profiles.load_snapshot().revision == content_hash(changed)

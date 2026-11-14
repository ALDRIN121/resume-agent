from fastapi.testclient import TestClient

from tests.test_cli_json import invoke
from tests.test_release_service import setup as released_setup, release  # noqa: F401
from tests.test_v2_api import services


def test_json_and_api_return_the_same_pending_state_and_preview(tmp_path,monkeypatch):
    from resume_agent.api.app import create_app
    runtime,calls=services(tmp_path)
    _,started=invoke(tmp_path,monkeypatch,runtime,'start',{'job_input':'Python full role','input_type':'text'})
    run_id=started['resource']['id']
    with TestClient(create_app(services=runtime),base_url='http://localhost') as client:
        api=client.get('/api/runs/'+run_id).json()
        assert started['data']==api and started['next_action']==api['pending']
        body={key:api['pending'][key] for key in ('review_id','source_revision')};body['approved_ids']=[]
        preview=client.post('/api/runs/'+run_id+'/content-preview',json=body).json()
        _,inspected=invoke(tmp_path,monkeypatch,runtime,'inspect',body,'run:'+run_id)
        assert inspected['data']['content_preview']==preview
    assert calls==['extract_jd','questions','proposals']


def test_json_export_reuses_approved_bytes_and_existing_api_replay(tmp_path,monkeypatch,released_setup):
    from resume_agent.api.app import create_app
    from resume_agent.config import OutputConfig
    from resume_agent.runtime import Runtime
    from resume_agent.artifacts import hash_file
    completed=release(released_setup)
    runtime=Runtime(root=tmp_path)
    runtime._settings_override=runtime.settings.model_copy(update={'output':OutputConfig(base_dir=str(tmp_path/'exports'))})
    action={'action_id':'json-export','expected_pdf_hash':completed.release.pdf_hash}
    result,exported=invoke(tmp_path,monkeypatch,runtime,'export',action,'run:'+completed.id)
    assert result.exit_code==0,exported
    assert hash_file(exported['data']['destination'])==completed.release.pdf_hash
    with TestClient(create_app(services=runtime),base_url='http://localhost') as client:
        response=client.post('/api/runs/'+completed.id+'/reexport',json=action)
        assert response.status_code==200,response.text
        assert response.json()==exported['data']
    assert runtime.store.release(completed.id)['action_id']==completed.release.action_id

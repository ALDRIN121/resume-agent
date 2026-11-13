from fastapi.testclient import TestClient

from tests.test_evaluation_operations import setup_evaluation


def test_local_report_export_and_metrics_do_not_invent_submission(tmp_path):
    from resume_agent.api.app import create_app
    runtime,job,calls=setup_evaluation(tmp_path)
    runtime.applications.create(job.id,action_id='planned')
    with TestClient(create_app(services=runtime),base_url='http://localhost') as client:
        report=client.get('/api/outcomes')
        assert report.status_code==200 and report.json()['counts']['submitted']==0
        exported=client.get('/api/outcomes/export')
        assert exported.status_code==200 and 'attachment' in exported.headers['content-disposition']
        assert exported.json()['counts']==report.json()['counts']
        metrics=client.get('/api/metrics').json()
        assert metrics['applications']['recorded']==1 and metrics['applications']['submitted']==0
        assert metrics['generation']['percent'] is None
        assert calls==[]

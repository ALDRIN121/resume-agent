import pytest


def test_jobs_keep_full_immutable_versions_and_reuse_same_logical_content(tmp_path):
    from resume_agent.job_store import JobStore
    from resume_agent.run_store import RunStore
    jobs=JobStore(RunStore(tmp_path/'library.sqlite',tmp_path/'state.sqlite'))
    first=jobs.capture('Engineer at Example',company='Example',role='Engineer')
    second=jobs.capture('Engineer at Example',company='Example',role='Engineer')
    assert first.id!=second.id and first.logical_id!=second.logical_id


def test_job_supported_boundary_and_version_chain(tmp_path):
    from resume_agent.job_store import JobStore
    from resume_agent.run_store import RunStore
    jobs=JobStore(RunStore(tmp_path/'library.sqlite',tmp_path/'state.sqlite'))
    first=jobs.capture('é'*48000,source_key='manual:example')
    same=jobs.capture('é'*48000,source_key='manual:example')
    assert same==first
    changed=jobs.capture('Changed posting',source_key='manual:example')
    assert changed.logical_id==first.logical_id and changed.previous_id==first.id
    assert jobs.get(first.id).text=='é'*48000
    assert jobs.current(first.logical_id).id==changed.id
    assert jobs.list()[0].id==changed.id
    assert jobs.capture('é'*48000,source_key='manual:example')==first
    assert jobs.current(first.logical_id).id==first.id
    with pytest.raises(ValueError):
        jobs.capture('é'*48001)
    with pytest.raises(ValueError):
        jobs.capture('   ')

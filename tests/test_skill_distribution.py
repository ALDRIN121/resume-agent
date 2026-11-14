from pathlib import Path
import tarfile
import zipfile
import os
import subprocess
import sys

from typer.testing import CliRunner

from tests.test_packaged_ui import distributions  # noqa: F401


def test_skill_export_is_portable_and_refuses_to_overwrite(tmp_path):
    from resume_agent.cli import app
    destination=tmp_path/'project with spaces'/'skills'/'resume-agent'
    result=CliRunner().invoke(app,['skill','export','--destination',str(destination)],input='')
    assert result.exit_code==0,result.output
    assert (destination/'SKILL.md').is_file()
    assert (destination/'references'/'protocol.md').is_file()
    assert not any(p.is_symlink() for p in destination.rglob('*'))
    # The exported reference must work without the repository around it.
    assert 'schema_version' in (destination/'references'/'protocol.md').read_text()
    sentinel=destination/'user-note.txt';sentinel.write_text('Keep this file.')
    before={str(p.relative_to(destination)):p.read_bytes() for p in destination.rglob('*') if p.is_file()}
    rejected=CliRunner().invoke(app,['skill','export','--destination',str(destination)],input='')
    assert rejected.exit_code!=0
    assert {str(p.relative_to(destination)):p.read_bytes() for p in destination.rglob('*') if p.is_file()}==before


def test_distribution_contains_skill_and_excludes_private_workspaces(distributions):
    with zipfile.ZipFile(next(distributions.glob('*.whl'))) as archive:
        names=archive.namelist()
        assert 'resume_agent/_skills/resume-agent/SKILL.md' in names
        assert 'resume_agent/_skills/resume-agent/references/protocol.md' in names
        source=Path(__file__).resolve().parents[1]/'skills/resume-agent'
        for relative in ('SKILL.md','references/protocol.md','agents/openai.yaml'):
            assert archive.read('resume_agent/_skills/resume-agent/'+relative)==(source/relative).read_bytes()
        metadata=archive.read(next(p for p in names if p.endswith('.dist-info/METADATA'))).decode()
        assert 'License-Expression: MIT' in metadata
    with tarfile.open(next(distributions.glob('*.tar.gz'))) as archive:
        paths=archive.getnames()
        assert any(p.endswith('/skills/resume-agent/SKILL.md') for p in paths)
    for name in [*names,*paths]:
        assert not set(Path(name).parts)&{'.egm','.superpowers','.env','.claude','.codex','node_modules','library.sqlite','state.sqlite','base_resume.yaml'}


def test_installed_wheel_exports_the_skill_outside_the_checkout(distributions,tmp_path):
    installed=tmp_path/'installed'
    result=subprocess.run(['uv','pip','install','--no-deps','--target',str(installed),str(next(distributions.glob('*.whl')))],
        capture_output=True,text=True,env=os.environ.copy())
    assert result.returncode==0,result.stdout+result.stderr
    result=subprocess.run([sys.executable,'-I','-c',
        'import sys;sys.path.insert(0,sys.argv[1]);from typer.testing import CliRunner;from resume_agent.cli import app;'
        'result=CliRunner().invoke(app,["skill","export","--destination",sys.argv[2]],input="");'
        'assert result.exit_code==0,result.output',str(installed),str(tmp_path/'project'/'resume-agent')],cwd=tmp_path,
        capture_output=True,text=True,env=os.environ.copy())
    assert result.returncode==0,result.stdout+result.stderr
    assert (tmp_path/'project/resume-agent/references/protocol.md').is_file()

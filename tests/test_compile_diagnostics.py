"""Compiler log preservation and isolated pipeline nodes."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from resume_agent.tools.tectonic_compile import compile_latex


def fake_compile(cmd, **kwargs):
    out = Path(cmd[cmd.index("--outdir") + 1])
    source = Path(cmd[3]).read_text()
    (out / "resume.pdf").write_bytes(b"%PDF-" + source.encode())
    (out / "resume.log").write_text(
        "Overfull \\hbox (1.2pt too wide)\nOverfull \\vbox (3pt too high)\nOutput written on resume.pdf (2 pages)."
    )
    return SimpleNamespace(returncode=0, stderr="compile note", stdout="stdout")


def test_success_retains_tex_log_and_structured_overflow(tmp_path):
    with (
        patch("resume_agent.tools.tectonic_compile.shutil.which", return_value="tectonic"),
        patch("resume_agent.tools.tectonic_compile.subprocess.run", side_effect=fake_compile),
    ):
        result = compile_latex("marker", output_dir=tmp_path)
    assert result.ok
    assert "Overfull \\hbox" in result.raw_log
    assert result.page_count == 2
    assert result.overflow
    assert len(result.overfull_boxes) == 2
    assert (tmp_path / "tectonic_raw.log").read_text() == result.raw_log


def test_underfull_is_not_overflow_and_failed_logs_survive(tmp_path):
    def fail(cmd, **kwargs):
        out = Path(cmd[cmd.index("--outdir") + 1])
        (out / "resume.log").write_text("Underfull \\hbox\n! Bad input")
        return SimpleNamespace(returncode=1, stderr="", stdout="")

    with (
        patch("resume_agent.tools.tectonic_compile.shutil.which", return_value="tectonic"),
        patch("resume_agent.tools.tectonic_compile.subprocess.run", side_effect=fail),
    ):
        result = compile_latex("bad", output_dir=tmp_path)
    assert not result.ok
    assert not result.overflow
    assert not result.overfull_boxes
    assert "! Bad input" in (tmp_path / "tectonic_raw.log").read_text()


@pytest.mark.parametrize("second_company", ["Acme", "Different Company"])
def test_compiler_interleaving_render_save_and_retry(tmp_path, monkeypatch, second_company):
    from resume_agent import artifacts
    from resume_agent.agents.output_saver import output_saver_node
    from resume_agent.agents.pdf_compiler import pdf_compiler_node
    from resume_agent.agents.render_pages import render_pages_node
    from resume_agent.config import OutputConfig, ResumeAgentSettings
    from resume_agent.schemas import JobDescription, PersonalInfo, UserResume

    monkeypatch.setattr(artifacts, "CONFIG_DIR", tmp_path)
    settings = ResumeAgentSettings(output=OutputConfig(base_dir=str(tmp_path / "output")))

    def state(marker, company):
        return {
            "latex_source": marker,
            "jd": JobDescription(company=company, role_title="Engineer"),
            "base_resume": UserResume(personal=PersonalInfo(full_name="Jane Doe", email="j@e.com")),
        }

    a, b = state("A", "Acme"), state("B", second_company)
    with (
        patch("resume_agent.agents.pdf_compiler.check_tectonic_available", return_value=True),
        patch("resume_agent.tools.tectonic_compile.shutil.which", return_value="tectonic"),
        patch("resume_agent.tools.tectonic_compile.subprocess.run", side_effect=fake_compile),
    ):
        a.update(pdf_compiler_node(a, settings=settings))
        b.update(pdf_compiler_node(b, settings=settings))
        original = Path(a["pdf_path"])
        retry = {**a, "latex_source": "A2"}
        retry.update(pdf_compiler_node(retry, settings=settings))

    def render(pdf_path, *, dpi, output_dir):
        output_dir.mkdir(exist_ok=True, parents=True)
        image = output_dir / "page_1.png"
        image.write_bytes(Path(pdf_path).read_bytes())
        return [str(image)]

    with patch("resume_agent.agents.render_pages.pdf_to_images", side_effect=render):
        images = render_pages_node(a)["page_images"]
    assert Path(images[0]).read_bytes() == b"%PDF-A"
    assert original.read_bytes() == b"%PDF-A"
    assert retry["attempt_number"] == 2
    assert retry["pdf_path"] != str(original)
    for current, marker in [(a, b"%PDF-A"), (b, b"%PDF-B")]:
        saved = output_saver_node(current, settings=settings)
        assert Path(saved["final_pdf_path"]).read_bytes() == marker
    with pytest.raises(ValueError, match="release"):
        output_saver_node({**a, "schema_version": 2}, settings=settings)


def test_timeout_preserves_tex_log(tmp_path):
    import subprocess

    def timeout(cmd, **kwargs):
        out = Path(cmd[cmd.index("--outdir") + 1])
        (out / "resume.log").write_text("Last useful TeX diagnostic")
        raise subprocess.TimeoutExpired(cmd, 1, output="partial stdout", stderr="partial stderr")

    with (
        patch("resume_agent.tools.tectonic_compile.shutil.which", return_value="tectonic"),
        patch("resume_agent.tools.tectonic_compile.subprocess.run", side_effect=timeout),
    ):
        result = compile_latex("source", output_dir=tmp_path)
    assert not result.ok
    assert "Last useful TeX diagnostic" in result.raw_log
    assert "partial stderr" in result.raw_log
    assert result.error_code == "compile_timeout"
    assert (tmp_path / "tectonic_raw.log").read_text() == result.raw_log


def test_terminal_failure_copies_only_its_attempt_log(tmp_path, monkeypatch):
    from uuid import uuid4

    from resume_agent import artifacts
    from resume_agent.agents.terminal_failure import terminal_failure_node
    from resume_agent.config import OutputConfig, ResumeAgentSettings

    monkeypatch.setattr(artifacts, "CONFIG_DIR", tmp_path)
    run = artifacts.RunArtifacts.create(str(uuid4()))
    run.attempt(1).log_path.write_text("run A diagnostic")
    other = artifacts.RunArtifacts.create(str(uuid4()))
    other.attempt(1).log_path.write_text("run B diagnostic")
    settings = ResumeAgentSettings(output=OutputConfig(base_dir=str(tmp_path / "output")))
    terminal_failure_node(
        {
            "artifact_id": run.artifact_id,
            "attempt_number": 1,
            "latex_source": "A",
            "pdf_errors": ["failed"],
        },
        settings=settings,
    )
    logs = list((tmp_path / "output/_failed").rglob("tectonic_raw.log"))
    assert len(logs) == 1
    assert logs[0].read_text() == "run A diagnostic"


def test_image_render_preserves_unexpected_existing_file(tmp_path):
    from resume_agent.tools.pdf_to_images import pdf_to_images

    target = tmp_path / "page_1.png"
    target.write_bytes(b"unrelated")
    from PIL import Image

    image = Image.new("RGB", (1, 1))
    with (
        patch("resume_agent.tools.pdf_to_images._check_poppler"),
        patch("pdf2image.convert_from_path", return_value=[image]),
    ):
        with pytest.raises(FileExistsError):
            pdf_to_images("source.pdf", output_dir=tmp_path)
    assert target.read_bytes() == b"unrelated"


@pytest.mark.parametrize(
    "returncode, log, code",
    [
        (1, "! Undefined control sequence", "compile_syntax"),
        (1, "TLS handshake unavailable", "compile_environment"),
    ],
)
def test_compile_failure_has_stable_error_code(tmp_path, returncode, log, code):
    with (
        patch("resume_agent.tools.tectonic_compile.shutil.which", return_value="tectonic"),
        patch(
            "resume_agent.tools.tectonic_compile.subprocess.run",
            return_value=SimpleNamespace(returncode=returncode, stderr=log, stdout=""),
        ),
    ):
        result = compile_latex("source", output_dir=tmp_path)
    assert result.error_code == code


def test_missing_compiler_has_stable_error_code():
    with patch("resume_agent.tools.tectonic_compile.shutil.which", return_value=None):
        result = compile_latex("source")
    assert result.error_code == "compiler_unavailable"


def test_concurrent_failure_diagnostics_do_not_share_paths(tmp_path, monkeypatch):
    from uuid import uuid4

    from resume_agent import artifacts
    from resume_agent.agents.terminal_failure import terminal_failure_node
    from resume_agent.config import OutputConfig, ResumeAgentSettings

    monkeypatch.setattr(artifacts, "CONFIG_DIR", tmp_path)
    settings = ResumeAgentSettings(output=OutputConfig(base_dir=str(tmp_path / "output")))
    for marker in ["failure A", "failure B"]:
        run = artifacts.RunArtifacts.create(str(uuid4()))
        run.attempt(1).log_path.write_text(marker)
        terminal_failure_node(
            {"artifact_id": run.artifact_id, "attempt_number": 1, "pdf_errors": [marker]},
            settings=settings,
        )
    logs = list((tmp_path / "output/_failed").rglob("tectonic_raw.log"))
    assert sorted(p.read_text() for p in logs) == ["failure A", "failure B"]

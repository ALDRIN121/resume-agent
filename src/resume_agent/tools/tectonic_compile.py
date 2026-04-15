"""Tectonic LaTeX → PDF compiler wrapper."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CompileResult:
    ok: bool
    pdf_path: str | None   # absolute path to the produced PDF
    errors: list[str]      # parsed error lines from tectonic's stderr
    raw_log: str           # full stderr for debugging


def compile_latex(
    latex_source: str,
    *,
    tectonic_path: str = "tectonic",
    timeout: int = 60,
    output_dir: Path | None = None,
) -> CompileResult:
    """
    Compile LaTeX source string to PDF using Tectonic.

    Creates a temporary directory, writes the .tex file, runs tectonic,
    and copies the output PDF to output_dir (or keeps it in the temp dir).

    Returns CompileResult with ok=True and pdf_path on success.
    """
    if not shutil.which(tectonic_path):
        return CompileResult(
            ok=False,
            pdf_path=None,
            errors=[
                f"Tectonic not found at '{tectonic_path}'. "
                "Install it from https://tectonic-typesetting.github.io/ "
                "or via: cargo install tectonic"
            ],
            raw_log="",
        )

    with tempfile.TemporaryDirectory(prefix="resume_agent_") as tmp:
        tmp_path = Path(tmp)
        tex_file = tmp_path / "resume.tex"
        tex_file.write_text(latex_source, encoding="utf-8")

        try:
            result = subprocess.run(
                [
                    tectonic_path,
                    "-X",
                    "compile",
                    str(tex_file),
                    "--outdir",
                    str(tmp_path),
                    "--keep-logs",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return CompileResult(
                ok=False,
                pdf_path=None,
                errors=[f"Tectonic timed out after {timeout}s"],
                raw_log="",
            )

        raw_log = result.stderr + result.stdout
        produced_pdf = tmp_path / "resume.pdf"

        if result.returncode != 0 or not produced_pdf.exists():
            errors = _parse_tectonic_errors(raw_log)
            return CompileResult(ok=False, pdf_path=None, errors=errors, raw_log=raw_log)

        # Move PDF to destination
        dest_dir = output_dir or tmp_path
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_pdf = dest_dir / "resume.pdf"
        import shutil as _shutil
        _shutil.copy2(str(produced_pdf), str(dest_pdf))

        return CompileResult(ok=True, pdf_path=str(dest_pdf), errors=[], raw_log=raw_log)


def _parse_tectonic_errors(log: str) -> list[str]:
    """
    Extract the most relevant error lines from tectonic output.
    LaTeX errors start with '!' or contain 'error:'.
    """
    errors: list[str] = []
    lines = log.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("!") or "error:" in stripped.lower():
            # Grab context: the error line plus next 2 lines
            context = [stripped]
            for j in range(i + 1, min(i + 3, len(lines))):
                ctx = lines[j].strip()
                if ctx:
                    context.append(ctx)
            errors.append(" | ".join(context))
        if len(errors) >= 8:
            break

    if not errors:
        # Return last 5 non-empty lines as a fallback
        errors = [ln.strip() for ln in lines if ln.strip()][-5:]

    return errors


def check_tectonic_available(tectonic_path: str = "tectonic") -> bool:
    """Return True if tectonic binary is accessible."""
    return shutil.which(tectonic_path) is not None

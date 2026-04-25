"""Tectonic LaTeX → PDF compiler wrapper."""

from __future__ import annotations

import os
import platform
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
    fatal: bool = False    # True = Tectonic env/network issue, retrying won't help


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

        # On Windows, fontconfig may not be configured, causing
        # "Cannot load default config file" errors that abort compilation.
        # Write a minimal empty fontconfig and point FONTCONFIG_FILE at it.
        env = None
        if platform.system() == "Windows" and "FONTCONFIG_FILE" not in os.environ:
            fc_file = tmp_path / "fonts.conf"
            fc_file.write_text(
                '<?xml version="1.0"?>\n'
                '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
                "<fontconfig/>\n"
            )
            env = {**os.environ, "FONTCONFIG_FILE": str(fc_file)}

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
                env=env,
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
            # The TeX .log file contains the real error messages (package errors,
            # undefined commands, etc.) — stderr only has Tectonic's own notes.
            tex_log_path = tmp_path / "resume.log"
            if tex_log_path.exists():
                try:
                    tex_log = tex_log_path.read_text(encoding="utf-8", errors="replace")
                    raw_log = raw_log + "\n=== TeX log ===\n" + tex_log
                except OSError:
                    pass
            errors = _parse_tectonic_errors(raw_log)
            fatal = False
            if not errors:
                errors = ["Tectonic exited with an error but produced no diagnostic output."]
                fatal = True
            return CompileResult(ok=False, pdf_path=None, errors=errors, raw_log=raw_log, fatal=fatal)

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
    'note:' and 'warning:' lines are informational and skipped.
    """
    errors: list[str] = []
    lines = log.splitlines()

    _NOISE_PREFIXES = ("note:", "warning:", "i searched for")

    def _is_noise(line: str) -> bool:
        low = line.lower().lstrip()
        return any(low.startswith(p) for p in _NOISE_PREFIXES)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("!") or (
            "error:" in stripped.lower() and not _is_noise(stripped)
        ):
            context = [stripped]
            for j in range(i + 1, min(i + 4, len(lines))):
                ctx = lines[j].strip()
                if ctx and not _is_noise(ctx):
                    context.append(ctx)
            errors.append(" | ".join(context))
        if len(errors) >= 10:
            break

    if not errors:
        # Fallback: last 15 non-noise, non-empty lines for diagnostics
        errors = [
            ln.strip()
            for ln in lines
            if ln.strip() and not _is_noise(ln.strip())
        ][-15:]

    return errors


def check_tectonic_available(tectonic_path: str = "tectonic") -> bool:
    """Return True if tectonic binary is accessible."""
    return shutil.which(tectonic_path) is not None

"""Tectonic LaTeX → PDF compiler wrapper."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CompileResult:
    ok: bool
    pdf_path: str | None   # absolute path to the produced PDF
    errors: list[str]      # parsed error lines from tectonic's stderr
    raw_log: str           # full stderr for debugging
    fatal: bool = False    # True = Tectonic env/network issue, retrying won't help
    page_count: int | None = None
    overfull_boxes: list[str] = field(default_factory=list)
    overflow: bool = False
    error_code: str | None = None


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
            error_code="compiler_unavailable",
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
            # Point fontconfig at Windows system fonts so Tectonic's TeX engine
            # can initialise without "Cannot load default config file" errors.
            # Use a temp cache dir to avoid permission issues with the system cache.
            fc_cache = (tmp_path / "fontcache").as_posix()
            fc_file = tmp_path / "fonts.conf"
            fc_file.write_text(
                '<?xml version="1.0"?>\n'
                '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
                '<fontconfig>\n'
                '  <dir>C:/Windows/Fonts</dir>\n'
                f'  <cachedir>{fc_cache}</cachedir>\n'
                '</fontconfig>\n'
            )
            env = {**os.environ, "FONTCONFIG_FILE": str(fc_file)}

        timed_out = False
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
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            def text_output(value: str | bytes | None) -> str:
                return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
            result = subprocess.CompletedProcess(
                exc.cmd, 1, stdout=text_output(exc.stdout), stderr=text_output(exc.stderr)
            )

        raw_log = result.stderr + result.stdout
        tex_log_path = tmp_path / "resume.log"
        if tex_log_path.exists():
            raw_log += "\n=== TeX log ===\n" + tex_log_path.read_text(
                encoding="utf-8", errors="replace"
            )
        dest_dir = output_dir or Path(tempfile.mkdtemp(prefix="resume_agent_pdf_"))
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Exclusive writes preserve prior attempt diagnostics and canonical bytes.
        with (dest_dir / "tectonic_raw.log").open("x", encoding="utf-8") as stream:
            stream.write(raw_log)
        overfull = [line.strip() for line in raw_log.splitlines()
                    if re.search(r"Overfull\s+\\[hv]box\b", line, re.IGNORECASE)]
        pages = re.search(r"Output written on .*?\((\d+) pages?\b", raw_log)
        diagnostics = {"overfull_boxes": overfull, "overflow": bool(overfull),
                       "page_count": int(pages[1]) if pages else None}
        produced_pdf = tmp_path / "resume.pdf"

        if result.returncode != 0 or not produced_pdf.exists():
            # The TeX .log file contains the real error messages (package errors,
            # undefined commands, etc.) — stderr only has Tectonic's own notes.
            errors = _parse_tectonic_errors(raw_log)
            fatal = False
            error_code = "compile_syntax" if re.search(
                r"(?m)^\s*!|(?:LaTeX|Package\s+\S+)\s+Error:", raw_log
            ) else "compile_environment"
            if timed_out:
                errors = [f"Tectonic timed out after {timeout}s", *errors]
                error_code = "compile_timeout"
            elif not errors:
                errors = ["Tectonic exited with an error but produced no diagnostic output."]
                fatal = True
            return CompileResult(ok=False, pdf_path=None, errors=errors, raw_log=raw_log,
                                 fatal=fatal, error_code=error_code, **diagnostics)

        # Copy PDF to a stable destination. If no destination is supplied, use
        # a second temp directory that survives this context manager; tmp_path
        # itself is deleted when the source build directory closes.
        dest_pdf = dest_dir / "resume.pdf"
        if produced_pdf.resolve() != dest_pdf.resolve():
            with produced_pdf.open("rb") as source, dest_pdf.open("xb") as target:
                shutil.copyfileobj(source, target)

        if diagnostics["page_count"] is None:
            try:
                from pypdf import PdfReader
                diagnostics["page_count"] = len(PdfReader(dest_pdf).pages)
            except Exception:
                pass  # Malformed/unreadable PDFs are rejected by the PDF validator.
        return CompileResult(ok=True, pdf_path=str(dest_pdf), errors=[], raw_log=raw_log,
                             **diagnostics)


def _parse_tectonic_errors(log: str) -> list[str]:
    """
    Extract the most relevant error lines from tectonic output.
    LaTeX errors start with '!' or contain 'error:'.
    'note:' and 'warning:' lines are informational and skipped.
    """
    errors: list[str] = []
    lines = log.splitlines()

    _NOISE_PREFIXES = ("note:", "warning:", "i searched for")  # noqa: N806

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

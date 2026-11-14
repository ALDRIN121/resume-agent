"""PDF Compiler node — compiles LaTeX source to PDF using Tectonic."""

from __future__ import annotations

from uuid import uuid4

from ..artifacts import RunArtifacts, hash_file
from ..config import ResumeAgentSettings
from ..state import ResumeGenState
from ..tools.tectonic_compile import check_tectonic_available, compile_latex
from ..ui.panels import print_info, print_warning


def pdf_compiler_node(
    state: ResumeGenState, *, settings: ResumeAgentSettings | None = None
) -> dict:
    """
    Compile state["latex_source"] to a PDF using Tectonic.
    On success: sets pdf_path, clears pdf_errors.
    On failure: sets pdf_errors for the retry loop.

    Every compile has an immutable run-owned attempt directory.
    """
    settings = settings or ResumeAgentSettings.load()
    latex_source = state.get("latex_source", "")

    if not latex_source:
        return {"pdf_errors": ["No LaTeX source to compile"]}

    # Fail fast on missing tool — retrying generation won't fix a missing binary.
    if not check_tectonic_available(settings.latex.tectonic_path):
        raise RuntimeError(
            f"Tectonic not found at '{settings.latex.tectonic_path}'.\n"
            "Install it first, then retry:\n"
            "  • macOS/Linux binary: https://tectonic-typesetting.github.io/\n"
            "  • Via cargo:          cargo install tectonic\n"
            "  • Via conda:          conda install -c conda-forge tectonic\n\n"
            "After installing, run:  resume-generator doctor"
        )

    print_info("Compiling PDF with Tectonic…")

    run = RunArtifacts.create(state.get("artifact_id") or str(uuid4()))
    previous = state.get("attempt_number", 0)
    if type(previous) is not int or previous < 0:
        raise ValueError("Previous attempt number must be a nonnegative integer")
    attempt = run.attempt(previous + 1)
    with attempt.source_path.open("x", encoding="utf-8") as stream:
        stream.write(latex_source)
    owned = {"artifact_id": run.artifact_id, "attempt_number": attempt.number}

    result = compile_latex(
        latex_source,
        tectonic_path=settings.latex.tectonic_path,
        timeout=settings.latex.compile_timeout_seconds,
        output_dir=attempt.attempt_dir,
    )

    if result.ok:
        attempt.write_manifest({
            "artifact_id": run.artifact_id, "attempt_number": attempt.number,
            "pdf_hash": hash_file(attempt.pdf_path), "page_count": result.page_count,
            "overfull_boxes": result.overfull_boxes, "overflow": result.overflow,
        })
        print_info(f"PDF compiled successfully → {result.pdf_path}")
        return {**owned, "pdf_path": result.pdf_path, "pdf_errors": []}

    # Write the full raw log (stderr + TeX .log) to disk for debugging.
    if result.raw_log and not attempt.log_path.exists():
        with attempt.log_path.open("x", encoding="utf-8", errors="replace") as stream:
            stream.write(result.raw_log)

    if result.fatal:
        raise RuntimeError(
            "Tectonic failed without any error output — this is almost always a\n"
            "network or firewall issue preventing Tectonic from downloading TeX packages.\n\n"
            "Fix options:\n"
            "  1. Allow tectonic.exe outbound HTTPS access in your firewall/antivirus.\n"
            "  2. Pre-download packages by running once in a terminal:\n"
            "       tectonic -X compile your_file.tex\n"
            "  3. Use a Tectonic offline bundle:\n"
            "       https://tectonic-typesetting.github.io/book/latest/faq.html"
        )

    print_warning(f"Tectonic compilation failed ({len(result.errors)} error(s)):")
    for err in result.errors[:10]:
        print_warning(f"  {err}")

    return {**owned, "pdf_path": None, "pdf_errors": result.errors}

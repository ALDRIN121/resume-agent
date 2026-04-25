"""PDF Compiler node — compiles LaTeX source to PDF using Tectonic."""

from __future__ import annotations

from ..config import CONFIG_DIR, ResumeAgentSettings
from ..state import ResumeGenState
from ..tools.tectonic_compile import check_tectonic_available, compile_latex
from ..ui.panels import print_info, print_warning

# Stable working directory — reused/overwritten on each run, never fills /tmp
_WORK_DIR = CONFIG_DIR / "_working"


def pdf_compiler_node(state: ResumeGenState) -> dict:
    """
    Compile state["latex_source"] to a PDF using Tectonic.
    On success: sets pdf_path, clears pdf_errors.
    On failure: sets pdf_errors for the retry loop.

    Uses a stable working directory (~/.resume_generator/_working/) so the PDF
    path remains valid for downstream nodes without leaking temp directories.
    """
    settings = ResumeAgentSettings.load()
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

    _WORK_DIR.mkdir(parents=True, exist_ok=True)

    result = compile_latex(
        latex_source,
        tectonic_path=settings.latex.tectonic_path,
        timeout=settings.latex.compile_timeout_seconds,
        output_dir=_WORK_DIR,
    )

    if result.ok:
        print_info(f"PDF compiled successfully → {result.pdf_path}")
        return {"pdf_path": result.pdf_path, "pdf_errors": []}

    # Write the full raw log (stderr + TeX .log) to disk for debugging.
    if result.raw_log:
        _WORK_DIR.mkdir(parents=True, exist_ok=True)
        (_WORK_DIR / "tectonic_raw.log").write_text(result.raw_log, encoding="utf-8", errors="replace")

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

    return {"pdf_path": None, "pdf_errors": result.errors}

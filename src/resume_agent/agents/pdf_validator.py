"""
PDF Validator agent node — vision LLM checks each page for layout issues.

Uses a multimodal model (claude-opus-4-6 or gpt-4o) to inspect PNG screenshots
of each PDF page and identify alignment/formatting problems.
"""

from __future__ import annotations

import base64

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import ResumeAgentSettings
from ..llm import get_chat_model
from ..state import ResumeGenState
from ..ui.panels import print_info, print_warning

_SYSTEM = """\
You are a meticulous resume layout reviewer inspecting one rendered PDF page.

The resume uses a small-caps section heading with a horizontal rule, and custom
itemize macros (\\resumeSubheading, \\resumeProjectHeading, \\resumeItem) that
produce a left-aligned title with a right-aligned date/location, followed by
indented bullet points with $\\bullet$ markers.

EVALUATE THIS PAGE FOR THESE ISSUES SPECIFICALLY:

A. Margins & overflow
   - Any text touching or crossing the left/right page edge
   - Lines that extend past the right margin (look at section rules — body text
     should never exceed the rule line's right edge)
   - Bottom-of-page text running off the page

B. Alignment
   - Two-column rows in \\resumeSubheading where the right column (dates) is
     not right-flush, or the left column wraps awkwardly into the right column
   - Bullet points whose text indentation differs from sibling bullets
   - Bullet markers ($\\bullet$) not visually aligned in the same column

C. Vertical rhythm
   - Section headings with their underline rule but no body content beneath
     (orphaned heading at page bottom)
   - First or last bullet of an itemize stranded alone on a page (widow/orphan)
   - Inconsistent gap between sections (one section noticeably tighter or
     looser than its peers)
   - Large empty whitespace block in the middle or bottom of the page that
     suggests a forced page break

D. Typography
   - Mismatched font sizes inside the same section (e.g. one bullet rendered
     bigger than its siblings)
   - Unescaped special characters showing as literal LaTeX (e.g. a literal &
     instead of \\&, $$ instead of $|$, % truncating the line)
   - Hyperlinks rendered with stray brace characters or incorrect colour
   - Header (name + contact line) wrapping onto more than 2 lines

E. Content sanity (visible problems only)
   - Empty bullet ($\\bullet$ with nothing after it)
   - Duplicate adjacent bullets
   - Heading text colliding with the rule above/below it

OUTPUT FORMAT — STRICT.

If everything looks clean: respond with EXACTLY the single word PASS (no
punctuation, no explanation).

Otherwise list each defect on its own line in this format:
  Page {N} | Section "{visible heading}" | Issue: {what is wrong, precise} | Fix: {concrete LaTeX-level change}

The Fix must be something a LaTeX-savvy editor can act on, e.g.
"shorten the third bullet under Acme Corp to under 130 characters" or
"move the Education section before Certifications to absorb whitespace".
Vague fixes ("improve spacing") are not acceptable.
"""

_HUMAN_IMAGE = "Please evaluate the layout quality of this resume page."


def pdf_validator_node(state: ResumeGenState) -> dict:
    """
    Check each PDF page image for layout problems using a vision LLM.
    Sets validation_passed=True or provides validation_feedback for retry.
    """
    page_images: list[str] = state.get("page_images", [])

    if not page_images:
        # No images to validate — skip (already handled in render_pages)
        return {"validation_passed": True, "validation_feedback": None}

    settings = ResumeAgentSettings.load()
    llm = get_chat_model(settings, task="vision", temperature=0.0)

    print_info(f"Validating layout of {len(page_images)} page(s) with vision model…")

    all_feedback: list[str] = []
    check_errors: list[int] = []  # page numbers where vision API failed

    for i, img_path in enumerate(page_images, 1):
        feedback = _check_page(llm, img_path, page_num=i)
        if feedback is None:
            check_errors.append(i)
        elif feedback.strip().upper() != "PASS":
            all_feedback.append(feedback.strip())

    if check_errors:
        pages = ", ".join(str(p) for p in check_errors)
        all_feedback.append(
            f"Vision check unavailable for page(s) {pages} — layout unverified."
        )

    if not all_feedback:
        print_info("Layout validation passed — all pages look good.")
        return {"validation_passed": True, "validation_feedback": None}

    combined = "\n".join(all_feedback)
    print_warning(f"Layout issues found on {len(all_feedback)} page(s).")
    # Print detailed feedback so Resume Writer can address specific issues
    for line in all_feedback:
        print_info(f"  → {line}")
    return {"validation_passed": False, "validation_feedback": combined}


def _check_page(llm, img_path: str, *, page_num: int) -> str | None:
    """
    Run vision check on a single page image.

    Returns:
        "PASS" if the layout is clean.
        A feedback string if issues are found.
        None if the vision API call failed (caller must not treat as PASS).
    """
    img_data = _encode_image(img_path)
    media_type = "image/png"

    # Build multimodal message (works with Claude and GPT-4o via LangChain)
    messages = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(
            content=[
                {"type": "text", "text": f"Page {page_num}. {_HUMAN_IMAGE}"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{img_data}"},
                },
            ]
        ),
    ]

    try:
        response = llm.invoke(messages)
        return response.content
    except Exception as e:  # noqa: BLE001
        print_warning(f"Vision check failed for page {page_num}: {e}")
        return None  # Signal unavailable — caller must not treat as PASS


def _encode_image(path: str) -> str:
    """Base64-encode an image file for inline embedding."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

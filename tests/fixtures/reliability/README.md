# Fictional reliability inputs

All names, employers, accomplishments, dates, job requirements, and identifiers
in this directory were invented for tests. `example.invalid` is deliberately
non-deliverable. No personal resume, credentials, production history, or network
resource was copied. These are inputs, not assertions approving future fixes.

| Input / reproducible failure case | Owner |
| --- | --- |
| `profile.json`: identical observability bullet in two different roles. Text-only selection can target the wrong role. | T05 structured edit identity |
| `profile.json`: 450ms to 90ms reduction. A rewrite can reverse the metric while retaining both numbers. | T05 edit review; T06 faithful rendering |
| `profile.json`: “Helped” and “Assisted” describe contributions. Rewriting them as platform ownership overstates scope. | T05 edit review; T06 faithful rendering |
| `job.txt`: required AND and preferred OR groups plus a regional restriction. | T04 full import; T13 later fit calculations |
| Long JD recipe: prepend `("Context detail. " * 600)` to `job.txt`; the tail marker/restriction then lies beyond the old 8,000-character extraction window. Prepend 150 repetitions to exercise persisted-text truncation independently. | T04 complete JD delivery/storage |
| Long resume recipe: prepend `("Resume context. " * 900)` to a plain-text rendering of `profile.json`, with its final education entry as the tail marker beyond character 12,000. Test 48,000 and 48,001 characters separately. | T04 full import and explicit limits |
| Partial PDF recipe: render a first text page from `profile.json` and a second image-only page carrying `RELIABILITY_SCANNED_PAGE_MARKER`; extract both pages and retain the page warning. A successful first page currently hides the incomplete second page. | T04 per-page import warnings |
| Interleaved artifacts recipe: create two local PDFs with literal markers `RELIABILITY_RUN_A` and `RELIABILITY_RUN_B`; compile A, compile B, render/save A, then save B. Repeat with equal company names. Shared `_working/resume.pdf` can cross-contaminate the bytes. | T03 run-owned artifacts |
| `legacy_history.jsonl`: complete, missing-artifact, failed, cancelled, paused (`awaiting-input`), and deliberately malformed records. Relative artifact paths are inert labels; owner tests must map them into temporary storage and create only the complete PDF. | T02 migration; T08 legacy/restart recovery |

The final JSONL line is intentionally invalid JSON. The paused summary contains
no checkpoint or event stream, matching the information missing from legacy
history. It does not invent a recoverable v2 run or imply a release guarantee.
Each owner task adds its own failing regression and acceptance rule before its
production change; T01 only establishes safe state and reusable source material.

Before importing application modules, `tests/conftest.py` creates a temporary
`RESUME_GENERATOR_STATE_DIR`, removes inherited provider credentials and settings
overrides, and uses LiteLLM's bundled cost map. Package and server subprocesses
must inherit that environment; Python `-I` alone does not isolate app storage.
Tests needing independent module-bound paths should use a fresh child process
with a distinct explicit state root. Never point test `HOME` at the real home;
the isolation subprocess tests use temporary sentinel homes only.

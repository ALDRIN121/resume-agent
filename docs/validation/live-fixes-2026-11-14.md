# Live failures fixed and verified

Date: 14 November 2026, Asia/Kolkata. Code revision: `362a3b5`. Provider: Command Code. Model: `deepseek/deepseek-v4.1-flash`.

**Both reported live failures are fixed. A fresh browser journey reached reviewed export. Its preview, download and exported file have the same PDF hash. C4 remains open for external certification.**

## What changed

| Failure | Cause and fix | Verification |
| --- | --- | --- |
| `pdf_content_mismatch` for `Tools` | Font kerning caused pypdf to extract `T ools`. The deterministic template now disables kerning. The strict content comparator is unchanged. | Three real-compiler cases failed before the fix: heading, body and name fonts. All pass afterward. All 56 focused PDF/render checks passed. |
| `truncated_output` during role evaluation | A diagnostic response used all 16,384 completion tokens for reasoning and returned zero answer characters. The evaluation prompt required exact character offsets. The app now supplies a deterministic citation catalog with exact Unicode start/end offsets and source quotes. | Five new catalog/input tests failed before implementation. All 37 focused evaluation/scoring tests passed afterward. The same-model diagnostic returned a schema-valid, source-valid result with 9,894 completion tokens. A fresh actual browser evaluation also passed. |

The fix keeps complete JD text and existing source/hash validation. Stored operation inputs remain unchanged. The derived catalog is included in model-task input identity. Citation references are still checked against the original text. No model, API route, token limit, score formula or retry budget was changed.

The provider's native thinking toggle was tested and ignored in this case. A `none` effort request was rejected; `low` effort timed out. Those diagnostic approaches were not added to production. The final repair gives deterministic bookkeeping to application code instead of relying on provider-specific reasoning controls.

## Fresh real-model browser journey

The application ran in isolated state with fictional Casey Example and an Example Cloud Platform Engineer posting. No model or API double was injected.

1. Upload a fictional TEX resume through the browser.
2. Inspect the actual parsed profile and accept the test import.
3. Save the full posting and run the actual model evaluation.
4. Inspect the valid evaluation, its evidence interval and unknowns.
5. Explicitly override advisory `review` to generate in this QA scenario.
6. Answer two live questions about work preferences and testing tools.
7. Inspect three proposals, all initially unselected.
8. Select only the experience-bullet edit that adds explicitly supplied pytest evidence.
9. Review and confirm the complete content projection.
10. Compile the PDF and run strict content checks.
11. Inspect the actual page image and PDF review.
12. Approve the exact fictional preview through the browser.
13. Verify completion, final download and export bytes.

| Evidence | Result |
| --- | --- |
| Import | `66e69cc0-201e-4cec-bb47-1de5b9e1f8cb`, complete |
| Evaluation | `1803baee-5dea-40eb-9fcc-1f480c950211`, complete and not stale |
| Evaluation result | Interval 70.31–92.19; coverage 78.12%; eligibility unknown; recommendation `review` |
| Generation | `4b0724af-7321-44ef-9bf2-5f6819207a7b`, complete |
| Content | One selected proposal applied. Projection matched the stored approved content. No Kubernetes claim was added. |
| PDF | One page, standard layout, no overflow, exact content check passed |
| PDF SHA-256 | `03e464149c993814aed913a7a164ea03d05995da3a511c3dd292186c9970e92a` |
| Release identity | Preview hash = final-download hash = exported-file hash |
| Advisories | HR review passed; repeated supplied skill text remained visible as an advisory; optional vision was disabled |
| Applications | Zero application records or submissions |

These approvals were explicit fictional QA actions. They are not decisions about the owner's profile or volunteer-pilot results. The score is descriptive evidence fit, not a hiring probability.

## Regression and visual checks

| Check | Result |
| --- | --- |
| Python 3.12, required browser/PDF flags | **943 passed, zero failures, zero skips**, 7 upstream warnings, 271.54 seconds |
| JUnit guard | 943 tests; no failures, errors or skips |
| Python 3.13 ordinary compatibility | **878 passed, 65 explicitly disabled browser/PDF checks**, 7 warnings, 54.18 seconds. Those checks ran in the flagged Python 3.12 suite. |
| Frontend | 15 tests passed; production build passed with the same tracked bundle |
| Lint/whitespace | Source Ruff and `git diff --check` passed |
| Representative PDFs | Regenerated all ten cases with the new template. Exact content/export hashes passed. All eleven page images were visually inspected. |

The known presentation limits remain: equal social handles lack platform labels, explicitly approved repeated text is retained, and a long paragraph can continue across pages. No clipping, overlap or missing glyphs was observed in the inspected cases.

## Current state

The normal app was restarted with the fixes and verified at `http://127.0.0.1:18731/`. No generation was running before restart. Temporary test/browser services were stopped. Personal resumes and applications were unchanged.

Five owner-arranged pilots, Linux/native Windows certification and authenticated Claude validation remain open. No push, tag or publication occurred. The app remains a local 3.3.0 candidate.

Raw evidence is retained in `live-fixes-2026-11-14/` under the ignored execution workspace: red/green logs, required-suite XML, model-completion diagnostics, live browser records, inspected page images, released PDF, representative PDF inventory and hashes. Historical failure reports are retained and superseded by this result.

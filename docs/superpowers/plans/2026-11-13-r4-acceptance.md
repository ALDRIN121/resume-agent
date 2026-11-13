# R4 acceptance record — 3.3.0 candidate

Updated 14 November 2026. Branch: `codex/resume-agent-r1`. **C4 remains OPEN.** The candidate has not been pushed, tagged or published. Local implementation is distinct from external release certification.

## Scope and revisions

T01–T21 are implemented locally. T22's author-owned checks, representative PDF inspection, final review and package preparation are recorded here. T22 cannot close until its external evidence exists.

The first candidate freeze was `b075271255b8ef02155aaa0f024c4a68eddc20b4`. The independent review found three Important recovery defects. Runtime fix `aa19fea78c6bcc557c3d550f69a277a3ec26e05c` addresses all three. The final test revision is `b0098aa01490df784645a8ca6639f5e38400f4fc`; it also checks the updated upload test fixtures. See the [review and fix record](../../validation/final-branch-review-2026-11-14.md).

## Local verification

| Check | Result and evidence |
| --- | --- |
| Python 3.12, all required flags | **935 passed, zero failures, zero skips**, 7 upstream warnings, 228.12 seconds. JUnit failure/error/skip guard passed. The earlier 934-pass/one-failure run and its stale-fixture diagnosis are retained. |
| Python 3.13 compatibility | 873 passed, 62 explicitly disabled browser/PDF tests, 7 upstream warnings, 54.32 seconds. Those 62 checks must run in the flagged Python 3.12 matrix. |
| Frontend | 15 tests passed. Production build passed. Bundle: `index-D-KELynJ.js`, `index-D26JeVwS.css`. |
| Recovery regressions | 100 focused backend tests passed. Both new actual API/browser restart journeys passed. |
| Source lint and whitespace | Ruff passed for source and the new recovery tests. `git diff --check` passed. |
| Package and interface parity | Installed-wheel UI, source archive, portable skill/export and JSON/shared-service parity are included in the full Python matrices. Final retained artifacts were built from `b6b7754`. Five package tests and six checks on those exact artifacts passed. See the [artifact hashes](../../validation/candidate-artifacts-2026-11-14.json). |
| Synthetic journeys | All **30 named journeys** passed in the final complete matrix, including six new recovery cases. See the [journey record](../../validation/synthetic-journeys-2026-11-13.md). |
| Representative PDFs | Ten released fictional PDFs, eleven pages. Actual compiler, extraction, rendering, exact content guard and byte-hash checks passed. All eleven page images were inspected. See the [PDF review](../../validation/pdf-review-2026-11-13.md). |
| Independent branch review | One fresh reviewer; three Important findings accepted and fixed with failing-then-passing regression tests. No Critical or separate Minor findings. No second review claim. |
| Additional live configured-provider check, 14 November | Actual browser Settings → Re-test failed for Command Code / `deepseek/deepseek-v4.1-flash`: authentication/access error, 909 ms, empty reply. A key/access update is needed before a full live-model journey. See the [live result](../../validation/live-provider-2026-11-14.md). |

The initial stale fixture matched `/api/resume/upload` exactly and missed `?defer_processing=true`. It therefore did not inject its intended upload error. The corrected fixture accepts the query and asserts that the actual request contains it. No production behavior was weakened to make that test pass.

Final archive inspection found local `Frontend/node_modules` in the source archive. A strengthened exclusion test failed before the fix. The build now excludes that folder explicitly; all five package tests pass. The source archive fell from 10,948,574 to 1,170,576 bytes. The wheel hash stayed unchanged. Runtime code did not change after the complete 935-test matrix. The final archive, installed UI, exported skill, metadata and tracked frontend bytes were checked again.

## Environment and inputs

| Item | Recorded value |
| --- | --- |
| Operating system | macOS, Darwin 27.0.0, arm64 |
| Python | 3.12.7 and 3.13.2 |
| Browser | Chrome 157.0.8103.52; Playwright 1.58.0 |
| PDF tools | Tectonic 0.15.0; installed Poppler extraction/rendering tools |
| Core libraries | Pydantic 2.13.1; LangGraph 1.1.6 |
| Generation models | Deterministic structured-response fixtures. No paid configured-provider model calls. |
| Actual host probe | Codex CLI 0.153.4; actual model not reported. Claude Code 2.1.285 stopped before inference because OAuth had expired. |
| Data | Fictional profiles, role descriptions, feeds and answers. Isolated local application state. |
| Interfaces | Actual API, WebSocket, SQLite, checkpoint store, browser, CLI and installed wheel where named by the tests. External model/feed boundaries are substituted where documented. |

Ten-PDF visual evidence was generated on `b075271`; the recovery fixes do not change the renderer, templates, content projection or PDF guard. Its original provenance is retained. The final full matrix reruns real-tool PDF checks against the repaired code.

## C4 requirements

| Requirement | Disposition |
| --- | --- |
| Released content and approved PDF bytes match | Covered by exact content/hash checks, real-tool journeys and the ten-PDF record. No mismatch observed in that evidence. |
| Approved edits produce an outcome; rejected edits do not change output | Selected/rejected proposal and exact-target tests, plus real review/export journeys. |
| Durable pauses survive restart in tested interfaces | Lifecycle, model budget, external request, import, review, release, memory and discovery recovery checks. The final review's three missing cases now have explicit regressions. |
| Legacy migration preserves access and invents no approval/submission | Migration rollback/idempotency and visibly unverified legacy recovery tests. |
| C2/C3 career workflows pass | Local C2/C3 acceptance passed; their regressions remain in the final matrix. |
| JSON commands preserve shared contracts | Closed-stdin JSON, typed actions, stale decisions, exact preview/export and installed-package parity checks. |
| External-agent mode invokes no configured backend in tested journey | Structured host-mode lifecycle tests, including actual PDF tools, reject backend-factory/callback calls. |
| Every claimed host passes recorded smoke | Codex's named review-handoff smoke passed. Claude remains unsupported and its authenticated check remains OPEN. No universal-host claim. |
| Four of five pilots finish without developer help; zero identity mismatch | **OPEN: zero sessions recorded.** The [pilot procedure and five-session record](../../validation/volunteer-pilots.md) are ready for owner scheduling. |
| Required checks have zero unexplained failures or skips | Local post-fixture matrix passed with zero failures and zero skips. Remote Linux/native Windows checks remain OPEN. |

## External gates and next checkpoints

1. Run the configured Linux and native Windows jobs against the exact candidate revision. Record their logs and outcomes. Do not claim support from local macOS results.
2. Have the owner restore Claude authentication. Run the documented authenticated host smoke. Do not change sign-in as part of implementation.
3. Arrange five voluntary pilot sessions. Record setup time, first reviewed PDF, assistance, interruption recovery, factual review and identity hashes. At least four must finish without developer help, with zero artifact identity mismatches.
4. Reassess C4 using those actual records. Keep 3.3.0 a candidate if a required gate remains open or fails.
5. Review the exact artifacts and [publication checklist](../../publication-checklist.md). Push, tag, remote settings and publication require separate authorization.

## Limits and rollback

The evidence does not establish adoption, hiring outcomes, predictive score validity, universal factual correctness, all languages or every host/model. Public feeds were tested with controlled responses; live provider drift is not certified. Small outcome samples remain suppressed. Local typed actions are not cryptographic human identity.

The inspected template can show ambiguous equal social handles, retain duplicate wording that was explicitly approved, and split a paragraph across pages. Legacy downloads remain labelled unverified. V2 audit-history deletion is unavailable pending retention design.

Use the [complete state backup and rollback procedure](../../candidate-rollback.md). Database migrations are forward-only. Do not run older code against a newer live database or restore only one of the matching databases. No personal-state rollback was performed.

All execution rulings and their costs are in the [decision record](../../validation/implementation-decisions-2026-11-14.md). Raw logs, JUnit files, source/PDF inventories and package hashes remain in the ignored execution workspace while external C4 is open. Existing `.egm/` files and personal application state were preserved.

The original plan/specification status, file inventories, checkboxes and EGM wording findings have been reconciled. See the [A01–A23 disposition record](../../validation/pending-plan-review-2026-11-14.md). This is an implementation traceability update, not a repeat of the five-stage EGM review or dictionary-certified ASD-STE100 compliance.

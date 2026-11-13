# Upgrade implementation status

Updated 14 November 2026. Branch `codex/resume-agent-r1`. All commits are local. Nothing has been pushed, tagged or published.

**Feature code and both live fixes are implemented locally. The required suite passed 943 tests with zero failures or skips. A fresh real-model browser journey reached reviewed export with identical preview/download/export bytes. C4 remains OPEN for external evidence.** See the [verified fixes](../../validation/live-fixes-2026-11-14.md).

| Work | Implemented result | Checkpoint |
| --- | --- | --- |
| T01–T05 | Isolated state, durable lifecycle, separate artifacts, complete imports and exact selected content | Producer reviews and regression checks passed. |
| T06–T10 | Deterministic PDF rendering, exact-byte release, startup/legacy recovery, shared app/API/CLI and bounded model retries | Local C1 behavior accepted. Later final-review recovery fixes have explicit regressions. |
| T11 | Browser, compiler, package and platform test preparation | Local macOS checks pass. Linux/native Windows CI is configured but has not run. |
| T12–T14 | Reviewed memory, immutable jobs, evidence-based evaluation, explicit generation overrides and UI/CLI controls | Local C2 passed. See the [R2 acceptance record](2026-11-13-r2-acceptance.md). |
| T15–T18 | Explicit application events, audited corrections, descriptive outcomes, bounded discovery and tracker/search controls | Local C3 passed. See the [R3 acceptance record](2026-11-13-r3-acceptance.md). |
| T19–T21 | Non-interactive JSON commands, durable external-agent model requests, portable skill, package export and distribution preparation | Codex's named handoff smoke passed. Claude remains unsupported until authenticated validation passes. |
| T22 | Complete local matrix, ten-PDF inspection, synthetic journeys, final independent review, fixes and candidate artifacts | See the [R4 acceptance record](2026-11-13-r4-acceptance.md) for exact results and remaining gates. |

The web app, API and CLI share the reviewed workflow. Full source inputs remain saved. Wording proposals start unselected. Content confirmation and exact PDF-byte approval are separate. An import creates a draft and replaces the profile only after an explicit reviewed decision.

The final independent review found three Important recovery defects and no Critical defects. All three were accepted and fixed in one test-first pass: Continue now reuses an owned export reservation; a cleanup ownership conflict stays attached to its run; saved imports are discoverable and have explicit Continue/Cancel controls. See the [review report](../../validation/final-branch-review-2026-11-14.md).

The final Python 3.12 matrix passed **943 tests with zero failures and zero skips**. Python 3.13 passed **878 tests**, with 65 browser/PDF checks explicitly disabled and covered by the flagged 3.12 run. All 15 frontend tests and the production build passed. Seven upstream warnings remain visible.

The final local evidence uses fictional data, isolated state, actual API/browser/checkpoint infrastructure and real PDF tools. Model and feed boundaries use controlled responses where documented. The separate actual Codex probe covers a named review handoff, not every host, model or setup journey.

Three external gates remain:

1. Record five owner-arranged volunteer pilots. Four must reach a reviewed PDF without developer help. No session may have an artifact identity mismatch.
2. Run and record Linux and native Windows certification against the exact candidate.
3. Restore Claude authentication through the owner's host flow, then run its smoke check. Authentication was not changed during implementation.

The reconciled [plan/review disposition](../../validation/pending-plan-review-2026-11-14.md) lists every original EGM action. The [pilot record](../../validation/volunteer-pilots.md), [rollback procedure](../../candidate-rollback.md), [publication checklist](../../publication-checklist.md) and [complete decision record](../../validation/implementation-decisions-2026-11-14.md) are ready. Required external evidence must exist before C4 can pass. No hiring-outcome, adoption or universal reliability claim is made.

Raw evidence remains under `.superpowers/sdd/2026-11-12-resume-agent-reliability-and-search/` while C4 is open. The existing `.egm/` directory and personal application state remain untouched.

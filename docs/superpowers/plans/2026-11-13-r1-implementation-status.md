# Upgrade implementation status

Updated 13 November 2026. Branch `codex/resume-agent-r1`. All commits are local; nothing has been pushed or published.

The reliable generation workflow now serves the web app, API and CLI. It saves complete source inputs, collects evidence, offers unselected wording changes, confirms the complete content, checks the rendered PDF and requires approval of the exact PDF bytes before export. Import parsing creates a reviewable draft and never replaces the base resume on its own.

| Work | Status |
| --- | --- |
| T01–T05: isolated state, durable lifecycle, separate artifacts, full imports, exact content | Implemented and independently reviewed |
| T06–T08: deterministic PDF, exact release, startup/legacy recovery and reexport | Implemented; recovery fixes independently approved |
| T09: shared app/API/CLI, saved form drafts, readiness and review screens | Integrated; controller verification passed locally |
| T10: durable model retry owner | Implemented; independent review and regression fixes approved |
| T11/C1: acceptance, package and platform checks | Python 3.12 and 3.13: **710 passed, 46 skipped** each. Required browser/PDF/native-path suite: **54 passed, zero skips** before final recovery regressions. The two new navigation fixtures were corrected; all three real journeys then passed. All 55 distinct required checks pass across the combined and focused runs. Local C1 behavior gate passes. |
| T12–T14/C2: reviewed memory, immutable jobs and evidence-based role decisions | T12–T14 implemented. Local C2 passes: Python 3.12/3.13 each 772 passed; required browser/PDF suite 63 passed with zero skips; frontend 14 tests and build pass. See the R2 acceptance matrix. Application tracking is next. |
| T15–T18/C3: applications, outcomes and bounded discovery | T15–T16 application events, outcome evidence and truthful dashboard/company counts implemented; full suite 798 passed and 45 focused browser checks passed. Discovery and tracker integration are next; C3 pending. |
| T19–T22/C4: structured CLI, host execution and distribution | Not implemented |

The 46 full-suite skips are browser journeys disabled in the ordinary unit command. These run separately with required servers and real PDF tools. Seven upstream warnings remain visible. An initial ordinary run could not open a local socket; the approved local-socket rerun passed on both Python versions.

Source lint passes. All **12 frontend tests** pass and the production bundle builds. Real generation uses the actual API, WebSocket, SQLite, Tectonic and Poppler with only model responses substituted. Installed-wheel and source-archive checks pass. The acceptance matrix records each C1 requirement.

Linux CI and native Windows jobs are configured but **have not run here**. Their results remain required before claiming platform support or publishing. The same lock and Unicode/space path tests pass locally on macOS. Later private development may proceed after local C1 behavior acceptance; this does not certify untested platforms.

Detailed evidence and the ledger are under `.superpowers/sdd/2026-11-12-resume-agent-reliability-and-search/`. The existing `.egm/` directory and personal application state remain untouched.

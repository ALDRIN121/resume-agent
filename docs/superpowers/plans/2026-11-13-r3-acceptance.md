# R3 local acceptance — C3

13 November 2026. **Local behavioral checkpoint: PASS.** Version 3.2.0 is a local candidate. Publication and remote platform certification have not occurred.

| Required behavior | Evidence |
| --- | --- |
| Generated PDFs and submissions stay separate | Application service and actual dashboard/browser tests. No generation creates a submission. |
| Submission retains chosen evidence | Real discovery → selected role → evaluation → reviewed PDF → explicit submission journey. Job IDs, evaluation ID and released PDF hash match. Unknown-document recording is explicit. |
| Corrections preserve the audit | Browser records a favorable response, then corrects it to acknowledgment. Original event remains. One submission stays pending, with zero positive outcomes. |
| Outcomes use frozen scores | Exact band arithmetic, stale evaluation freeze, missing artifacts, later rejection, withdrawals, pending and small-sample tests. |
| Discovery is bounded and manual | Provider/HTTP/service tests cover fixed URLs, pagination, malformed records, conflicts, size/concurrency/time/retry limits and no model calls. |
| Failed and partial scans preserve prior jobs | Actual browser complete → partial → failure → restart → clean empty journey. Stale active jobs remain until a complete scan establishes absence. |
| Restart and cancellation are explicit | Real server hard-kill and restart shows interrupted. No jobs appear until Continue. Request attempts advance from one to two. Cancellation publishes no incomplete board. |
| Old recovery cannot replace newer evidence | Cached older scan resumes after a newer complete scan. Newer job heads and posting states remain. |
| Source/configuration revisions protect changes | Strict typed HTTP/CLI and shared service tests. Action replay and stale revisions pass. Source form survives reload. |
| Exact source snapshots remain inspectable | Original raw record and selected job survive a newer posting version. Job selection never substitutes current provider text. |

Evidence directory: `.superpowers/sdd/2026-11-12-resume-agent-reliability-and-search/`.

- `task18-python312.log`: **834 passed, 59 browser-disabled skips, 7 upstream warnings**, 39.28 seconds.
- `task18-python313.log`: **834 passed, 59 browser-disabled skips, 7 upstream warnings**, 37.87 seconds.
- `task18-acceptance.log` and XML: **67 passed, zero skips**, 171.77 seconds. The XML skip guard passed.
- New focused journeys cover source setup, all scan result states, complete selected-role handoff, exact released document binding, local submission, response correction, draft reload, cancellation and interrupted recovery.
- Frontend: **15 tests passed**. Final build passed. After the last draft-field tightening, all three new browser journeys passed again (29.91 seconds). Installed-wheel/source-archive and adapter checks passed: seven tests (12.08 seconds).

The actual API, SQLite, checkpoints, sockets, PDF tools and filesystem perform the journeys. Only structured model responses and external public-board HTTP are substituted. Data is fictional. No employer submission, message, user-board request, branch push or package publication occurred.

Linux and native Windows CI remain unverified here. Whole-branch review remains required before distribution. Host integrations and volunteer pilots belong to C4.

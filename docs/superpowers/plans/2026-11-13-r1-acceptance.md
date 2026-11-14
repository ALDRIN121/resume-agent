# R1 3.0.0 acceptance evidence

Prepared 13 November 2026. This table records behaviors individually; a total test count is not a substitute for C1. Version metadata is 3.0.0, without publication. Full integration and platform results are recorded separately below.

The acceptance fixture uses fictional profile data, isolated state and fake credentials. Only the structured model callback is substituted. SQLite, checkpoints, API, WebSockets, imports, deterministic templates, Tectonic, Poppler, PDF checks, final review and export are real. The suite never intercepts API or socket traffic; it blocks only an external font request. Missing mandatory tools fail acceptance.

| C1 behavior | Concrete checks | Evidence and current result |
| --- | --- | --- |
| Ten interleaved same-company runs retain artifacts and hashes | `test_ten_interleaved_same_company_exports_keep_hashes`; compiler interleaving and UUID ownership tests | Producer T03: 113 focused checks passed; ten concurrent plans have ten canonical and friendly paths, committed hashes match. Final quiescent run recorded below. |
| Reject-all preserves wording; approved edits have visible results | `test_reject_all_exact_copy`, indexed duplicate-bullet projection checks; real browser reject-all and visible-edit variants | Producer T05: 64 focused checks passed. Real browser generation passes both reject-all and visible-edit variants, including all three restart pauses and exact released bytes. |
| Replaced PDF bytes and stale approval block release | `test_every_stale_review_identity_conflicts_before_reservation`, `test_canonical_tampering_blocks_preview_and_approval`, `test_tampered_draft_approval_conflicts_before_command_acceptance`; real API attempts in browser journey | Producer T07 and workflow guards passed their focused checks. Real browser generation passes both reject-all and visible-edit variants, including all three restart pauses and exact released bytes. |
| Complete supported input reaches parsing; rejected import preserves profile | Inclusive 48,000/48,001-character and 10 MiB limits, complete page coverage and blank-page confirmation; `test_real_import_source_draft_restart_reject_and_accept` | Producer T04: 56 focused checks passed. Fresh real API/browser import: **1 passed**, full 31,500-byte source download equals upload; parsing/restart do not save; reject keeps old revision; accept saves explicitly reviewed draft. |
| All human pauses survive restart; legacy recovery uses fresh review | Question/content/PDF restart parametrization, one-child legacy recovery, saved answers and replay/no duplicate release in browser journey | Producer T08: 113 focused checks passed. Real browser generation passes both reject-all and visible-edit variants, including all three restart pauses and exact released bytes. |
| Required browser checks actually execute without unexpected skips | Required CI sets browser URL and real-browser flag, starts Vite and isolated API processes; JUnit guard rejects skips | **44 mocked browser checks and 3 real browser journeys passed**, without skips. Native PDF/path checks passed in the combined run. |
| Real PDFs conserve text, obey page limits and reject overflow | Real browser journey compares complete extracted PDF token stream to approved manifest, checks actual page count, overflow and page images; real visual fixture compiles | Fresh Tectonic/visual, native platform and installed-package command: **10 passed**, no skips. Both real generation variants pass complete token equality, page count, overflow, exact bytes and verified export restoration. |

## Fresh commands and artifacts

Workspace evidence is under `.superpowers/sdd/2026-11-12-resume-agent-reliability-and-search/` (local review artifacts, not shipped package data).

- `task11-import.log`: `RESUME_REAL_BROWSER_TEST=1 PLAYWRIGHT_CHROMIUM_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' ... .venv/bin/python -m pytest tests/test_reliability_journey.py -k import -q` → **1 passed, 2 deselected**, 10.91s. Deselection is explicit for this focused command, not a required-check skip.
- `task11-package-tools.log`: `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/resume-agent-r1-build-cache RESUME_REQUIRE_PDF_TOOLS=1 .venv/bin/python -m pytest tests/test_platform_runtime.py tests/test_visual_regression.py tests/test_packaged_ui.py -q` → **10 passed**, 14.76s, one upstream LangChain deprecation warning. Includes source archive assets and an installed-wheel subprocess outside the checkout.
- `task11-browser-first.log` and `task11-browser-debug.log`: retained initial failures. The live socket revealed a feedback loop: reading an unchanged pause republished it, and the socket read triggered another publication. The production owner is fixing it with a regression test; these failures do not count as acceptance passes.
- `task11-evidence/`: browser screenshots and, after successful generation, approved PDF/source/log/image artifacts, render record and exact-byte release evidence.

## Whole-suite and distribution checks

| Check | Result |
| --- | --- |
| Quiescent Python 3.12 and 3.13 full suite and source lint | **710 passed, 46 browser-disabled skips**, on each Python version; source lint passed. The extra interrupted-reexport API regression also passed in the focused 6-case API suite. |
| Frontend test/build and existing mocked browser coverage | **12 frontend tests passed; production bundle built; all 44 mocked browser checks passed.** |
| Linux CI jobs | **NOT RUN locally**; required workflow is configured. |
| Windows Python 3.12/3.13 OS lock and Unicode/space path checks | **NOT RUN on Windows locally**; required workflow is configured. The same native tests passed on macOS. |
| Package publish, tag, push, repository settings | Not performed. |

The CI contract uses the documented [setup-uv v7 inputs](https://github.com/astral-sh/setup-uv/blob/v7/action.yml), [setup-node v6 inputs](https://github.com/actions/setup-node/blob/v6/action.yml), [upload-artifact v4 inputs](https://github.com/actions/upload-artifact/blob/v4/action.yml), and the [official Tectonic 0.15.0 release assets](https://github.com/tectonic-typesetting/tectonic/releases/tag/tectonic%400.15.0). Actions run with read-only repository contents permission. Remote job execution remains unverified until CI runs.

## Final local C1 result

**PASS for the local behavioral gate**, 13 November 2026. Linux and Windows platform certification remains unverified. This permits continued private R2 work, not publication or an unsupported platform claim.

- `r1-final-python312-local.log` and `r1-final-python313-local.log`: 710 passed, 46 skips each. Required browser checks are run separately.
- `r1-final-acceptance.log`: 53 passed and two new restoration-navigation fixture failures. All 44 mocked browser checks, real import, native paths and real PDF fixtures passed. The completed grid card uses a different label from an unfinished run; the fixture was corrected.
- `r1-real-browser-reexport.log`: all 3 real journeys passed after that correction, 35.91s. Includes actual export deletion/restoration and verifies the restored byte hash. No required check skipped.
- `reexport-api-green.log`: 6 passed, including interrupted restoration after output settings change. Recovery preserves the original action plan.
- `review-progress-red.log`: reproduced missing durable progress fields; the regression now passes. `legacy-recovery-ui-red.log`: reproduced absent legacy recovery control; that test passes in the 44-case browser result.

The final required acceptance set is 55 distinct checks: 44 mocked browser checks, 3 real journeys, and 8 native/PDF checks. Evidence is split across the combined run and focused rerun; no failed check is being counted as a pass. No remote CI, tag or release was performed.

# R1 implementation status

Updated: 13 November 2026.
Branch: `codex/resume-agent-r1`.
Starting revision: `5c1938f`.
Code checkpoint: `c751850`.

R1 is in progress. **The new review flow is not yet connected to the web app or CLI.** The current user-facing workflow remains the legacy workflow until the integration task is complete. Version 3.0.0 is not released. C1 has not passed.

## Component status

| Task | Result | Review status |
|---|---|---|
| T01: isolated state and fixtures | Built. Tests use temporary state. Explicit state roots do not import home or project secrets. | Approved |
| T02: durable runs and operations | Built. Fixed inputs, SQLite migrations, process locks, action replay and cancellation survive restart. | Approved after rejection-recovery fix |
| T03: separate artifacts and atomic copies | Built. Each run and attempt owns its files. Interrupted copies retain ownership proof. | Approved after partial-copy fix |
| T04: complete input and import drafts | Built privately. Resume and JD limit is 48,000 characters. Upload limit is 10 MiB. Profile saves check the current revision. | Approved |
| T05: explicit edits and content manifest | Built privately. Indexed edits, evidence references, declared omissions and the complete display stream are hash-bound. | Approved |
| T06: deterministic rendering | Built privately. Two fixed layouts preserve approved text. Restored records now require a distinct valid image for every page. | Final recovery fix needs re-review |
| T07: exact PDF check and final release | Built privately. Approval binds content, render and PDF hashes. Export and cancellation use the same final database transaction. | Independent review pending |
| T08: startup and legacy recovery | Incomplete. Initial regression tests are saved for the next implementation step. | Pending |
| T09: web, API and CLI integration | Not implemented. Detailed backend and frontend task briefs are saved. | Pending |
| T10: model failures and retry limits | Built privately. One retry owner permits at most two model attempts and saves the budget before each call. | Independent review pending |
| T11: release gate | Incomplete. Browser journeys, cross-platform checks and release evidence remain. | C1 pending |

## Verified checkpoint

The full Python suite ran after implementation workers stopped:

```text
634 passed, 43 skipped, 5 warnings in 28.60s
```

The 43 skipped checks need a running browser test server. These skips prevent a C1 pass. The five warnings are known upstream deprecations and an existing unregistered test marker. They were not hidden.

- Source lint passed.
- All 4 existing frontend tests passed.
- Source archive, wheel and installed-wheel UI checks passed in the full Python run.
- A real Tectonic and Poppler fixture produced one page with no overflow.
- Its entire extracted text matched the approved display text exactly, including duplicate text, `--`, straight quotes, backticks, signs, units and the order of `450ms` and `90ms`.
- Restart reused the same source, PDF, log and image hashes.

The full suite used isolated app state and a temporary offline package-build cache. No real provider request, personal resume import or job application was used for verification. Component test counts overlap; use the full-suite result above as the checkpoint count.

## Remaining tasks and checkpoints

1. Re-review the T06 restored-image fix in `bc2eba6`.
2. Review T07 and T10 before client activation.
3. Complete T08. Keep the existing library canonical. Do not replay old JSONL over reconciled or deleted rows. Recover each legacy run into one linked new run with fresh approvals. Add verified re-export from the canonical PDF.
4. Complete T09A. Connect the API and CLI to the shared services. Route every configured model call through the durable retry owner, including import parsing. Add real readiness checks and read-only content preview.
5. Complete T09B. Add source-versus-draft review, unselected edit proposals, complete content confirmation, exact PDF approval and saved non-secret form drafts.
6. Complete T11. Run a real browser-to-backend journey, all required browser checks, Python 3.12/3.13 checks, Windows lock/path checks and the complete C1 acceptance matrix.
7. Start R2 only after C1 passes.

## Current constraint

The app usage limit interrupted the implementation and review workers. Their work is saved. Independent reviews and client activation remain pending. No new approval bypass was added to work around that limit.

The implementation ledger, task briefs, reports, test logs, real PDF fixture and saved T08 regression patch are in the local ignored workspace:

`.superpowers/sdd/2026-11-12-resume-agent-reliability-and-search/`

T08's unfinished test changes are saved as `task08-library-red-tests.patch`; they are not part of the passing checkpoint. No T08 production code was lost or claimed complete.

All implementation commits are local. Nothing was pushed, published or deployed. The pre-existing `.egm/` files were left untouched.

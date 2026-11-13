# Pending work against the plan and EGM review

Checked 14 November 2026 against the original consolidated EGM report, implementation plan, specification, execution supplements and recorded implementation evidence.

**Feature code, document reconciliation and both live fixes are complete locally. A fresh live-model reviewed export passed. Final external acceptance is not complete.** The original plan now distinguishes completed work from its remaining external checks. The historical EGM report remains unchanged; this is not a new formal EGM certificate.

## Remaining acceptance work

| Work | Owner or dependency | Completion checkpoint |
| --- | --- | --- |
| Validate Claude Code for T21 | Owner restores host authentication; then run its recorded smoke | Named host version completes the required reviewed handoff. Keep Claude unsupported until then. |
| Run Linux and native Windows certification | Remote jobs against the exact candidate | Save successful platform results. Do not infer them from macOS tests. |
| Run five volunteer pilots for T22 | Owner arranges voluntary sessions | Four of five reach a reviewed PDF without developer help. No artifact identity mismatch. Record timing, factual review and recovery. |
| Close C4 | All required evidence above | Record actual results and exclusions. Keep 3.3.0 a candidate while required evidence is absent. |
| Push, tag and publish | Separate owner authorization after acceptance | Review the exact candidate, artifact hashes and publication checklist first. These external actions have not occurred. |

## Original EGM action dispositions

This is a traceability audit, not a new five-stage EGM review. “Implemented” refers to the recorded code and tests. It does not silently amend the original design document.

| Action | Current disposition | What remains |
| --- | --- | --- |
| A01 — Alternatives and trade-offs | Documented in the main design and execution supplements, including later domain/host choices. | No known implementation work pending. |
| A02 — Immutable memory inputs | Implemented with fixed memory snapshots/hashes and the career-domain contract. | No known feature work pending from this action. |
| A03 — Requirements and AND/OR groups | Implemented with normalized groups, deduplication and exact scoring tests. | No known feature work pending. |
| A04 — Response classification | Implemented with explicit response categories. | Original wording now matches the explicit categories. |
| A05 — Exact file boundaries | Master-plan inventories now name exact current source, test, fixture, router, skill and workflow paths. Paths were checked. | No known implementation work pending. |
| A06 — Storage and action transactions | Implemented in migrations, shared lifecycle, replay and release transactions. | See the R1 SQL contract, migrations and shared lifecycle tests. |
| A07 — Export ownership recovery | Implemented; final review found and fixed an additional public-Continue crash window. | No known code defect remains from the finding. Retain the crash-test evidence. |
| A08 — Content versus layout identity | Resolved in the R1 supplement and implemented with separate content/render/PDF hashes. | Original manifest wording now distinguishes all three identities. |
| A09 — Malformed discovery completeness | Implemented conservatively. Partial/failed data cannot establish removal. | No known feature work pending. |
| A10 — One retry budget | Implemented with durable consumed attempts and one model retry owner. | No known feature work pending. |
| A11 — Executable acceptance setup | Local matrix, actual browser/PDF tools, package tests and CI setup exist. | Complete remote platform execution and record its evidence. |
| A12 — Activation boundaries | Defined in the R1 contract; integration completed before later local behavior gates. | Master-plan status now reflects local implementation and open C4. |
| A13 — Rejected-memory wording | Code preserves the rejection audit and leaves active data unchanged. | Plan wording now preserves the rejection audit explicitly. |
| A14 — Software release versus PDF export | Both documents now define the terms separately. Code identifiers remain exact. | No known implementation work pending. |
| A15 — Markdown union pipe | Escaped in the original methods table. | No known work pending. |
| A16 — Identity caveat | Removed from the original specification. Explicit human review remains required. | No known work pending. |
| A17 — Independent checkboxes | Task checkboxes now reflect local completion. Reviewed combined build/verification actions were split. Claude, pilot, platform and C4 actions remain unchecked. | Complete the unchecked external acceptance actions. |
| A18 — Named journey/PDF matrix | Complete: 30 executed named journeys and ten visually inspected PDFs. | Journey and PDF records are linked below and from R4. |
| A19 — Legacy JSONL precedence | Implemented with insert-only migration/precedence and restart tests. | No known feature work pending. |
| A20 — Complete graph and dispatch | Runtime handlers, typed actions and restart/parity checks are implemented. | See the public [dispatch inventory](runtime-dispatch-2026-11-14.md). |
| A21 — Successful compiler logs | Implemented and checked through overflow/layout fixtures. | No known feature work pending. |
| A22 — Pre-import isolation | Implemented for tests, subprocesses and browser servers. | No known feature work pending. |
| A23 — Real browser/backend evidence | Complete: actual API, socket, SQLite, compiler and export journeys; external model/feed boundaries are controlled. | No known feature work pending. |

The original design now links all execution supplements. The added alternatives and dispatch descriptions document implemented decisions. They do not introduce new runtime behavior. Formal five-stage EGM re-review and certified ASD-STE100 dictionary checking have not been performed. Neither is substituted by this status audit.

## Completed local evidence

The initial live failures are now [fixed and verified](live-fixes-2026-11-14.md). The new key works, evaluation completes with exact source references, and a fresh actual browser journey released the reviewed PDF. External gates remain open.

- Complete runtime matrix: 943 passed, zero failures and zero skips at `362a3b5`.
- Python 3.13: 878 passed; 65 browser/PDF checks explicitly disabled and covered in the flagged Python 3.12 run.
- Frontend: 15 tests and the production build passed.
- All three Important final branch-review defects were fixed and reproduced by regression tests.
- Ten fictional PDFs and all eleven page images were inspected. Known presentation limits remain recorded.
- The final package excludes local frontend dependencies. Its strengthened packaging test failed before the fix and passed afterward. All five package tests passed. Six retained-artifact checks passed.
- Candidate wheel and source archive exist locally. Their exact source revision and hashes are in [the artifact manifest](candidate-artifacts-2026-11-14.json).

See the [R4 evidence record](../superpowers/plans/2026-11-13-r4-acceptance.md), [final review](final-branch-review-2026-11-14.md), [journeys](synthetic-journeys-2026-11-13.md), [PDF review](pdf-review-2026-11-13.md) and [pilot checklist](volunteer-pilots.md).

## Limits rather than unfinished roadmap features

Contact-label clarity, paragraph breaks and retained approved duplicate wording are known presentation limits. V2 history deletion awaits a separate retention design. Legacy downloads remain labelled unverified.

Auto-applications, messages, OCR, DOCX import, scheduled discovery, hosted accounts and unrestricted scraping were excluded from this roadmap. They are not pending T01–T22 tasks. The evidence does not measure adoption or prove better hiring outcomes.

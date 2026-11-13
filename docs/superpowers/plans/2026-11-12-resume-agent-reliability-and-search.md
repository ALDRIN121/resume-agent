# Resume Agent Reliability and Job Search Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` during authorized implementation. Complete one task and its review before dependent work.

**Goal:** Release reviewed, traceable resumes. Then add reusable corrections, role decisions, application tracking, bounded discovery, and an agent interface.

**Architecture:** Retain the existing app and LangGraph engine. Use fixed input snapshots, typed edits, deterministic rendering, durable reviews, and isolated artifacts. Add search features through shared services.

**Tech Stack:** Python 3.12–3.13, Pydantic, LangGraph, SQLite, FastAPI, Typer, React, Jinja2, Tectonic, Poppler, pytest, and Playwright.

**Spec:** [Reliable Resume and Job Search Design](/Users/aldrinjoseph/Developer/Resume-agent/resume-agent/docs/superpowers/specs/2026-11-12-resume-agent-reliability-and-search-design.md).

**Starting revision:** `5c1938f670ce5fc1322d3b26bcac5cb85e377743`.

**Repository root:** `/Users/aldrinjoseph/Developer/Resume-agent/resume-agent`. Paths in task inventories are relative to this root.

**Status:** Updated 14 November 2026. T01–T21 feature code is present on `codex/resume-agent-r1`. Controlled-response C1–C3 checks passed. The live retest found T06/T13 issues requiring repair. C4 remains open.

**Current checkpoint:** [Implementation status](2026-11-13-r1-implementation-status.md) and [R4 acceptance](2026-11-13-r4-acceptance.md). PDF extraction and live evaluation repairs, five pilots, remote platform certification and authenticated Claude validation remain open. All work is local and unpublished.

**Final transitions:** [Runtime transition and dispatch inventory](../../validation/runtime-dispatch-2026-11-14.md).

**R1 decisions:** [Execution contract](/Users/aldrinjoseph/Developer/Resume-agent/resume-agent/docs/superpowers/specs/2026-11-12-r1-execution-contract.md). This supplement resolves core review findings before activation.

| Term | Meaning |
|---|---|
| Profile | Accepted candidate facts and saved work preferences |
| Run | One saved resume-generation workflow |
| Artifact | A file owned by one run |
| Content snapshot | The fixed wording, display order, and omissions approved for a run |
| Software release | A version of the application approved for distribution |
| Reviewed PDF export | Final copy of the approved PDF bytes; code retains identifiers such as `release_records` |
| Saved state | The LangGraph checkpoint used to resume work |
| Gate | A pass/fail release checkpoint, named C1 through C4 |

## Global Constraints

- Preserve the current web app and interactive CLI.
- Preserve local-first storage and the local Ollama path.
- Keep `base_resume.yaml` canonical. Do not remove schema validation.
- Apply only explicit approved content changes. Require final PDF approval.
- Set checkpoint schema to v2, REST contract to 2, and JSON envelope to 1.
- Use `filelock>=3.32.7,<4`. The current lockfile already contains version 3.32.7.
- Permit PDF and TEX imports up to 10 MiB and 48,000 extracted characters. Reject larger inputs without truncation.
- Use two supported layouts. Default to two pages. Permit explicit page limits from one through five.
- Keep personal data and diagnostic logs local. Do not log credentials or full provider responses.
- Do not submit applications, send messages, or add authenticated scraping.
- Use three discovery providers only: Greenhouse, Lever, and Ashby.
- Use active voice and one action per checklist step. Keep technical identifiers exact.

## Review Focus

1. Identical bullets in different roles must remain separate targets. Test this in T05.
2. A crash between approval and export must not create a false completed run. Test every release boundary in T07 and T08.
3. CLI and web actions must not resume one run concurrently. Test cross-process ownership and cancellation in T02 and T08.
4. A partial scan must not mark jobs removed. Test bounded and failed refreshes in T17.
5. An external-agent response must not act as human approval or make a backend model call. Test this in T20.

## 1. Release Order and Checkpoints

| Release | Tasks | Depends on | Release checkpoint |
|---|---|---|---|
| **R1 — 3.0.0: Reliable engine** | T01–T11 | Current revision | C1: correct content, correct bytes, reviewed export, complete input handling, and durable recovery |
| **R2 — 3.1.0: Memory and decisions** | T12–T14 | C1 | C2: accepted corrections persist; evidence fit remains auditable and advisory |
| **R3 — 3.2.0: Search operations** | T15–T18 | C2 | C3: explicit application events and complete/partial discovery remain distinct |
| **R4 — 3.3.0: Agent access** | T19–T22 | C3 | C4: packaged app and tested agent hosts complete the same reviewed workflow |

Do not start a later release before the earlier checkpoint passes. Keep every task independently reviewable.

Use this task procedure: add meaningful tests, observe their failure, implement the minimum change, verify, and review.
Commit each accepted implementation task separately. Do not publish releases from this planning task.

## 2. R1 — Reliable Resume Engine

### T01 — Establish the baseline and regression fixtures

**Depends on:** none. **Owner:** core implementer. **Review:** independent reviewer.

**Files:** `src/resume_agent/config.py`, `tests/conftest.py`, `tests/test_state_isolation.py`, `tests/fixtures/reliability/profile.json`, `tests/fixtures/reliability/job.txt`, `tests/fixtures/reliability/legacy_history.jsonl`.

**Produces:** synthetic source profiles, long inputs, overlapping-run markers, legacy checkpoints, and baseline verification records.

- [x] Capture the starting revision and current required-check results in isolated test state.
- [x] Add fixtures for duplicate bullets, reversed metrics, role-scope changes, long inputs, and partial PDF extraction.
- [x] Add legacy fixtures for paused, complete, missing-artifact, malformed, and cancelled runs.
- [x] Record the known failure mechanisms without changing their acceptance rules.
- [x] Review fixture provenance and confirm that fixtures contain no personal resumes or credentials.

**Done when:** each known defect has a reproducible synthetic input and an assigned owner task.
Do not commit an unexplained failing test suite. Add each failing regression in its owner task.

### T02 — Define the v2 run contract and shared lifecycle

**Depends on:** T01.

**Files:** `src/resume_agent/contracts.py`, `src/resume_agent/run_store.py`, `src/resume_agent/run_service.py`, `src/resume_agent/operation_service.py`, `src/resume_agent/checkpoint.py`, `src/resume_agent/migrations.py`, `tests/test_run_service.py`, `tests/test_operation_service.py`, `tests/test_migrations.py`.

**Interfaces:** define `RunRequest`, `RunView`, `ResumeAction`, `PdfReview`, and the `RunService` methods in the spec.
Store new typed checkpoint values as validated JSON dictionaries or explicitly registered schema types.
Add the shared `OperationService` create/get/drive contract for import drafts. Use it for evaluation when R2 starts.

- [x] Add `test_run_create_is_durable`, `test_run_lock_cross_process`, and `test_action_id_replay`.
- [x] Run `uv run pytest tests/test_run_service.py -q` and confirm the new tests fail.
- [x] Implement ordered SQLite migrations, state v2, fixed run inputs, and process-independent run locks.
- [x] Build the shared create/drive/get lifecycle behind a private interface. Activate both clients together after T09.
- [x] Verify action replay, stale-action rejection, explicit cancellation requests, and rollback after migration failure.

**Done when:** two processes cannot drive the same run, and the same action cannot execute twice.
Creation must survive restart before the first model call.

### T03 — Isolate run artifacts and make export atomic

**Depends on:** T02.

**Files:** `src/resume_agent/artifacts.py`, `src/resume_agent/tools/fs.py`, `tests/test_artifact_isolation.py`, `tests/test_fs.py`.

**Interfaces:** `RunArtifacts.create(artifact_id)`, `attempt(number)`, `hash_file(path)`, `prepare_export(pdf_hash, destination)`, and `commit_export(plan)`.
All paths derive from a generated UUID and validated attempt number.
`prepare_export` returns temporary path, reserved destination, expected hash, and reservation ownership.
Only the release service calls `commit_export`, inside the final release transaction.

- [x] Add interleaved and concurrent artifact tests for different companies and the same company.
- [x] Run `uv run pytest tests/test_artifact_isolation.py -q` and confirm the shared-file regression fails.
- [x] Replace shared working paths with run-owned attempt paths for PDFs, images, and logs.
- [x] Implement hash verification and atomic export through a temporary sibling file.
- [x] Verify that failed copies expose no completed artifact and remove unused destination reservations.

**Done when:** compile A, compile B, render A, save A, and save B retain the correct hashes and contents.
No node may read the old global `_working/resume.pdf` for a v2 run.

### T04 — Import complete supported input through a reviewed draft

**Depends on:** T02.

**Files:** `src/resume_agent/imports.py`, `src/resume_agent/profile_store.py`, `src/resume_agent/api/routers/resume.py`, `tests/test_import_coverage.py`, `tests/test_profile_store.py`.

**Interfaces:** `ProfileStore.load_snapshot()` and `ProfileStore.save(expected_revision, profile, source_metadata)`.
Use a profile lock and atomic YAML replacement. Persist import drafts separately from the accepted profile.

- [x] Add tests for a marker after character 12,000, a restriction after character 8,000, and complete stored JD text.
- [x] Add boundary tests for 48,000 versus 48,001 characters and 10 MiB versus an oversized upload.
- [x] Replace slicing with explicit input validation and full supported-text delivery.
- [x] Add per-page PDF extraction warnings and source-versus-draft review before profile save.
- [x] Verify stale-save conflicts and preservation of the old profile after invalid, incomplete, or failed imports.

**Run:** `uv run pytest tests/test_import_coverage.py tests/test_resume_upload.py tests/test_resume_context.py -q`.

**Done when:** supported input is retained in full, or import stops with a clear limit error before changing the profile.
Source delivery must not be described as proof of complete factual extraction.

### T05 — Apply explicit structured edits and review the display projection

**Depends on:** T02 and T04.

**Files:** `src/resume_agent/content_review.py`, `src/resume_agent/agents/resume_generator.py`, `src/resume_agent/contracts.py`, `tests/test_content_review.py`, `tests/test_resume_fidelity.py`.

**Interfaces:** `EditProposal`, `PatchResult`, `RenderManifest`, and `build_content_preview(snapshot, selected_ids)`.
Consume a fixed profile revision and answer references. Produce an immutable approved-content hash.

- [x] Add tests for reject-all, duplicate bullets, stale hashes, unknown IDs, unsupported paths, and overlapping edits.
- [x] Add tests for ordered list appends and explicit display omissions.
- [x] Stop whole-profile rewriting during question enrichment. Generate final proposals after answers arrive.
- [x] Validate all selected edits against the fixed source before applying any change.
- [x] Add the content-preview endpoint and require explicit confirmation of its content hash.

**Run:** `uv run pytest tests/test_content_review.py tests/test_resume_fidelity.py -q`.

**Done when:** every selected edit has a result, and no rejected or unmatched edit changes the content.
Display ordering and omissions must appear in the approved manifest.

### T06 — Render approved content without hidden model writing

**Depends on:** T03 and T05.

**Files:** `src/resume_agent/approved_render.py`, `src/resume_agent/templates/approved.tex.jinja`, `src/resume_agent/tools/tectonic_compile.py`, `tests/test_approved_render.py`, `tests/test_template_render.py`.

**Consumes:** approved `RenderManifest` and content snapshot.
**Produces:** deterministic LaTeX and one of the two supported layout candidates.

- [x] Add tests that inject scope changes and reversed metrics into mocked writer or repair responses.
- [x] Remove free-text LaTeX polishing and free-text repair from the execution path.
- [x] Move normalization and display decisions before content approval.
- [x] Implement `standard` then `compact` layout selection under the page and overflow rules.
- [x] Force every retry path and verify that the approved content hash remains unchanged.

**Run:** `uv run pytest tests/test_approved_render.py tests/test_template_render.py tests/test_graph_flow.py -q`.

- [ ] Add a real-compiler regression for the live `Tools` → `T ools` extraction case.
- [ ] Correct font setup while retaining the exact content guard.

**Done when:** lint, HR review, vision review, retries, and layout changes cannot rewrite approved wording.
A layout failure must request a new run or content revision instead of dropping text.

### T07 — Verify and approve the exact PDF before release

**Depends on:** T03 and T06.

**Files:** `src/resume_agent/pdf_content_check.py`, `src/resume_agent/release_service.py`, `src/resume_agent/api/routers/runs.py`, `tests/test_pdf_content_check.py`, `tests/test_release_service.py`, `tests/test_final_recovery.py`.

**Interfaces:** `verify_pdf_content(manifest, pdf_path)`, `PdfReview`, and the typed `review_pdf` action.
Use `release_records` states and release ordering from the spec.

- [x] Add tests for missing words, changed signs or units, reversed values, stale review IDs, and replaced PDF bytes.
- [x] Add crash tests before copy, after rename and after commit.
- [x] Add cancellation tests after copy but before export commit.
- [x] Add expected-token verification, frozen preview delivery, and explicit PDF approval.
- [x] Commit release state and run completion only after verified export and a cancellation check.
- [x] Verify replay of the accepted action returns the same release without recompilation or duplicate export.

**Run:** `uv run pytest tests/test_pdf_content_check.py tests/test_release_service.py -q`.

**Done when:** completion and final download refer to the exact approved PDF hash.
No existing token, numeric, or structural guard may be advertised as proof of factual truth.

### T08 — Recover paused, interrupted, and legacy runs safely

**Depends on:** T02, T05, and T07.

**Files:** `src/resume_agent/recovery.py`, `src/resume_agent/library.py`, `src/resume_agent/run_service.py`, `tests/test_run_recovery.py`, `tests/test_library.py`, `tests/test_final_recovery.py`.

**Interfaces:** `recover_legacy(run_id)` and startup reconciliation against checkpoints, release records, and cancellation commands.

- [x] Add restart tests at question, content-review, model-call, compile, and PDF-review boundaries.
- [x] Rebuild the current pending request from the latest checkpoint without automatic execution.
- [x] Implement idempotent v1-to-v2 recovery through a linked new run.
- [x] Add explicit missing-artifact state and reviewed historical relinking.
- [x] Verify release reconciliation, pending cancellation, CLI/web contention, and missing required legacy source data.

**Run:** `uv run pytest tests/test_run_recovery.py tests/test_library.py tests/test_websocket.py -q`.

**Done when:** a saved checkpoint cannot disappear from both interfaces, and old approval state cannot approve new content.
Original checkpoints and historical files must remain unchanged.

### T09 — Make readiness, review, and interrupted input clear

**Depends on:** T04–T08.

**Files:** `src/resume_agent/runtime.py`, `src/resume_agent/workflow.py`, `src/resume_agent/api/v2_manager.py`, `src/resume_agent/api/routers/readiness.py`, `src/resume_agent/api/streaming.py`, `src/resume_agent/cli.py`, `Frontend/src/app.jsx`, `Frontend/src/live-run.jsx`, `Frontend/src/resume-upload.jsx`, `Frontend/src/draft-store.js`, `Frontend/src/api/client.js`, `tests/test_v2_api.py`, `tests/test_ui_flow.py`, `tests/test_import_recovery_ui.py`.

**Interfaces:** `GET /api/readiness`, current pending-action data, content preview, and final PDF review.

- [x] Add browser tests for missing profile, missing tools, missing provider setup, and import-draft acceptance.
- [x] Replace hardcoded readiness with server results. Explain the next required action.
- [x] Add before/after content review, default-unselected edits, declared omissions, and exact PDF review.
- [x] Preserve non-secret form drafts in IndexedDB, keyed by form, run, review ID, and profile revision.
- [x] Separate loading, empty, failed, interrupted, missing-artifact, and complete states in both interfaces.

**Run:** `npm test`; then run `tests/test_ui_flow.py` against a started preview server.

**Done when:** navigation or restart does not silently discard draft input, and status labels reflect actual checks.
Restored drafts with a stale review or profile revision must require reconciliation.

### T10 — Classify provider failures and bound retries

**Depends on:** T02 and T06.

**Files:** `src/resume_agent/model_tasks.py`, `src/resume_agent/provider_errors.py`, `src/resume_agent/llm.py`, `tests/test_model_tasks.py`, `tests/test_provider_errors.py`.

**Produces:** stable error codes for authentication, unavailable model, rate limit, transport, invalid output, and truncation.

- [x] Add fixture tests for tool output, JSON output, arbitrary skill categories, truncation, and malformed responses.
- [x] Set one retry owner per model task. Disable duplicate node-level retry handling.
- [x] Permit at most two model attempts for retryable failures. Respect bounded provider backoff.
- [x] Stop immediately on missing credentials or unavailable models. Keep input and prior approved content intact.
- [x] Record the failing stage, model, attempt count, and sanitized error code in durable run metadata.

**Run:** `uv run pytest tests/test_llm.py tests/test_resume_structured_output.py tests/test_provider_errors.py -q`.

**Done when:** failures are actionable and countable, with no partial-JSON repair or nested retry multiplication.

### T11 — Enforce the R1 build and release gate

**Depends on:** T01–T10.

**Files:** `.github/workflows/ci.yml`, `pyproject.toml`, `tests/test_packaged_ui.py`, `tests/test_platform_runtime.py`, `tests/test_reliability_journey.py`, `tests/reliability_server.py`, `docs/superpowers/plans/2026-11-13-r1-acceptance.md`.

- [x] Run Python lint and tests on Python 3.12 and 3.13.
- [x] Add frontend tests.
- [x] Build the frontend.
- [x] Add a browser job with a started backend and preview server.
- [x] Add real Tectonic/Poppler checks.
- [x] Configure native Windows lock/path coverage. Execution remains an external gate.
- [x] Build the wheel.
- [x] Build the source archive.
- [x] Test the installed wheel with bundled UI assets.
- [x] Complete the local C1 evidence table.
- [x] Prepare version 3.0.0 release notes.

**Checkpoint C1 — Pass only when all conditions hold:**

- Ten interleaved same-company runs retain their own artifacts and hashes.
- Reject-all preserves reviewed wording. Every approved edit has a visible result.
- Replaced PDF bytes and stale approvals block release.
- Supported long input reaches parsing in full. Rejected import preserves the old profile.
- All review pauses survive restart. Legacy recovery does not reuse unsafe approvals.
- Required browser checks execute. No required check is unexpectedly skipped.
- Real fixture PDFs pass text conservation, page limits, and overflow checks.

Stop R2 if C1 fails. Do not replace this gate with a total test count.

## 3. R2 — Reusable Corrections and Role Decisions

### T12 — Retain accepted corrections and preferences

**Depends on:** C1.

**Files:** `src/resume_agent/memory.py`, `src/resume_agent/api/routers/memory.py`, `Frontend/src/career-memory.jsx`, `tests/test_memory.py`, `tests/test_memory_api.py`, `tests/test_memory_ui.py`.

**Interfaces:** `MemoryProposal`, `MemoryRecord`, and `decide_memory(id, decision, expected_revision, action_id)`.

- [x] Add tests for reject, accept-once, stale revision, revoke, supersede, and interrupted fact promotion.
- [x] Implement typed candidate-fact, target-preference, and writing-rule proposals.
- [x] Apply accepted facts through `ProfileStore`. Keep other accepted rules in the memory audit.
- [x] Reconcile interrupted promotions by comparing old, proposed, and current profile hashes.
- [x] Show active memory and its source. Apply it only to future runs and evaluations.

**Run:** `uv run pytest tests/test_memory.py tests/test_profile_store.py -q`.

**Done when:** a rejected correction leaves active profile facts and rules unchanged. Its rejection remains in the audit, and a later run reuses an accepted rule without changing earlier artifacts.

### T13 — Add versioned job snapshots and auditable fit calculations

**Depends on:** T12.

**Files:** `src/resume_agent/career_schemas.py`, `src/resume_agent/job_store.py`, `src/resume_agent/role_evaluation.py`, `src/resume_agent/migrations.py`, `tests/test_job_store.py`, `tests/test_role_evaluation.py`, `tests/test_evaluation_operations.py`.

**Interfaces:** `CareerJob`, `RoleRequirement`, `RequirementFinding`, `RoleEvaluation`, and `score_fit(findings, rubric_version)`.
Store profile/JD hashes and rubric `fit-v1` with every result.

- [x] Add exact arithmetic tests for supported, transferable, contradicted, unknown, and absent criteria.
- [x] Implement the six fixed weights and evidence interval from the spec.
- [x] Implement explicit eligibility checks without inferring authorization from personal identifiers.
- [x] Validate JD spans and candidate source references. Reject unsupported evidence references.
- [x] Mark evaluations stale after input changes.
- [x] Return no score for zero usable criteria.

- [x] Extend `OperationService` for durable evaluations.
- [x] Verify restart during model work and after result persistence.

**Run:** `uv run pytest tests/test_role_evaluation.py tests/test_job_store.py -q`.

- [ ] Diagnose and resolve the live configured-model `truncated_output` evaluation failure.

**Done when:** two equally weighted criteria yield `[50,100]` at 50% coverage for supported plus unknown.
Supported plus transferable must yield `[75,75]` at 100% coverage.

### T14 — Add role decisions before tailoring

**Depends on:** T13.

**Files:** `src/resume_agent/api/routers/jobs.py`, `src/resume_agent/cli.py`, `Frontend/src/career-jobs.jsx`, `tests/test_career_ui.py`, `docs/superpowers/plans/2026-11-13-r2-acceptance.md`.

**Interfaces:** the job and evaluation endpoints in the spec. Preserve generation from pasted text, files, and URLs.

- [x] Add API/browser tests for prioritize, review, confirmed eligibility conflict, stale evaluation, and user override.
- [x] Show evidence coverage, unknowns, requirement sources, and the fixed recommendation rules.
- [x] Offer evaluation before generation. Permit generation after an explicit recommendation override.
- [x] Keep fit scores separate from writing/formatting checks and hiring probabilities.
- [x] Preserve the chosen JD snapshot and evaluation reference when generation starts.

- [x] Prepare version 3.1.0 metadata, release notes, and installed-candidate evidence before recording C2.

**Checkpoint C2:** accepted memory persists, evidence references resolve, score arithmetic is exact, and unknown evidence remains visible.
No score may silently exclude a candidate or imply an interview probability.

## 4. R3 — Applications, Outcomes, and Bounded Discovery

### T15 — Record explicit application events and sent artifacts

**Depends on:** C2.

**Files:** `src/resume_agent/applications.py`, `src/resume_agent/api/routers/applications.py`, `src/resume_agent/migrations.py`, `tests/test_applications.py`.

**Interfaces:** `Application`, `ApplicationEvent`, and the application endpoints in the spec.

- [x] Add tests for explicit submission, direct forward changes, correction/reopen, idempotency, and unknown dates.
- [x] Implement the separate application stages and append-only event corrections.
- [x] Record the selected sent-artifact hash, or explicitly record an unknown artifact.
- [x] Prevent later generations or document deletion from changing application history.
- [x] Update company cleanup so retained jobs and applications are not deleted or orphaned.

**Run:** `uv run pytest tests/test_applications.py tests/test_library.py -q`.

**Done when:** a generated resume changes zero submission counts until a user records submission.

### T16 — Show outcome evidence and accurate dashboard measures

**Depends on:** T15.

**Files:** `src/resume_agent/outcomes.py`, `src/resume_agent/api/routers/outcomes.py`, `Frontend/src/career-outcomes.jsx`, `tests/test_outcomes.py`, `tests/test_outcomes_ui.py`.

**Interfaces:** `OutcomeBandReport` with positive, negative, pending, withdrawn, unknown-score, and excluded counts.

- [x] Add tests for score-at-submission snapshots, historical positive responses, pending exclusions, and small samples.
- [x] Implement the three score bands and resolved-outcome rules from the spec.
- [x] Suppress rates below ten resolved records per band. Show counts and exclusions.
- [x] Rename compilation success to generation health. Derive application counts only from explicit events.
- [x] Add local export of the report without automatic rubric changes or telemetry.

**Run:** `uv run pytest tests/test_outcomes.py tests/test_applications.py -q`.

**Done when:** later rejection does not erase a previously recorded interview response, and pending applications do not become negative outcomes.

### T17 — Add three bounded public job-board adapters

**Depends on:** T13. Start only after C2 passes.

**Files:** `src/resume_agent/discovery/schemas.py`, `src/resume_agent/discovery/providers.py`, `src/resume_agent/discovery/http.py`, `src/resume_agent/discovery/journal.py`, `src/resume_agent/discovery/service.py`, `tests/test_discovery.py`, `tests/test_discovery_http.py`, `tests/test_discovery_service.py`.

**Interfaces:** `DiscoverySource`, `DiscoverySyncResult`, and a provider protocol `fetch_board(source) -> BoardResult`.

- [x] Add provider fixtures for pagination, duplicate IDs, malformed records, limits, HTTP 429, and transient failure.
- [x] Implement public Greenhouse, Lever, and Ashby adapters from their official contracts.
- [x] Enforce the board, job, body-size, concurrency, timeout, redirect, and retry limits from the spec.
- [x] Store stable source keys and immutable JD snapshots. Preserve freshness and partial-result warnings.
- [x] Verify that only a complete successful refresh can mark a prior posting removed.

**Run:** `uv run pytest tests/test_discovery.py tests/test_security.py -q`.

**Done when:** source failure preserves earlier results, and discovery never makes model calls or application-submission requests.

### T18 — Connect discovery to review, evaluation, and generation

**Depends on:** T14, T16, and T17.

**Files:** `src/resume_agent/api/routers/discovery.py`, `src/resume_agent/cli.py`, `Frontend/src/career-discovery.jsx`, `Frontend/src/career-applications.jsx`, `tests/test_search_operations_ui.py`, `tests/test_search_operations_cli.py`, `docs/superpowers/plans/2026-11-13-r3-acceptance.md`.

- [x] Add browser tests for source setup, manual refresh, partial results, stale data, selection, and evaluation handoff.
- [x] Show source, freshness, posting state, and scan limits on each result set.
- [x] Let the user select jobs for evaluation. Do not evaluate all fetched jobs automatically.
- [x] Preserve the selected job identity through evaluation, generation, and application linking.
- [x] Verify empty, failed, partial, and complete scans remain distinct across restart.

- [x] Prepare version 3.2.0 metadata, release notes, and installed-candidate evidence before recording C3.

**Checkpoint C3:** completed PDFs, submitted applications, responses, and discovery results have separate state and accurate counts.
No failed or partial sync may erase jobs or assert that they closed.

## 5. R4 — Agent Access, Distribution, and Final Validation

### T19 — Expose the shared workflow through JSON commands

**Depends on:** C3.

**Files:** `src/resume_agent/agent_cli.py`, `src/resume_agent/agent_schemas.py`, `tests/test_cli_json.py`, `tests/test_interface_parity.py`, `docs/agent-json.md`.

**Interfaces:** commands, resource identifiers, envelope fields, and exit codes from the spec.

- [x] Add closed-stdin tests for start, inspect, respond, cancel, export, import, evaluate, discover, memory, and application.
- [x] Implement exactly one JSON response on stdout. Keep progress on stderr.
- [x] Await command execution until a durable pause or terminal result.
- [x] Validate action files through the same typed actions as the API.
- [x] Compare CLI/API state, approval defaults, and artifact hashes using interface-parity tests.

**Run:** `uv run pytest tests/test_cli_json.py tests/test_interface_parity.py -q`.

**Done when:** agent commands cannot hang at an interactive prompt or bypass a stale review check.

### T20 — Reuse a host agent through a durable model boundary

**Depends on:** T19.

**Files:** `src/resume_agent/external_model.py`, `src/resume_agent/model_tasks.py`, `src/resume_agent/operation_service.py`, `src/resume_agent/api/routers/model_tasks.py`, `tests/test_external_agent.py`.

**Interfaces:** `ModelTask`, `OperationService`, `configured_provider`, and `external_agent` execution modes.
Use the unique owner/task/input-hash key from the spec to avoid duplicate requests on graph replay.

- [x] Add tests for external import, JD extraction, proposal generation, evaluation, restart, stale responses, and two-attempt limits.
- [x] Persist external model requests and return them as `next_action` without calling a backend model.
- [x] Validate host results through existing schemas and source-reference checks.
- [x] Keep model responses separate from content and PDF approvals.
- [x] Disable optional external-mode HR/vision calls.
- [x] Patch the backend model factory to raise in external-mode tests.
- [x] Complete a fixture journey without triggering that factory.

**Run:** `uv run pytest tests/test_external_agent.py tests/test_model_tasks.py tests/test_cli_json.py -q`.

**Done when:** external mode can reach reviewed export without a backend API key, while configured-provider mode remains compatible.

### T21 — Add the skill entry point and prepare distribution

**Depends on:** T20.

**Files:** `src/resume_agent/skill_distribution.py`, `skills/resume-agent/SKILL.md`, `skills/resume-agent/references/protocol.md`, `skills/resume-agent/agents/openai.yaml`, `.github/workflows/publish-candidate.yml`, `tests/test_skill_distribution.py`, `docs/agent-hosts.md`, `docs/publication-checklist.md`.

- [x] Write the skill around the JSON contract and explicit user review pauses.
- [x] Add protocol tests for action-file use, shell metacharacters, stale reviews, and hostile instructions inside job text.
- [x] Validate the installed skill and named handoff in Codex CLI 0.153.4.
- [ ] Validate the installed skill and named handoff in authenticated Claude Code.
- [x] Document host-model versus backend-provider billing and prerequisites without universal free-use claims.
- [x] Prepare the wheel, source archive, PyPI metadata, short demo, issue templates, and release notes.

**Done when:** each claimed host has a named tested version and a recorded journey.
An unavailable host is unsupported in release notes until its required smoke check passes.
Prepared publication files do not authorize registry publication or GitHub settings changes.

### T22 — Run the complete acceptance matrix and prepare release

**Depends on:** T01–T21.

**Files:** `docs/superpowers/plans/2026-11-13-r4-acceptance.md`, `docs/validation/synthetic-journeys-2026-11-13.md`, `docs/validation/pdf-review-2026-11-13.md`, `docs/validation/volunteer-pilots.md`, `docs/validation/candidate-artifacts-2026-11-14.json`, `docs/candidate-rollback.md`.

- [x] Run all local required Python, frontend, browser, compiler, migration, package, and interface-parity checks. Remote platform certification remains open.
- [x] Run at least 20 synthetic journeys spanning success, rejection, interruption, provider failure, migration, and partial discovery. Final record: 30 journeys.
- [x] Review ten representative PDFs for factual correspondence and visual defects.
- [ ] Record five owner-arranged volunteer pilots.
- [ ] Measure pilot setup, first reviewed PDF, interruptions and factual-review results.
- [x] Record revision, environment, models, input set, results, exclusions, known limits, and rollback procedure.
- [x] Prepare version 3.3.0 release artifacts and a concrete external publication checklist for separate approval.

- [ ] Record the configured Linux and native Windows certification results.
- [ ] Record the authenticated Claude smoke result before claiming support.
- [ ] Repeat the complete live-model reviewed-export journey after the local fixes.
- [ ] Close C4 only after its required evidence passes.

**Checkpoint C4 — Pass only when all conditions hold:**

- No released PDF differs from its approved content or approved byte hash.
- No approved edit disappears without a result. No rejected edit changes the output.
- Every durable pause survives restart in the tested interfaces.
- Legacy files remain accessible or visibly missing. Migration invents no approval or submission history.
- Memory, role evaluation, tracking, and discovery pass C2 and C3.
- JSON commands preserve the same contracts as the web app.
- External-agent mode makes zero configured-provider model calls in the tested journey.
- Both claimed host integrations pass their recorded smoke checks.
- Four of five pilot participants reach a reviewed PDF without developer intervention. No pilot has an artifact identity mismatch.
- Required checks contain zero unexplained failures or skips.

If C4 fails, keep the build as a candidate. Do not describe it as released or production-verified.

Local closure and the remaining external gates are recorded in the [R4 acceptance record](2026-11-13-r4-acceptance.md), updated 14 November 2026. T22 and C4 remain open for the new local live-test issues and required pilot, platform and authenticated-host evidence. See the [live retest](../../validation/live-provider-retest-2026-11-14.md).

## 6. Implementation Control and Evidence

### Task order

Follow the listed dependency order. Within R1, T03 and T04 can proceed in parallel after T02.
T10 can proceed after T06 while T08 and T09 finish. Coordinate shared graph and schema changes through one owner.
Within R3, adapter work can proceed alongside application work after the shared job contract is stable.

Use one implementer and one independent reviewer per task. Give each worker only its task, spec, and required interfaces.
Use a suitable isolated checkout during implementation. Do not modify unrelated files or personal application state.

### Required task evidence

For each task, retain:

- The task ID and starting revision.
- The new test names and their initial failure.
- The final verification commands and actual results.
- The interface changes and migration effects.
- The review result and remaining limits.

Run routine tests with model/API fixtures. Keep live provider checks separate and explicitly enabled.
Use version-labelled pilot results. Do not reuse the historical 17-run sample as the current reliability baseline.

### Rollout and rollback

Back up databases and the canonical profile before each migration. Verify restore using a test copy.
Install each candidate into isolated state before using normal state.
For rollback, stop the service and restore the matching pre-migration backup with the earlier application version.
Retain new run artifacts separately. Do not run an older graph against v2 checkpoints.

### Definition of complete

Each task passes its stated tests and review. Each release passes its checkpoint.
The built package passes the required journey. Documentation matches observed behavior.
No task is complete because its code exists or because another agent reports success.

This plan prepares implementation. It does not implement features, publish a package, or promise a hiring outcome.

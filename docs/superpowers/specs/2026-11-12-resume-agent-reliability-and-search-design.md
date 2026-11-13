# Resume Agent: Reliable Resume and Job Search Design

Date: 12 November 2026. Status: R1 implementation in progress after the user's instruction to start. The C1 release gate is pending.

The [R1 execution contract](2026-11-12-r1-execution-contract.md) resolves the storage, recovery, identity, and activation decisions from the EGM review.

## 1. Purpose and defaults

Build a dependable resume engine. Then add role decisions, application records, job discovery, and an agent skill.

Keep the current web app and interactive CLI. Keep Python, Pydantic, LangGraph, SQLite, FastAPI, Typer, React, and LaTeX.

The user requested a detailed plan after the comparison report. The clarification form returned no answers. Use these defaults:

- Serve individual technical job seekers first.
- Deliver the full roadmap through four separate releases.
- Apply only explicit, approved content changes.
- Require approval of the final PDF before final export.
- Store personal data locally. Keep telemetry off.
- Retain the configured-provider and local Ollama paths.
- Add a separate external-agent mode in the last release.

Do not add auto-application, email sending, hosted accounts, billing, interview simulation, or a new agent framework.
Do not add OCR, DOCX import, unrestricted web scraping, or scheduled discovery in this roadmap.

Source: [comparison report](/Users/aldrinjoseph/Developer/Resume-agent/Career-Ops-vs-Resume-Agent-Report-2026-11-12.md).

## 2. Success criteria

| Release | User result | Required evidence |
|---|---|---|
| R1 — 3.0.0 | Import, review, generate, interrupt, resume, and export a correct run | All core checkpoints pass. No content or artifact identity mismatch occurs. |
| R2 — 3.1.0 | Retain accepted corrections and decide which roles deserve attention | Memory changes require acceptance. Every evaluation cites its inputs. |
| R3 — 3.2.0 | Track explicit applications and find roles on configured public boards | Generated documents never become submitted applications automatically. Partial scans remain visible. |
| R4 — 3.3.0 | Use the same workflow from an agent skill | JSON commands do not prompt. External-agent mode makes no configured-provider model calls. |

These criteria measure software behavior. They do not establish candidate truth, active-user adoption, or hiring probability.

## 3. Core workflow and content contract

Use this sequence:

1. Load the complete job input and a fixed base-profile copy.
2. Show role evaluation when R2 is available.
3. Collect answers as evidence. Do not replace the profile with an LLM response.
4. Generate structured edit proposals against the fixed profile.
5. Show each proposal, its target, and its source references.
6. Apply only the selected proposals.
7. Show the complete display projection and declared omissions.
8. Freeze the approved content snapshot.
9. Render and compile that snapshot.
10. Check the displayed text and page layout.
11. Show the exact preview PDF for final approval.
12. Export the same approved bytes atomically.

### 3.1 Fixed inputs

Keep `base_resume.yaml` as the canonical candidate profile. Keep `UserResume` compatible with existing saved profiles.

Compute the profile revision from canonical JSON. Use sorted keys, UTF-8, fixed separators, and SHA-256.
Copy the profile, complete JD, answers, and source hashes into the run directory. Resume from those copies.

Use a JSON Pointer within a fixed profile revision as a claim reference. Do not add permanent IDs to every bullet.
Store references as `profile_revision + target_path + value_hash`. A changed revision requires new proposals.

Define `SourceRef` with `kind`, `input_hash`, `target_path`, `answer_id`, `start`, `end`, and `quote`.
Permit kinds `profile`, `answer`, and `user_text`. Use only fields relevant to that kind.
Use Unicode character offsets for source spans. Verify quotes against the fixed input before accepting a reference.
Use canonical-JSON SHA-256 for value hashes. Use file-byte SHA-256 for artifact hashes.

### 3.2 Proposed changes

Define `EditProposal` with these fields:

`id`, `operation`, `target_path`, `source_revision`, `before_hash`, `after`, `source_refs`, `rationale`.
Use `after: str | None`. Require text for replacement or append. Require null for a display omission.

- Permit `replace`, `append`, and `omit_from_display` only.
- Permit replacements for the summary, existing bullets, project descriptions, and individual skill strings.
- Permit appends to experience bullets, project bullets, and existing skill categories.
- Use a separate explicit profile edit for identity, employer, title, date, education, or certification changes.
- Require explicit answer or user-text evidence for additions. Do not infer new facts from the JD.
- For append, target the parent list. Do not use an insertion index or `/-`.
- Check every selected proposal against the fixed source before applying any change.
- Reject unknown IDs, stale hashes, unsupported paths, duplicate replacement targets, and invalid field types.
- Permit multiple distinct appends to one list. Apply them in the displayed proposal order after replacements.
- Restrict display omissions to the summary, project descriptions, bullets, and skill strings.
- Reject an omission that overlaps a selected replacement. Preserve other source order. Do not support list deletion.
- Return one `PatchResult` per selected proposal: `applied`, `conflict`, or `invalid`.
- Keep all proposals unselected by default. Missing approval input is not approval.

An accepted proposal is a user-approved claim. Source references do not independently prove that claim is true.

### 3.3 Display and final review

Define `RenderManifest` with ordered display fields, explicit omissions, template version, layout ID, and content hash.
Show skill ordering, punctuation normalization, and duplicate-description omissions before content approval.
Treat targeting preferences and source metadata as non-display fields. Declare other template omissions in the reviewed manifest.

Remove free-text LaTeX polishing and repair. Render from the approved snapshot with fixed templates.
Keep lint and HR advice visible. Do not change text to satisfy metric-density or strong-verb preferences.

Use these layouts, in this order: `standard`, then `compact`.
Use 10-point text and 0.65-inch margins for `standard`. Use 10-point text and 0.5-inch margins for `compact`.
Use compact spacing only in `compact`. Do not reduce text below 10 points or omit approved content.
Set `max_pages` to 2 by default. Permit explicit values from 1 through 5 in `RunRequest`.
Accept `standard` when page count is within the limit and no overfull box warning exists.
Otherwise, try `compact`. Stop if it still exceeds the page limit or reports an overfull box.
Return `layout_limit_exceeded` with the page count and available remedies. Never remove text to pass.
Permit at most two successful layout candidates. Retry a transient compile failure twice with unchanged input.
Stop on template syntax errors. Offer content revision if supported layouts cannot produce a usable document.

Compare extracted PDF text with the expected display tokens. Normalize Unicode compatibility ligatures and whitespace only.
Do not remove signs, units, numeric order, case, or ordinary hyphens. Disable automatic word hyphenation in the template.
Require the generated template labels and display-field order to appear in the expected token stream.
Block final export on content mismatch, malformed PDF, missing pages, or a known compile error.
Keep HR and optional vision judgments advisory. Display their status and unresolved warnings in the final review.

Define `PdfReview` with `review_id`, `content_hash`, `pdf_hash`, `template_version`, `layout_id`, and `created_at`.
Require explicit confirmation of the current review ID and PDF hash. Any new PDF invalidates prior final approval.
The preview endpoint is available for inspection. Preview access cannot prevent a user from saving draft bytes manually.

### 3.4 Artifact isolation

Create a server-generated UUID `artifact_id`. Do not form paths from unchecked thread input.
Use `~/.resume_generator/runs/<artifact_id>/attempts/<number>/` for each attempt.
Keep run-owned input copies, LaTeX, logs, PDF, images, manifests, and approval records.

Hash the PDF after compile. Verify that hash before preview, final approval, export, and artifact linking.
Keep the run PDF immutable. Keep the existing friendly output-folder export as a second copy.
Reserve its filename. Copy to a temporary sibling. Flush and verify the hash before the release transaction.
Replace the reserved destination inside the final release transaction, after checking cancellation.
Keep released artifacts until explicit deletion. Do not add automatic cleanup in this roadmap.

## 4. Import, persistence, and compatibility

### 4.1 Import

- Retain PDF and TEX input support. Set the upload limit to 10 MiB.
- Set the supported extracted-text limit to 48,000 characters for resume and JD input.
- Send all supported text to the parser. Remove silent slices, including the 2,000-character stored-JD slice.
- Reject larger inputs explicitly. Keep the earlier profile unchanged. Do not add chunk merging in this release.
- Record PDF extraction per page. Require review for a page without readable text.
- Allow explicit confirmation that such a page is intentionally blank. Otherwise, require a text-based source.
- Save parsed content as a draft. Show the source and parsed fields before saving the base profile.
- Save with an expected profile revision and an atomic file replace.
- Bind provenance metadata to that profile revision. Missing or stale metadata must not imply verified provenance.
- If manual YAML edits change the hash, require profile review before a new run uses that revision.

Full input delivery and schema validity do not prove complete semantic extraction. Preserve the source for review.

### 4.2 Durable run service

Add one `RunService`. Make API and CLI wrappers use that service.

Define `RunRequest` with job input, execution mode, `max_pages`, optional job/evaluation references, and an optional parent run.
Define `RunView` with run status, artifact status, fixed-input hashes, current pending action, diagnostics, and release metadata.
Store approved content, its manifest, review IDs, preview hash, release hash, attempt number, and legacy parent in v2 state.

Required methods:

| Method | Contract |
|---|---|
| `create(request: RunRequest) -> RunView` | Persist a queued run and fixed inputs. |
| `drive(run_id: str, action: ResumeAction | None) -> RunView` | Continue until a human/model pause or terminal state. |
| `get(run_id: str) -> RunView` | Return durable state and current pending action. |
| `subscribe(run_id: str) -> AsyncIterator[Event]` | Stream current-process progress. Rebuild pending state after restart. |
| `cancel(run_id: str) -> RunView` | Record explicit user cancellation and retain diagnostics. |
| `recover_legacy(run_id: str) -> RunView` | Create or return the linked safe v2 recovery run. |

Use a process-independent `filelock` lock per run. Acquire it without waiting for a second writer.
Return a conflict when another process owns the run. Release the lock at every durable pause.
The API may schedule `drive`. JSON CLI calls must await `drive` before exiting.

Cancellation writes an idempotent command to a separate SQLite command table. It does not acquire the active worker lock.
The worker checks cancellation before and after external calls, before each pause, and before release commit.
An in-flight provider request may finish. Ignore its result after cancellation. Do not export it.
Show `cancellation_requested` until the worker records `cancelled`. A boot reconciliation completes pending cancellations.

Extend the current library database for run indexing. Keep LangGraph checkpoints as the pending-state authority.
Persist creation, pause, interruption, cancellation, failure, and completion. Do not suppress required persistence errors.
Reconcile the run index from the latest checkpoints at startup. Do not resume work automatically.

Use run status values: `queued`, `running`, `awaiting-input`, `interrupted`, `complete`, `failed`, `cancelled`.
Use artifact status values: `pending`, `available`, `missing`, `legacy_unverified`.
Store error category and stage separately. Keep cancellations out of system-failure totals.
Record app version, build revision when known, provider/model, input hashes, retry counts, and run duration.
Do not store API keys or full provider responses in diagnostic events.

Use a `release_records` table with states `approved`, `exporting`, and `released`.
Persist approval and its action ID before preparing the temporary export copy.
Start a final immediate SQLite transaction. Check cancellation, rename the prepared copy, then commit `released` and completion together.
A cancel command committed earlier prevents the rename. A later command waits and returns the committed completed state.
A cancel request after release returns the completed state. It does not erase prior approval or application history.
Expose final downloads only after `released`. The released record is authoritative if the final checkpoint write was interrupted.
For an unfinished export, show `interrupted`. An explicit continue action reuses the same approved bytes and reserved destination.
If cancellation follows a crash after rename but before commit, remove only the matching uncommitted export and temporary copy.
Check the expected hash and ownership before cleanup. Preserve an unexpected replacement and report the conflict.
If the friendly export is missing, retain the canonical run PDF. Show export availability separately and permit a verified re-export.

### 4.3 Migrations

Set the checkpoint schema to v2. Set the REST contract version to 2. Set the new JSON command envelope version to 1.
Use ordered SQLite migrations with `PRAGMA user_version`. Back up databases with the SQLite backup API before migration.
Back up the base YAML. Use a migration lock. Apply each migration in a transaction.

Preserve v1 completed records and files. Label them as legacy. Do not invent review hashes.
For a paused v1 run, create one linked v2 run from stored source inputs and answers.
Clear old approvals, whole-resume enrichment, LaTeX, PDF paths, and retries. Require fresh content and PDF reviews.
Do not modify the original checkpoint. Return a clear recovery error when required saved inputs are absent.

Mark missing historical artifacts as missing. Permit manual relinking only after inspection.
Without a historical hash, label a relinked artifact as legacy and identity-unverified until review.
Never infer a match from filename alone. Do not convert old generations into submitted applications.

## 5. Public interfaces

Retain existing run endpoints. Add fields without deleting existing response keys.

| Interface | Addition |
|---|---|
| `GET /api/runs/{id}` | Current pending action, review IDs, hashes, diagnostics, and artifact availability |
| `POST /api/runs/{id}/resume` | Typed actions with the expected review ID; reject stale input with HTTP 409 |
| `GET /api/runs/{id}/preview` | The frozen draft PDF for the current PDF review |
| `POST /api/runs/{id}/recover` | Idempotent v1 recovery |
| `GET /api/readiness` | Profile, provider, parser, compiler, and renderer readiness |
| `POST /api/profile/imports` | Create an import draft |
| `GET /api/profile/imports/{id}` | Inspect the source, parsed draft, and coverage warnings |
| `POST /api/profile/imports/{id}/accept` | Save a reviewed draft with the expected current profile revision |
| `POST /api/runs/{id}/artifact/relink` | Inspect and attach a user-selected historical PDF; retain legacy status |
| `GET/POST /api/memory/proposals` | List or create explicit durable-change proposals |
| `POST /api/memory/{id}/decision` | Accept, reject, or revoke a proposal with an action ID and expected profile revision |
| `GET/POST /api/jobs` | List jobs or capture a manual posting snapshot |
| `POST /api/jobs/{id}/evaluations` | Create a durable evaluation operation |
| `GET /api/evaluations/{id}` | Return evaluation progress, findings, and stale status |
| `GET/POST /api/applications` | List or create planned applications |
| `POST /api/applications/{id}/events` | Record explicit progress or a linked correction |
| `GET /api/outcomes` | Return local descriptive bands, counts, and exclusions |
| `GET /api/outcomes/export` | Download the standalone local outcome report |
| `GET /api/metrics` | Separate generation health, explicit application counts, jobs and known companies |
| `GET/PUT /api/discovery/sources` | Read or replace the reviewed public-board configuration |
| `POST /api/discovery/sync` | Start one bounded manual sync |
| `GET /api/discovery/syncs/{id}` | Return source results, limits, and freshness |
| `POST /api/model-tasks/{id}/respond` | Validate one external-agent result against its durable request |

Keep the current upload route as a compatibility wrapper that creates an import draft. Do not save automatically.
Keep the final PDF endpoint restricted to released v2 artifacts or labelled legacy artifacts.
Validate stage, review ID, content hash, and PDF hash on every review action. Reject stale actions before scheduling work.
Use `action_id` for idempotency. Replaying the same action returns its stored result.
An action ID reused with different content returns HTTP 409.

Add `POST /api/runs/{id}/content-preview`. It returns the projection and content hash for selected proposal IDs.
It does not approve content or continue the graph. The UI and CLI must use this same projection function.

Use stage-specific resume payloads:

| Kind | Required payload |
|---|---|
| `ask_missing` | `action_id`, `request_id`, `answers` |
| `present_suggestions` | `action_id`, `review_id`, `source_revision`, `approved_ids`, `content_hash` |
| `review_pdf` | `action_id`, `review_id`, `content_hash`, `pdf_hash`, `decision` |
| `continue` | `action_id`; valid only for an interrupted run without a pending human request |
| `model_request` | `action_id`, `request_id`, `input_hash`, `result` |

For PDF review, permit `approve` or `reject`. Rejection records user cancellation and retains the draft.
A later content revision starts a new linked run. It requires new content and PDF reviews.
Do not require a PDF hash before a PDF exists. Do not treat a model response as a human decision.

Define import acceptance separately from run actions. Require `action_id`, `review_id`, `draft_hash`, and `expected_profile_revision`.
Include explicit intentionally blank page confirmations when applicable. A missing current profile has revision null.
Import rejection requires its action ID and review ID. Neither action is a model response.

Extend the existing `hitl_pending` event kinds with `review_pdf` and, in R4, `model_request`.
Keep `ask_missing` and `present_suggestions`. Add review metadata to their typed payloads.
Add completion hashes and `artifact_status` to the existing completion event.

## 6. Reusable corrections and role evaluation

### 6.1 Memory

Define `MemoryProposal` and `MemoryRecord`. Use kinds `candidate_fact`, `target_preference`, and `writing_rule`.
Store exact proposed values, source references, source run, base revision, acceptance, revocation, and supersession.
Use the library database for the memory audit. Do not create a second candidate-fact overlay.

Accept candidate-fact changes through the same revision-checked profile save operation.
Use an `applying` audit entry before a profile write. Record old and proposed profile hashes.
On recovery, compare those hashes with the canonical profile. Complete or cancel the audit entry deterministically.
If neither hash matches, mark a conflict. Do not overwrite the profile.
If the proposed hash matches, finish the acceptance audit. If the old hash matches, retain a pending proposal for explicit retry.
Revoke preferences and writing rules directly. Reverse a fact change through a new reviewed proposal against the current profile.

Apply active preferences and writing rules only to new evaluations and edit proposals.
Do not change existing approved snapshots. Require explicit acceptance for every durable promotion.
Reject targets outside the declared memory types. Do not accept settings, credential, or filesystem-path targets.

### 6.2 Role decisions

Add immutable job snapshots and evaluations to the library database.
Keep existing `JobDescription` fields for generation compatibility.

Define requirement evidence as `supported`, `transferable`, `contradicted`, or `unknown`.
Every requirement cites its JD span. Every supported finding cites a profile path or confirmed answer.
Missing profile text is unknown evidence, not a proven lack of skill.

Use rubric `fit-v1`:

| Dimension | Weight |
|---|---:|
| Required skills | 35 |
| Responsibilities | 25 |
| Scope and seniority | 15 |
| Domain experience | 10 |
| Candidate preferences | 10 |
| Additional skills | 5 |

Split each dimension's weight equally across its distinct requirements.
Exclude a dimension only when no criterion exists. Renormalize active dimensions to 100.
Assign 1.0 to supported evidence, 0.5 to justified transferable evidence, and 0.0 to explicit contradiction.
For unknown evidence, use 0.0 in the lower bound and 1.0 in the upper bound.
Coverage is the percentage of active weight with known evidence. Return no score when no usable criteria exist.

Evaluate eligibility separately. Use only explicit authorization, clearance, required-presence, and user hard-constraint evidence.
Set `fail` for a confirmed conflict. Set `unknown` for an unresolved stated restriction. Otherwise, set `pass`.
Do not infer authorization from name, home address, or preferred location.

Recommend `prioritize` when eligibility passes, coverage is at least 80%, and the lower bound is at least 70.
Recommend `skip` for a confirmed eligibility conflict or explicit user decision. Otherwise, recommend `review`.
Never block generation solely because of this recommendation. Explain overrides and unknowns.

Store the rubric version, model identifier, profile hash, and JD hash. Mark changed-input evaluations as stale.
These weights are product defaults. They are not validated hiring predictors.

## 7. Applications, outcome reports, and discovery

### 7.1 Application records

Define `Application` separately from generation records. Link immutable job, evaluation, and sent-artifact hashes.
Use stages `planned`, `submitted`, `screening`, `interviewing`, `offer`, `rejected`, `withdrawn`, and `closed`.
Record `response_received` as an event. Do not treat every response as an interview.
Allow direct forward changes when intermediate stages are unknown. Do not invent their dates.
Require an explicit correction or reopen event for a backward change.
Use unique action IDs. Keep event corrections as linked records rather than deleting original evidence.

Require a user action to record submission. PDF completion must never set `submitted`.
At submission, record the actual selected released artifact, or record that the artifact is unknown.
A later generation must not change the artifact recorded as sent.
Keep application history if a PDF is deleted. Mark its artifact unavailable.
Retain a company while jobs or applications still reference it.

### 7.2 Outcome reports

Keep reports local and descriptive. Group by the stored evaluation band: `0–39`, `40–69`, and `70–100`.
Use the lower-bound score recorded at submission. Do not rescore history automatically.
Count a positive response when an explicit response, interview, or offer event exists.
Count a negative outcome after explicit rejection without a positive response, or user-confirmed closure without response.
Keep pending and withdrawn-without-outcome records outside the denominator.
Display every excluded count. Suppress rates below ten resolved records in a band.
Do not change rubric weights automatically or present the report as causal evidence.

### 7.3 Bounded discovery

Support Greenhouse, Lever, and Ashby public board APIs. Support configured company boards only.
Use official contracts: [Greenhouse](https://docs.greenhouse.io/job-board), [Lever](https://github.com/lever/postings-api), [Ashby](https://developers.ashbyhq.com/docs/public-job-posting-api).

Use these defaults: 20 boards per manual sync, 1,000 jobs per board, three concurrent requests, and a 20-second timeout.
Allow two transient retries. Respect `Retry-After` up to 60 seconds. Stop that source if a longer wait is requested.
Set the response-body limit to 10 MiB. Mark a source partial if any bound truncates its result.
Build request URLs from a provider enum and validated board slug. Do not fetch an arbitrary configured URL.
Use the existing public-network address checks. Do not follow redirects outside the declared provider hosts.

Deduplicate by provider, board, and external job ID. Flag cross-provider similarities for review; do not merge them silently.
Mark a removed posting only after a complete successful refresh. A failed or partial refresh cannot establish removal.
Preserve previous data with a stale warning after refresh failure. Do not evaluate every job automatically.
Let the user select a role for evaluation or generation. Preserve its exact JD snapshot through that handoff.

## 8. Agent interface and distribution

Add `resume-generator agent` JSON commands. Retain the interactive commands as wrappers.
Use commands `start`, `inspect`, `respond`, `cancel`, `export`, `import`, `evaluate`, `discover`, `memory`, and `application`.
Use input files for structured actions. Do not build shell commands from user text.
Return one UTF-8 JSON document on stdout. Send human-readable progress to stderr. Never prompt in JSON mode.

Use envelope fields: `schema_version`, `ok`, `command`, `resource`, `data`, `next_action`, and `error`.
Use `resource: {kind, id}`. Permit `run`, `profile_import`, `role_evaluation`, `discovery_sync`, `application`, and `memory`.
Use null for commands without one resource. Use null for `next_action` when no response is required.
Use `--resource <kind>:<uuid>` to inspect or respond to any pending operation.
Use exit codes: 0 for success or a durable pause; 1 for invalid input; 2 for missing prerequisites; 3 for execution failure; 4 for conflict.

Define execution modes `configured_provider` and `external_agent`. Default to `configured_provider`.
Expose only implemented modes in readiness results. Reject external-agent requests before R4 instead of silently using a backend provider.
An external-agent request contains `request_id`, `task`, `input_hash`, `schema_name`, `schema_version`, `input_payload`, and `output_schema`.
Pause at that request. Accept only the matching structured response. Validate it with the same schemas and source checks.
Do not call the configured-provider model in external-agent mode. Use no more than two response attempts per request.
Keep final human review separate from model responses. An agent response is never a content or PDF approval.
Disable optional HR/vision model calls in external-agent mode v1. Keep deterministic checks and user PDF review mandatory.

Give import and evaluation operations the same request/response model boundary. Do not maintain a second parser or evaluator.
Use a reviewed import draft for first-time setup. Do not require a configured backend API key in external-agent mode.

Keep generation rows in the existing resume library. Store import and evaluation lifecycles in a separate `operations` table.
Use operation states `pending_model`, `pending_review`, `running`, `interrupted`, `complete`, `failed`, and `cancelled`.
Mark interrupted processing without rerunning it. Permit an explicit continue action from its stored stage.
Use `OperationService.create`, `OperationService.get`, and `OperationService.drive` for those lifecycles.
Route inspect and respond commands through get and drive. Share locks, action replay, and model-task validation.
Create this lifecycle service in R1 for import drafts. Extend it for evaluation in R2 and external model requests in R4.
Store model tasks by owner kind, owner ID, task name, input hash, and schema version. Reuse a validated result after replay.
Keep pending model requests durable across restart. Require the current request ID and input hash when a response arrives.

Provide one host-neutral skill contract. Add tested installation guides for Codex and Claude Code.
Require the skill to show review requests and wait for explicit user decisions. Do not claim this proves user identity cryptographically.
Describe configured-provider billing and host-agent billing separately. Do not promise a free allowance for every host.

Prepare a wheel, source archive, bundled UI, install guide, short demonstration, and release notes.
Use synthetic profiles in demonstrations. Use personal success stories only with explicit permission.
Use the existing GitHub install path as the first supported distribution route. Prepare PyPI metadata and a publishing workflow.
Publishing remains a separate external release action. No registry publication or repository-setting change occurs during planning.

## 9. Verification and writing rules

Use isolated test state. Keep routine tests independent of real credentials and personal resume files.
Use deterministic model and API fixtures. Add real compiler/browser checks in the release gate.
Run browser tests against a started server. Treat unexpected skips as release failures.
Check a built wheel, not only the source checkout. Test Python 3.12 and 3.13.
Test Windows path/lock behavior and macOS/Linux artifact behavior.

Have the project owner arrange five voluntary pilot sessions before broad release. Do not contact people automatically.
Record setup completion, first reviewed PDF, interruptions, observed errors, and the participant's factual review.
Require four of five participants to reach a reviewed PDF without developer intervention. Require zero artifact identity mismatches.
Keep pilot notes local and permissioned. Treat this sample as usability evidence, not a general reliability estimate.

Use ASD-STE100-style instructions. Use active voice, short sentences, defined technical terms, and one action per numbered step.
Keep procedural sentences at 20 words or fewer. Keep descriptive sentences at 25 words or fewer where practical.
Keep code identifiers and interface contracts exact. Do not rewrite them to meet a sentence limit.
Reference: [official ASD-STE100 standard information](https://www.asd-ste100.org/STE_faq.html).

The implementation plan must name each task, dependency, test, and pass checkpoint.
Do not start the next release until the earlier release checkpoint passes.

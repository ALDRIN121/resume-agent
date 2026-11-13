# R1 execution contract

This document resolves the R1 decisions raised by the EGM review. It supplements the existing design and plan.
Later decisions are now defined in the [career-domain](2026-11-13-career-domain-execution-contract.md), [discovery](2026-11-13-discovery-provider-contract.md) and [external-model](2026-11-13-external-model-contract.md) supplements. Implementation is local on branch `codex/resume-agent-r1`. C4 remains open.

## Activation and alternatives

Build the v2 components through private service interfaces first. Keep the current CLI/API usable during those commits.
Switch new generation to v2 only when the graph, review handlers, preview endpoint, and both clients are integrated.
Do not add a setting that bypasses final review. Keep the checkpoint version at 1 for the current graph until that switch.

Retain YAML for candidate facts and the existing library/checkpoint databases. Replacing storage would create a separate migration without resolving content drift.
Use fixed-revision JSON pointers instead of permanent IDs in every nested field. This preserves existing profile files; edits require a new review after a revision change.
Use deterministic templates instead of model-written LaTeX. This trades unrestricted styling for a testable content boundary.
Reject oversize input instead of implementing chunk merging in R1. The error preserves the old profile; source completeness must not depend on an unreviewed merge.
Use one process lock per operation and a SQLite command path for cancellation. A single-worker app would be simpler but would not protect CLI/API contention.

## T01: isolated runtime

Use `RESUME_GENERATOR_STATE_DIR` to select an explicit state root. Resolve it before defining state paths.
When set, read dotenv only from that root. Do not migrate the old home directory into an explicit root.
Before test-module imports, create a temporary suite root, set the variable, and remove inherited provider/settings overrides.
Pass that environment into wheel subprocesses and browser servers. Fake-home tests must use child environments, not change the parent's HOME.
Default application behavior remains `~/.resume_generator` and the existing dotenv lookup.

## Identity

Canonical JSON uses UTF-8, sorted keys, compact separators, and JSON null for optional fields.
Profile hashes use `UserResume.model_dump(mode="json")`, including defaults.
Value hashes use the canonical JSON encoding of the exact referenced value.

The content hash covers schema version, source revision, approved text fields, display order, omissions, and accepted proposal IDs.
It excludes template and layout parameters. The render hash covers content hash, template-file SHA-256, and exact layout parameters.
The PDF hash covers the final bytes. Final review binds all three hashes and the review ID.
Source, profile, memory, and JD snapshots remain fixed during a run. R1 memory is the empty snapshot; R2 must version active memory.

## Storage ownership

Keep LangGraph's existing `state.sqlite` schema under LangGraph ownership.
Use `library.sqlite` for v2 operation indexing, accepted actions, cancellations, and PDF export records.
Existing `companies` and `resumes` remain legacy/library records, not application-submission records.
Use a database migration lock and SQLite backup API before the first upgrade of an existing database.
Use `BEGIN IMMEDIATE` for command acceptance and PDF export commit. Do not use a second database for cancellation.

Core migration 1 adds these tables. JSON columns contain validated canonical JSON; timestamps are UTC ISO-8601 strings.

```sql
CREATE TABLE IF NOT EXISTS migration_meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK (schema_version = 2),
  artifact_id TEXT NOT NULL UNIQUE,
  parent_run_id TEXT,
  status TEXT NOT NULL CHECK (status IN
    ('queued','running','awaiting-input','interrupted','complete','failed','cancelled')),
  input_json TEXT NOT NULL,
  source_revision TEXT NOT NULL,
  pending_json TEXT,
  result_json TEXT,
  error_code TEXT,
  error_stage TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operations (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('profile_import','role_evaluation')),
  status TEXT NOT NULL CHECK (status IN
    ('pending_model','pending_review','running','interrupted','complete','failed','cancelled')),
  input_json TEXT NOT NULL,
  pending_json TEXT,
  result_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
  owner_kind TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  action_id TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  request_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('accepted','complete','failed')),
  result_json TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (owner_kind, owner_id, action_id)
);
CREATE TABLE IF NOT EXISTS cancellations (
  owner_kind TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  action_id TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  PRIMARY KEY (owner_kind, owner_id)
);
CREATE TABLE IF NOT EXISTS release_records (
  run_id TEXT PRIMARY KEY REFERENCES runs(id),
  review_id TEXT NOT NULL,
  action_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  render_hash TEXT NOT NULL,
  pdf_hash TEXT NOT NULL,
  canonical_pdf_path TEXT NOT NULL,
  destination TEXT NOT NULL UNIQUE,
  temporary_path TEXT NOT NULL UNIQUE,
  ownership_token TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (status IN ('approved','exporting','released')),
  approved_at TEXT NOT NULL,
  released_at TEXT
);
```

Create the core tables and set `PRAGMA user_version=1` in one transaction. Reject a newer unsupported version without changing it.
Do not replace existing tables. Do not drop rows or overwrite existing non-null library values during migration.
Run creation persists input JSON before external work. Action IDs are scoped by owner kind and owner ID.
Replay the same action/hash from its stored result. Reject a reused action ID with a different payload.
An accepted action without a result requires recovery from the latest checkpoint; it must not silently start a second execution.
Model calls may repeat after an interruption, but accepted edits and final exports must remain idempotent.

## Legacy history precedence

Treat an existing library as canonical. Automatic JSONL import may populate only a newly created library.
Use insert-only writes, then persist `legacy_jsonl_imported` in the same transaction. Never replay history over existing rows.
Do not infer that a missing row in an existing library should be restored from an older history file.
Retain legacy files and history. A later explicit repair must show the proposed import before applying it.

## PDF export and cancellation ordering

1. Persist the accepted PDF review and complete export plan as `approved` before creating the temporary copy.
2. Include destination, temporary path, token, expected hashes, and run ownership in that durable plan.
3. Set `exporting` before copying. Prepare, flush, and verify the temporary copy outside the final transaction.
4. Start an immediate transaction and check cancellation.
5. If cancellation exists, do not rename. Remove only owned temporary/reservation files and record cancellation.
6. Otherwise, rename atomically and commit the released record, completed run, and action result in that transaction.

| Crash point | Recovery |
|---|---|
| Approved, no temporary copy | Offer explicit continuation using the stored plan. |
| Partial or bad temporary copy | Remove only the owned copy; prepare again after continuation. |
| Valid temporary copy | Verify and reuse it after continuation. |
| Destination renamed, transaction uncommitted | Check ownership and hash. Reuse on continuation or remove after cancellation. |
| Released record committed, checkpoint incomplete | Treat the released record as authoritative. Do not compile or export again. |
| Unexpected destination bytes | Preserve the file and report a conflict. Never delete it by filename alone. |

Cancellation writes a command without taking the active worker lock. Workers check before and after external calls and before export commit.
A cancellation committed before final rename wins. A cancellation arriving after export commit returns the completed result.

## Verification boundaries

Use isolated state before any API import. Keep credentials out of persisted input, diagnostics, and test output.
Preserve mocked browser tests. Add a separate real API/socket journey before C1, with only external model/network work substituted.
Preserve successful TeX logs and structured overflow results before implementing layout selection.
Keep one model retry owner: at most two total attempts, with no SDK/graph multiplication.
Retry network/5xx once after 0.5 seconds. Retry malformed complete JSON once with the same full input.
Do not retry authentication, unavailable-model, context-limit, or truncated-output errors automatically.
Retry HTTP429 only when Retry-After is at most60 seconds; otherwise stop with actionable rate-limit status.
Persist attempt counts before calls. Resume does not reset the budget.

T02–T09 activate together after review and verification. The existing workflow remains available until that integration point.

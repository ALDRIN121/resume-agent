# Runtime transition and dispatch inventory

This inventory describes the implemented v2 workflow. Fixed inputs, accepted actions and checkpoints govern continuation. Startup reconciles saved state; it does not start model or network work.

## Generation

| Current boundary | Handler | Next boundary or result |
| --- | --- | --- |
| Create | `Runtime.create_run`, `RunService.create` | Persist fixed inputs and `queued`. Explicit execution acquires ownership. |
| `fetch_jd` | `Workflow.drive` | Persist the complete supported JD. A source failure produces a stage-specific failure. |
| `extract_jd` | `ModelTaskRunner.run` | Validate and save structured JD fields. |
| `questions` | `ModelTaskRunner.run` | Save the question batch. Skip the human question pause if the batch is empty. |
| `ask_missing` | Typed `AskMissing` through the shared lifecycle | Save explicit answers. Continue to proposals. |
| `proposals` | Shared proposal output validation | Save fixed targets, references and unselected proposals. |
| `present_suggestions` | Pure preview plus typed `PresentSuggestions` | Validate selected IDs and the content hash. Freeze the approved projection. |
| `render` / `pdf_check` | Deterministic renderer and PDF content guard | Try supported layouts. Preserve approved text. Block malformed, mismatched or over-limit output. |
| `hr_advisory` | Bounded advisory model task in configured mode only | Retain advice without changing approved content. Host mode disables optional HR and vision calls. |
| `review_pdf` | Typed `ReviewPdf` | Reject records cancellation. Approve binds current review/content/render/PDF hashes and starts export. |
| `release` | `ReleaseService.release` or explicit recovery | Reuse the owned plan and exact approved bytes. Commit released record, action result and completion atomically. |
| `complete` | Released record is authoritative | Return the same result on replay. A missing friendly copy can be reexported from verified canonical bytes. |

## Shared interruption and error handling

| Condition | Dispatch rule |
| --- | --- |
| A worker already owns the operation | Return conflict. Do not start a second writer. |
| Pending human review | Require its typed action, current review/request ID and relevant hashes. Continue cannot impersonate that decision. |
| Interrupted accepted action | Require explicit `Continue`. Replay the accepted command from its saved stage. Preserve consumed attempts and original export intent. |
| External model request | Save `model_request` and release ownership. Matching structured responses pass the same schema/evidence checks. They never approve content or PDF bytes. |
| Retryable model error | Consume the bounded task attempt before calling. Persist it. Replay cannot reset the budget. |
| Exhausted or non-retryable error | Save sanitized category and stage. Retain prior inputs and artifacts. |
| Cancellation | Record the command without waiting for the worker lock. Check around external work and before export commit. Ignore a completed call after cancellation. |
| Cancellation after uncommitted rename | Remove only a matching owned export. Preserve unexpected replacement bytes and save a run-local diagnostic. |
| Process restart | Reconcile index, checkpoint, release and cancellation records. Show interrupted work without executing it. |
| Legacy recovery | Create one linked v2 child from retained inputs. Clear old approvals and require fresh reviews. |

## Other durable operations

| Operation | Transition and authority |
| --- | --- |
| Profile import | Persist source before parsing. `pending_model` becomes `pending_review`. Only typed acceptance saves the profile. Hash/provenance checks detect an already-saved acceptance after a crash. Explicit Continue completes its audit without rewriting. Reject/cancel retain source and audit. |
| Role evaluation | Freeze profile, memory, job and rubric. Validate model analysis and source references. Save the exact result before indexing it. Replay reuses that result. Input changes mark it stale. |
| Reviewed memory | A proposal remains inactive until accepted. Candidate-fact promotion records old/proposed hashes before YAML replacement. Recovery compares those hashes. Rejection changes no active facts or rules but remains audited. |
| Discovery | Persist the manual scan and request budget. Continue requires an explicit action. Cached old observations cannot replace newer authority. Only a clean complete scan can remove absent postings. |
| Application events | Explicit typed commands append stage/submission/correction history. Generating or exporting a PDF does not record submission. |

## Interface ownership

Web actions use the HTTP routers and the shared runtime. The interactive CLI uses the same services. JSON commands await a durable pause or terminal result and emit one envelope. `GET`/inspect/preview do not approve or execute work.

Import discovery, continuation and cancellation routes are `GET /api/profile/imports`, `POST /api/profile/imports/{id}/continue`, and `POST /api/profile/imports/{id}/cancel`. Web upload returns a durable ID before parsing through `defer_processing=true`.

Evidence includes `test_v2_workflow.py`, `test_run_service.py`, `test_operation_service.py`, `test_run_recovery.py`, `test_release_service.py`, `test_final_recovery.py`, `test_model_tasks.py`, `test_external_agent.py`, `test_evaluation_operations.py`, `test_discovery_service.py`, `test_interface_parity.py`, and the real browser journeys. Exact execution results are in the [R4 acceptance record](../superpowers/plans/2026-11-13-r4-acceptance.md).

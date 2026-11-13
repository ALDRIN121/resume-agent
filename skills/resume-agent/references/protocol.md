# Agent JSON protocol, version 1

Use `resume-generator agent COMMAND --input FILE --resource KIND:ID`.

The command reads one UTF-8 JSON object from a file. Structured text never enters a shell command. Files have a 10 MiB limit. JSON duplicate keys and non-finite numbers are invalid. The command does not read standard input or prompt.

Standard output contains one JSON document. Progress goes to standard error. `agent --help` prints command help.

Every result contains `schema_version`, `ok`, `command`, `resource`, `data`, `next_action`, and `error`. A resource has `kind` and `id`. Missing fields use null. Error objects have `code` and `message`.

| Exit | Meaning |
| --- | --- |
| 0 | Success or a saved pause |
| 1 | Invalid input, missing file or unknown resource |
| 2 | Missing prerequisites |
| 3 | Execution failed; inspect saved work |
| 4 | Conflict; inspect the current revision or review |

Resource kinds are `run`, `profile_import`, `role_evaluation`, `discovery_sync`, `application`, and `memory`.

| Command | Input and behavior |
| --- | --- |
| `start` | `job_input`, `input_type` (`text` or `url`), optional job/evaluation references, page limit and execution mode. Creates a run and awaits a saved pause or terminal result. |
| `inspect` | Requires `--resource`. Reads current saved state without model calls. For run content preview, supply `review_id`, `source_revision`, and `approved_ids`. |
| `respond` | Requires `--resource`. The action file uses the same typed action as the app. Include its action ID and current review/hash fields. |
| `cancel` | Requires `--resource`. Discovery also needs an action file with `action_id`. This does not record application withdrawal. |
| `export` | Requires a run resource and `action_id`, `expected_pdf_hash`, optional `recover`. Reexports already approved canonical bytes. |
| `import` | `source_path` selects a local TEX or text-based PDF. Parsing creates a draft. Acceptance requires a separate typed response. |
| `evaluate` | `job_id`, optional `answers`, `user_text`, `eligibility_facts`. Uses the saved job, profile and memory snapshots. |
| `discover` | Domain operations: `sources`, `configure`, `refresh`, `list`, `inspect`, `postings`, `continue`, `cancel`. |
| `memory` | Domain operations: `list`, `propose`, `inspect`, `decide`. Proposals do not activate themselves. |
| `application` | Domain operations: `list`, `create`, `inspect`, `event`. Events record local history only. |

Domain commands use `{"op":"OPERATION","payload":{...}}`. Payloads use the shared API schemas. Use empty payloads for reads. Existing-resource operations require the matching resource flag. Creation and list operations reject an existing resource.

Example start file:

```json
{"job_input":"The complete job description.","input_type":"text","max_pages":2,"execution_mode":"configured_provider"}
```

Example application creation file:

```json
{"op":"create","payload":{"job_id":"SAVED_JOB_ID","action_id":"UNIQUE_ACTION_ID"}}
```

Example discovery refresh file:

```json
{"op":"refresh","payload":{"expected_sources_revision":"CURRENT_64_CHARACTER_HASH","action_id":"UNIQUE_ACTION_ID"}}
```

Use the actual revision and identifiers from inspection. Reuse an action ID only when retrying the same payload. Changed payloads need a new action ID.

`next_action` returns the saved request. Show its evidence to the user before asking for a decision. Content selections start empty. Inspect the complete content preview before confirming its hash. Show the exact PDF before final approval. Import acceptance requires the reviewed draft hash and current profile revision.

A saved queued operation can report `next_action.kind = execute`. Invoke `respond` without an input file to execute it. An interrupted operation needs a typed `continue` action and action ID. A pending human review rejects a response without its typed action.

Model results and human decisions are different action kinds. A model result cannot approve content, accept an import or approve a PDF. Inspect saved work after an execution error; its resource and current pause remain available when storage can be read.

The default execution mode is `configured_provider`. It uses the configured backend provider and its billing. Use `external_agent` to request structured results from the calling agent instead. This mode needs no backend API key. The host agent can have its own subscription or usage charges.

External mode returns `next_action.kind = model_request`. Its `payload` contains `task`, `schema_name`, `schema_version`, the complete `input_payload`, `output_schema`, and response-attempt counts. Supply a typed `model_request` response with `action_id`, the exact `request_id`, `input_hash`, and structured `result`. The hash binds the task, schema, complete messages and captured execution identity.

The first schema-invalid result leaves one response attempt. A second invalid result fails the task. Stale requests consume no attempt. Saved validated results survive restart. Source-reference checks still apply after schema validation. These can reject an invalid claim immediately.

Host import and evaluation use the same boundary. A model-produced import draft still requires human acceptance. Host generation still requires content and exact PDF review. Optional HR and vision model calls are disabled in external mode. Provider and model labels are `external_agent` and `host_agent`; they do not identify the actual host model.

The optional API route `POST /api/model-tasks/REQUEST_ID/respond` accepts the same typed model response. It finds the saved owner and checks the current request before processing. The registry is a lookup index; the owner checkpoint holds the response budget and result.

This protocol does not establish cryptographic proof of human identity. Host installation and version smoke checks are separate release evidence.

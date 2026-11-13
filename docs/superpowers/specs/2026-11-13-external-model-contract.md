# External model execution contract

13 November 2026. This supplements design section 8 and the R1 execution contract.

Public JSON modes are `configured_provider` and `external_agent`. Their fixed compatibility values are `app` and `host`. New host inputs record provider `external_agent` and model `host_agent`. The actual host model is unknown unless separately recorded in host validation evidence.

Generation needs a reviewed profile and local PDF tools. Host mode needs no backend API key. First-time host import needs no existing profile. The same import parser, evaluation validator, proposal validator, renderer and release service process both modes.

Model task identity includes the stage, complete messages, output schema, captured provider/model and mode. Each owner checkpoint stores task records. A complete record stores the schema-validated result. Replaying that task reuses its result and retains the checkpoint contract.

A host task registers a request ID, then checkpoints its pending record. Its model request carries the complete input and output schema. It does not call a backend provider. The lifecycle publishes a run pause or operation model pause only after a saved checkpoint.

Schema-valid response envelopes use `ModelResponse`. Request ID and input hash must match the current pending action. Before schema validation, the task checkpoints the consumed attempt, action ID, result and validation status. An interrupted validation resumes from those saved bytes. It does not consume another attempt.

One schema-invalid response leaves one attempt. Two invalid responses fail the task. The same action replay returns its saved result. A stale request consumes no attempt. Source-reference validation remains mandatory after schema validation and can fail immediately.

The library database has an `external_model_requests` lookup index. It maps request ID to owner and task identity. The owner checkpoint remains the only task budget and result authority. If registration precedes a crash, the next drive reuses that ID. If the index is missing, the saved checkpoint ID can restore it. An index row cannot approve a response without the owner's matching pending request.

`POST /api/model-tasks/{request_id}/respond` resolves the owner and drives the same lifecycle. Path and body request IDs must match. Import and evaluation dispatch remain separate. The existing owner lock serializes responses and cancellation.

Model results cannot accept an import, choose content changes or approve a PDF. Those actions remain separate typed requests. Host mode disables optional HR and vision model calls. Deterministic checks and exact PDF approval remain mandatory.

Ruling: retain the owner checkpoint as the task authority and add only a lookup index. This avoids scanning all owners for a response route. The cost is a recoverable two-store registration window. Tests cover both sides of that window.

Ruling: input hash includes the complete task identity, including the output schema. Schema changes create a distinct identity. The host echoes the supplied hash; it does not infer a hash from candidate text alone.

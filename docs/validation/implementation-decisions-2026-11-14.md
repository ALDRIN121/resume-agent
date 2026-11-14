# Implementation decisions and costs

This record carries every ruling from the execution ledger, in ledger order. Some ledger entries contain more than one ruling; they have separate rows here. The final review dispositions are also recorded in the [review report](final-branch-review-2026-11-14.md).

## Rulings I made

| # | Decision and reason | Cost if wrong |
| --- | --- | --- |
| 1 | Complete reliable generation before later product features. Treat EGM findings as constraints. Resolve each contract before activating its code. | Later features arrive later; an incorrect contract needs revision before activation. |
| 2 | Reuse the prepared checkout on a feature branch. Preserve existing plans and dependencies. Isolate runtime state. | Less filesystem separation than a second worktree. |
| 3 | Merge durable and legacy library records in read adapters. Prefer v2 on duplicate IDs. Derive company counts. Do not write both stores. Disable v2 history deletion until retention is designed. | Users cannot delete v2 history yet; adapter errors could affect displayed counts. |
| 4 | Freeze whitelisted reviewed-profile provenance with run input. Do not copy settings. Legacy inputs default to no provenance. | A small input-schema extension must remain compatible. |
| 5 | Resolve memory, requirement grouping, response categories and partial-discovery ambiguity in the career-domain contract before R2/R3. | A mistaken interpretation requires a contract and implementation change. |
| 6 | Start the private renderer against the frozen content manifest while helper review finishes. Do not activate it in clients early. | A small adapter change may be needed after review. |
| 7 | Keep the Unicode font template and exact content guard. Warm the compiler dependency cache separately with fictional input. | More local toolchain setup; unsupported environments remain blocked. |
| 8 | Extract and reuse pure proposal prompt/output helpers for the durable model runner. Avoid nested event loops and duplicated prompts. | Helper interfaces need coordination with the workflow. |
| 9 | Start private artifact work against the frozen artifact contract while lifecycle work continues separately. Persist the reservation plan before copying. Commit release within its database transaction. | Integration may need a small adapter change before client activation. |
| 10 | Remove public-DNS dependence from mocked HTTP tests at their external boundaries. Retain DNS-block tests and separate real browser/server checks. | Mocked tests alone do not prove live integration. |
| 11 | Use validated JSON snapshots and shared ownership/action transactions. Bind PDF approval to the render hash. Keep the old graph until integration. Index reconciliation must not execute work. | Integration changes are required in the shared clients. |
| 12 | Recompute the selected content projection through a pure action validator. Validate review/source/IDs before accepting its hash. Preview reads do not change pending state. | Clients must supply the exact current review metadata. |
| 13 | Store provenance in reserved `_resume_agent` metadata in the same atomic YAML replacement. Hash normalized profile fields. Manual field edits make provenance stale. | Raw YAML has an extra mapping; manual changes require review. |
| 14 | Permit private R2 work after local C1 behavior passes. Keep remote platform certification as a distribution prerequisite. | Platform-specific fixes may still be needed; no untested-platform support claim. |
| 15 | Continue inline after worker usage limits instead of repeatedly dispatching failed workers. Retain one fresh whole-branch review. | No independent reviewer for every later integration task. |
| 16 | Establish eligibility only through typed eligibility evidence or accepted hard constraints. Do not infer authorization, clearance or presence from identity or ordinary answers. | Users must enter restriction facts in the proper channel. Interpretation stays advisory. |
| 17 | One application record represents one attempt with at most one effective explicit submission. Reopening does not resubmit. Correct submission mistakes through audit or a new attempt. Freeze the historical evaluation and preserve later stages for forgotten submissions. | Separate attempts require separate records. |
| 18 | Use Ashby's documented job URL as identity because its public schema lacks an ID. A missing URL is malformed/partial. | A changed URL can create a second historical posting identity. |
| 19 | An absent posting means removal from a clean complete scan, not proof that the employer closed it. Retain timestamps. Use one global concurrency bound and a separate network lifecycle. | Closure cannot be asserted; discovery has its own persistence tables. |
| 20 | Use a monotonic database observation sequence. An older resumed scan cannot replace newer posting evidence. | An old recovered board can be partial and need a fresh scan before removals. |
| 21 | Preserve `/sync` as a creation alias. Persist a durable scan separately from explicit execution/Continue. | A new scan uses two calls. |
| 22 | Deliver the deferred application tracker UI and CLI with T18. Keep the same application service contract. | T18 has broader scope. |
| 23 | Map public `configured_provider` and `external_agent` to internal app/host execution. Enable external mode only after T20. | Public and internal names differ. |
| 24 | Permit an explicit no-file `execute` response for queued work. Human reviews still require typed actions. | One additional recovery action must be documented. |
| 25 | Require the same review ID, source revision and approved IDs in CLI previews as in HTTP. | Callers must echo current metadata. |
| 26 | Keep checkpoints authoritative for external model requests. Add a recoverable lookup index. | A two-store registration window requires tested reconciliation. |
| 27 | Retry a schema-invalid external response once. Fail invalid semantic evidence as configured mode does. | An invalid claim can require new work instead of another automatic retry. |
| 28 | Put the canonical protocol in the bundled skill reference. Link the documentation to it. | Readers make one additional link hop. |
| 29 | Ship the portable skill in the product and require explicit project export. | Installation needs an explicit step. |
| 30 | Report that the baseline host already completed the handoff correctly. Use a compact protocol reference; do not invent a baseline failure or causal improvement. | No measured claim that the skill improves host behavior. |
| 31 | Treat Claude as unsupported until an authenticated smoke passes. Do not alter the owner's sign-in. | Claimed host support is limited. |
| 32 | Complete local verification, PDF inspection and whole-branch review while external C4 gates remain open. Keep the build a candidate. | A reviewable local candidate exists before broad-release evidence does. |
| 33 | Keep Linux/Windows certification, pilots and authenticated Claude as open external gates. | Platform, usability or host defects can remain undiscovered; broad release waits. |
| 34 | Claim only the recorded Codex handoff. Do not claim universal hosts, an unreported model identity or billing entitlement. | Different hosts, models and accounts may fail or charge differently. |
| 35 | Separate fixture transport/parser/service results from live feeds and real provider authentication. | Provider drift or account-specific issues may appear later. |
| 36 | Keep human review and advisory scores. Exact references and arithmetic cannot establish factual truth, semantic completeness or hiring predictions. | A reviewer can miss a plausible interpretation error. |
| 37 | Typed local actions do not provide cryptographic human identity. That is outside this local contract. | Another process with the same local access can issue actions. |
| 38 | Retain contact-label ambiguity, repeated approved project wording and a paragraph page split as recorded presentation limits. The inspected content and hashes match. | Some resumes need manual presentation adjustment; the independent reviewer did not repeat the visual inspection. |
| 39 | Keep labelled unverified legacy downloads and deferred v2 history deletion. Preserve compatibility and the audit until retention is designed. | Legacy files lack new approval guarantees; v2 deletion remains unavailable. |
| 40 | Preserve the ignored execution evidence while C4 remains open. Leave the existing `.egm/` directory untouched. | Local evidence occupies disk until gate closure. |

| 41 | Supply exact precomputed JD citation spans to the model. Keep full source, schema and strict source validation. Do not rely on unsupported provider controls or increase the output budget. | The prompt and repeated citation quotes grow slightly. Large or difficult inputs can still exhaust the model limit. |

## Deferred minors

The final independent review returned no separate Minor findings. The presentation limitations and compatibility decisions above are retained explicitly; they are not silently treated as completed improvements.

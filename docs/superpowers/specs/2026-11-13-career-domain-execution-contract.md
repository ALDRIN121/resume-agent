# Career domain execution contract

This supplement resolves the remaining EGM domain decisions before R2/R3 implementation. R2 activation still requires C1. R3 activation still requires C2.

## Immutable memory inputs

Capture the active memory records and their exact values, IDs and accepted revisions when a generation or evaluation operation is created. Sort records by ID and hash canonical JSON. Persist the snapshot and hash with fixed profile/JD inputs. Include that hash in model-task identity and evaluation staleness. Later acceptance, revocation or supersession changes only future operations. Never reload live memory during replay of an existing operation.

Candidate facts live only in the canonical profile. Their audit records describe accepted profile changes; do not apply them again as an overlay. Active target preferences and writing rules are distinct typed records. Target preferences may contain preferred locations, work modes and explicit hard constraints. Writing rules may contain exact user-authored drafting instructions. Neither type can set credentials, settings or filesystem paths.

Rejecting a proposal records the decision in the audit. It changes neither the active profile nor active rules. This replaces the ambiguous phrase “no durable effect” in T12.

Fact promotion writes an applying audit entry with old/proposed profile revisions before ProfileStore.save. Persist the reviewed proposed profile and source/action binding in that entry. On recovery: proposed hash means finish the audit; old hash means retain pending explicit retry; any other hash means conflict. Never overwrite an unrelated current profile. Reversing a fact change needs a new reviewed proposal. Revoking a rule does not rewrite historical operations.

## Requirement normalization

Score distinct requirement groups, not model-generated prose fragments. Each group has a dimension, explicit operator (single/all/any), stable ID, JD citation and one or more atomic member criteria. Retain the exact source wording and offsets. Mixed or unclear operators need review; do not silently flatten them.

Use a versioned conservative normalization: Unicode NFC, trimmed/collapsed whitespace and case folding for matching only. Preserve punctuation, signs, versions and units. Do not collapse C, C++ and C#. Consolidate exact normalized member/group duplicates within the same dimension; keep all JD citations. Do not invent semantic aliases. Equivalent whitespace/case and member order fixtures must yield identical weights.

Each atomic finding is supported, transferable, contradicted or unknown. Absence from the profile is unknown. Supported/transferable/contradicted findings require a resolving source reference; transferable also requires a justification.

| Group | Result |
|---|---|
| single | Its member result |
| all | Contradicted if any member is contradicted; otherwise unknown if any is unknown; otherwise transferable if any is transferable; otherwise supported |
| any | Supported if any member is supported; otherwise transferable if any is transferable; otherwise unknown if any is unknown; otherwise contradicted |

Split a dimension's weight across its distinct groups. Use the six fixed fit-v1 weights from the design, renormalized only across dimensions with usable groups. Use exact rational arithmetic internally, with a declared display rounding rule. Unknown contributes [0,1], supported [1,1], transferable [0.5,0.5], contradicted [0,0]. Coverage is known active weight. Zero usable groups returns null bounds and coverage, not a zero score.

Keep eligibility separate. Only explicit authorization, clearance, presence and user hard constraints can establish a conflict. Identity, home address, missing data and general location preferences do not prove authorization or its absence. Preserve prioritize/review/skip rules and explicit generation override from the original design.

## Response classification

An application response_received event must name its category: acknowledgment, rejection, favorable, or other. A generic reply or acknowledgment is not a positive outcome. Favorable responses and explicit screening/interview/offer progression establish a positive outcome. An explicit rejection or user-confirmed closure without any favorable response is negative. Pending and withdrawal without an outcome remain outside the resolved denominator.

Keep the event audit append-only. A later rejection does not erase an earlier favorable response. A correction explicitly linked to an erroneous earlier event can invalidate that evidence; it does not delete the original event. Record occurred_at as null when unknown; recorded_at is not a fabricated application date.

Freeze the evaluation lower bound and rubric/input identities when submission is explicitly recorded. Future evaluation or document changes do not rescore submission history. Use bands0–39,40–69,70–100 and suppress rates below10 resolved records per band. Report unknown-score and all exclusion counts. Never call these bands hiring probabilities or causal evidence.

## Discovery completeness

Use configured provider/board identities only. Enforce the design's20boards,1000jobs/board,3concurrentrequests,20secondtimeout,10MiB decodedresponse and initial-plus-two-transient-attempt limits. Parse the complete response under those bounds; never infer a posting closed from a failed/partial refresh.

Any malformed record, missing stable identity, conflicting or repeated external ID, pagination failure or enforced truncation makes the board partial. Preserve valid results and previous jobs; report the exact rejected/duplicate/limit counts. Identical duplicates may be deduplicated for storage, but completeness remains conservative. Only a clean, fully exhausted refresh can mark unseen prior postings removed.

Keep immutable JD snapshots per provider/board/external identity and content hash. Cross-provider similarity is a review hint, not an automatic merge. Discovery never calls a model or submits an application.

## Application event decisions

An application record represents one attempt, with at most one effective explicit submission. Reopening changes progress and does not resubmit. A separate attempt needs a new application, or a linked correction when original submission data was wrong. Recording a forgotten earlier submission preserves already-recorded later progress.

Corrections retain the original event and name it explicitly. An optional validated replacement takes effect at that original event's position. The latest explicit correction to that original controls its effective value; corrections cannot target corrections. Keep the full original audit. Unknown occurrence dates remain null.

At submission, freeze the complete evaluation the user selected, including its exact lower fraction, rubric and input identities. Record whether it was stale when recorded. Never choose the latest evaluation or artifact implicitly. Selected released artifacts retain their hashes if files disappear. A role mismatch remains visible rather than rewriting truthful sent-document history. Reports require an effective explicit submission; other progress remains visible until the user records that missing submission event.

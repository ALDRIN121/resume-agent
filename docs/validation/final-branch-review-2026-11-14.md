# Final branch review and recovery fixes

The independent reviewer inspected `5c1938f670ce5fc1322d3b26bcac5cb85e377743..b075271255b8ef02155aaa0f024c4a68eddc20b4`. The review found three Important defects and no Critical defects. The author accepted all three findings. Commit `aa19fea` fixes them in one test-first pass. The reviewer independently ran seven focused checks; all passed. No second review was used to certify the fixes.

Later actual-model testing exposed two additional issues after this review. Both were [fixed and verified](live-fixes-2026-11-14.md) at `362a3b5`. This earlier independent review is retained as scoped evidence.

## Findings and changes

| Finding | Effect before the fix | Implemented change | Regression proof |
| --- | --- | --- | --- |
| Export reservation before release-row insertion | Continue failed permanently after a crash between filename reservation and release-row insertion. | Explicit Continue reuses the owned reservation, original output location, ownership token, accepted action and approved hashes. It does not create a second export. | `tests/test_final_recovery.py::test_public_continue_reuses_reservation_before_release_row` runs with unchanged and changed output settings. Both failed before the fix and pass afterward. |
| Startup cleanup conflict | A replaced export followed by cancellation prevented the whole application from starting. | Preserve the replacement file. Save an `export_ownership_conflict` diagnostic on the affected run. Allow unrelated saved work to open. Retain the diagnostic across repeated restarts while cleanup is unresolved. | `tests/test_final_recovery.py::test_startup_cleanup_conflict_is_durable_per_run_and_preserves_other_work` failed before the fix and passes afterward. |
| Interrupted or undiscovered import | The browser showed continuous parsing and locked navigation. A lost upload response could hide the saved import ID. | Return the durable ID before parsing in the web flow. Discover saved imports without starting model work. Offer explicit Continue, Cancel and Minimize controls. Continue an already-saved acceptance without rewriting the profile or parsing again. | The backend import test and both tests in `tests/test_import_recovery_ui.py` failed before the fix and pass afterward. The second browser test kills and restarts the real fixture server after the YAML write. |

The focused backend recovery suite passed **100 tests**. Both new browser journeys passed. Full-suite results and the exact candidate environment are in the [R4 acceptance record](../superpowers/plans/2026-11-13-r4-acceptance.md).

Cancelling an import does not undo an earlier profile acceptance. Its source and audit remain available. An unresolved export ownership conflict needs owner inspection; startup does not delete a file it cannot prove it owns.

## Review scope decisions

These are explicit dispositions of every behavior the reviewer declined to judge as a new defect.

| Behavior | Decision and reason | Cost if wrong |
| --- | --- | --- |
| Linux, native Windows, five pilots and authenticated Claude | Keep the external acceptance gates open. Local tests cannot supply the missing evidence. | Platform or usability defects can remain undiscovered. Broad release must wait. |
| Universal host compatibility, actual host model and billing | Claim only the recorded Codex handoff. The host did not report its actual model. No universal compatibility or billing entitlement is claimed. | A different host, model or account can behave differently or incur charges. |
| Live public feeds and real provider authentication | Keep fixture transport/parser/service results separate from live certification. No personal board or paid provider request was needed for these repairs. | Provider drift or account-specific failures can appear in live use. |
| Factual truth, semantic completeness and predictive fit | Keep human review and advisory scoring. References, exact arithmetic and token guards prove narrower properties. | A plausible but incorrect interpretation can survive if the reviewer misses it. |
| Cryptographic human identity | Typed local actions record a decision; they do not authenticate a human cryptographically. This remains outside the local product contract. | Anyone with the same local access can issue an action. |
| Contact handles, repeated project wording and page breaks | Retain the recorded presentation limitations. No approved text was missing or changed in the inspected samples. | Some resumes need manual presentation adjustment. The independent reviewer did not repeat the ten-PDF visual inspection. |
| Unverified legacy downloads and v2 history deletion | Preserve explicit legacy labels. Keep v2 deletion unavailable until a retention design exists. | Older files lack new approval guarantees; users cannot yet delete v2 audit history through the app. |

No separate Minor finding was returned. The presentation observations above remain documented limits.

Evidence logs remain in the local execution workspace: `final-review-red.log`, `final-recovery-backend2.log`, `final-import-ui-red.log`, `final-import-ui-green.log`, and the final Python matrix logs/XML. The repository contains the regression tests and this disposition record.

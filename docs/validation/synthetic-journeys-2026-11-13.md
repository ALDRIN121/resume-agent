# Synthetic journey record

Test revision: `b0098aa01490df784645a8ca6639f5e38400f4fc`. All 30 named journeys passed in the final flagged Python 3.12 matrix. Runtime recovery fixes are in `aa19fea`.

These are controlled automated journeys with fictional data. They are not volunteer pilots. The final matrix passed **935 checks with zero failures and zero skips**.

| Journey | Result | Executed test |
| --- | --- | --- |
| Reviewed export without selected edits | PASS | `tests/test_reliability_journey.py::test_real_review_restart_and_exact_export[reject-all]` |
| Reviewed selected wording and exact export | PASS | `tests/test_reliability_journey.py::test_real_review_restart_and_exact_export[visible-edit]` |
| Import restart, reject and accept | PASS | `tests/test_reliability_journey.py::test_real_import_source_draft_restart_reject_and_accept` |
| Memory accepted, reused and revoked | PASS | `tests/test_memory_ui.py::test_memory_is_reviewed_then_reused_or_revoked` |
| Fact correction before/after acceptance | PASS | `tests/test_memory_ui.py::test_fact_correction_shows_exact_before_after_and_requires_acceptance` |
| Saved draft and hard-constraint review | PASS | `tests/test_memory_ui.py::test_memory_form_survives_reload_and_hard_constraints_need_review` |
| Prioritized role source handoff | PASS | `tests/test_career_ui.py::test_role_decision_preserves_sources_and_explicit_generation_override[CASE_PRIORITY-prioritize-False]` |
| Unknown evidence and explicit override | PASS | `tests/test_career_ui.py::test_role_decision_preserves_sources_and_explicit_generation_override[CASE_UNKNOWN-review-True]` |
| Confirmed restriction and explicit override | PASS | `tests/test_career_ui.py::test_role_decision_preserves_sources_and_explicit_generation_override[CASE_INELIGIBLE-skip-True]` |
| Stale profile retains old evaluation | PASS | `tests/test_career_ui.py::test_changed_profile_marks_evaluation_stale_and_keeps_old_result` |
| Complete/partial/failed/empty discovery and released-artifact handoff | PASS | `tests/test_search_operations_ui.py::test_manual_discovery_partial_failure_restart_and_exact_job_handoff` |
| Explicit submission and response correction | PASS | `tests/test_search_operations_ui.py::test_application_tracker_records_only_explicit_submission_and_audited_correction` |
| Source draft, cancel and hard restart | PASS | `tests/test_search_operations_ui.py::test_source_draft_cancel_and_interrupted_scan_need_explicit_continue` |
| Host-mode real PDF review/export without backend | PASS | `tests/test_external_agent.py::test_host_requests_survive_restart_and_reach_exact_reviewed_export_without_backend[real-pdf-tools]` |
| Host import request then separate acceptance | PASS | `tests/test_external_agent.py::test_host_import_is_a_durable_request_then_a_separate_human_review` |
| Host stale response and two-invalid budget | PASS | `tests/test_external_agent.py::test_stale_responses_use_no_attempts_and_two_invalid_results_exhaust_budget` |
| Consumed host response crash recovery | PASS | `tests/test_external_agent.py::test_consumed_response_validation_recovers_without_counting_twice[validating]` |
| Legacy recovery creates one child with fresh review | PASS | `tests/test_run_recovery.py::test_legacy_child_fixed_source_fresh_reviews_and_restart_idempotency` |
| Provider timeout budget and safe failure | PASS | `tests/test_model_tasks.py::test_terminal_errors_have_safe_durable_stage_and_bounded_calls[response5-transport-2]` |
| Reject PDF retains draft and never releases | PASS | `tests/test_release_service.py::test_reject_retains_draft_records_cancellation_and_replays` |
| Schema migration DDL rollback | PASS | `tests/test_migrations.py::test_failed_migration_rolls_back_all_ddl_and_version` |
| Closed-stdin JSON and literal metacharacters | PASS | `tests/test_cli_json.py::test_start_inspect_preview_stale_response_and_cancel_never_prompt` |
| Older cached discovery cannot replace newer evidence | PASS | `tests/test_discovery_service.py::test_resuming_an_older_cached_scan_cannot_roll_back_newer_posting_evidence` |
| Host proposal invalid source fails closed | PASS | `tests/test_external_agent.py::test_host_proposals_cannot_bypass_candidate_source_reference_validation` |
| Reserved export recovery at original output | PASS | `tests/test_final_recovery.py::test_public_continue_reuses_reservation_before_release_row[False]` |
| Reserved export retains destination after settings change | PASS | `tests/test_final_recovery.py::test_public_continue_reuses_reservation_before_release_row[True]` |
| Cleanup conflict preserves unrelated work across restarts | PASS | `tests/test_final_recovery.py::test_startup_cleanup_conflict_is_durable_per_run_and_preserves_other_work` |
| Discover import before parsing and continue saved acceptance | PASS | `tests/test_final_recovery.py::test_deferred_import_is_discoverable_before_parsing_and_continues_saved_acceptance` |
| Browser discovers lost upload response without model work | PASS | `tests/test_import_recovery_ui.py::test_import_creation_with_lost_client_id_is_discovered_without_model_work` |
| Browser resumes crashed profile acceptance without reparse | PASS | `tests/test_import_recovery_ui.py::test_browser_continues_interrupted_profile_save_without_reparsing` |

The journeys cover reviewed export, rejection, interruption, provider failure, migration/recovery, memory, role evidence, explicit application events and partial discovery. The final six cases reproduce the independent review findings through service/API/browser boundaries.

Evidence: `final-python312-green.xml` and `final-journeys.json` in the local execution workspace. The first complete candidate matrix at `b075271` passed 929 checks. The first post-review matrix found one outdated upload-URL fixture (934 passed, one failed). Its correction and the final all-green result are retained separately.

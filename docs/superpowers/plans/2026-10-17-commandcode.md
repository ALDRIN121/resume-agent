# Command Code Integration Plan

**Goal:** Connect the existing resume workflow to Command Code using DeepSeek V4.1 Flash, expose it in Settings/onboarding, and verify a complete browser run.

**Architecture:** Reuse the existing ChatOpenAI adapter, provider catalog, secret storage, and React configuration controls. Use `https://api.commandcode.ai/provider/v1` and `deepseek/deepseek-v4.1-flash`; disable vision by default for this text model. Keep credentials out of YAML and responses.

**Validation:** Offline adapter/settings regression tests, existing Python suite, production frontend build, then a live browser upload → JD extraction → questions → suggestion review → PDF download. Inspect logs and PDF contents/layout. Record external failures truthfully.

- [x] Add failing tests for provider discovery, settings/secrets, authenticated HTTP request, selected-provider configuration status, and actionable errors.
- [x] Implement Command Code config, adapter and catalogs; update UI provider switching and CLI integration.
- [x] Run regression tests and rebuild bundled UI.
- [x] Run sample resume/job through browser; reproduce and fix flow failures with regression tests.
- [x] Verify PDF content/layout and run final checks; record results.

**Review focus:** wrong key/provider, unsupported vision, API timeouts/retries, structured extraction, interactive resume after checkpointing.

Results: see `docs/validation/commandcode-2026-10-17.md`. All five steps verified; output assessment records metric-preservation limitations.

Real-data follow-up completed using Aldrin Joseph’s October resume and saved Senior AIML posting. See `docs/validation/aldrin-joseph-real-data-2026-10-17.md`; 246 tests pass.

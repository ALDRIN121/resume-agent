# LiteLLM integration implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan inline. Preserve the earlier uncommitted CLI and UI fixes in this checkout.

**Goal:** Route the seven existing providers through LiteLLM and reliably validate structured resume data across their supported models.

**Architecture:** Keep `get_chat_model(settings, task, temperature)` as the app boundary and use `langchain-litellm` with LiteLLM's Python SDK. Keep provider IDs, model names, credentials, endpoint overrides, LangGraph events, and Pydantic resume data compatible. Centralize structured-output method selection in the returned model, using non-strict tool calling where supported and schema-instructed JSON with local validation otherwise.

**Tech stack:** Python 3.12–3.13, LangChain/LangGraph, LiteLLM, Pydantic, pytest/respx, existing React UI.

**Spec:** User approved the preceding proposal to put LiteLLM behind the existing factory while retaining LangGraph and Pydantic validation, and requested completing the existing fixes.

## Global constraints

- Preserve all seven provider settings and existing secret environment variable names.
- Pass credentials per request; never copy provider keys into new environment variables or YAML.
- Preserve OpenRouter headers, Command Code's chat endpoint and timeout, Ollama local/remote auth, and NVIDIA endpoint overrides.
- Preserve text and vision model selection, synchronous/asynchronous use, streaming, and request timeouts.
- Keep arbitrary skill categories and reject invalid structured output.
- Preserve bundled UI artifacts and test actual installed distributions.
- Add no proxy service, mandatory cloud account, unrelated UI redesign, or new provider configuration flow.

## Review focus

- Unknown/custom model IDs must have a validated JSON fallback when capability metadata is absent.
- Missing tool calls and malformed JSON must raise parsing failures instead of returning empty successful data.
- Model/provider prefixes must not be duplicated or misroute third-party model IDs.
- Keys and custom endpoint settings must stay isolated between concurrently selected providers.
- Vision payloads and LangGraph token events must remain compatible with the common adapter.

## Task 1: Replace provider adapters and centralize structured parsing

**Files:** `src/resume_agent/llm.py`, `src/resume_agent/cli.py`, `pyproject.toml`, `uv.lock`, `src/resume_agent/agents/base_resume_loader.py`, `src/resume_agent/agents/hitl.py`, `tests/test_llm.py`, existing provider regression tests.

**Interface:** Preserve `get_chat_model(...) -> BaseChatModel` and existing `with_structured_output(PydanticModel)` calls.

- [x] Add failing factory/wire tests for provider/model mapping, credentials, endpoints, vision selection, sync/async streaming, unknown models, and invalid structured output.
- [x] Run targeted tests and confirm failures identify the missing LiteLLM adapter and capability handling.
- [x] Add compatible bounded dependencies and update the lockfile; remove unused native LangChain provider packages.
- [x] Implement the shared LiteLLM adapter and structured-output selection, and remove duplicated provider conditions in resume agents.
- [x] Run provider and agent regressions plus source lint; fix integration failures before proceeding.

## Task 2: Validate delivery and document the integration

**Files:** `README.md`, existing packaging/browser tests, generated frontend assets only if required.

- [x] Update architecture and development documentation to describe the common LiteLLM adapter and supported capability fallback.
- [x] Run the full Python suite with DNS access, frontend tests/build, and lint.
- [x] Build and install distributions outside the source checkout; check UI root/assets and the installed model factory.
- [x] Obtain an independent read-only review and resolve material findings with regression coverage.
- [x] Refresh the local installed CLI's dependencies and verify its doctor/help checks without replacing saved credentials.

## Progress

- Existing baseline: 273 Python tests passed, 43 optional tests skipped; 4 frontend tests and lint passed before the migration.
- Execution: inline in the current authorized checkout, preserving the earlier changes. No commits or publication requested.
- Final migration verification: 312 Python tests passed, 43 optional browser/visual tests skipped; 4 frontend tests, production build, lint, dependency compatibility, and installed-wheel regression checks passed.
- Review finding fixed: the default JSON parser repaired incomplete JSON. Three cutoff regressions failed first; strict JSON decoding and explicit length-cutoff rejection now pass, including `include_raw` error reporting.
- Related CLI safeguard verified RED→GREEN: failed re-imports preserve the prior saved resume, which was previously deleted before parsing.
- Installed CLI refreshed with locked dependencies. `doctor` and `serve --help` exit successfully. A minimal live Command Code test reaches the provider and returns HTTP 401 because the saved API key is expired; renewal requires a fresh user credential.
- Verification limits: provider HTTP and streaming tests use mocks; native Windows execution and opt-in browser/visual tests were not run. No deferred review findings.

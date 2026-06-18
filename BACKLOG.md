# Resume Generator — Review Backlog

> Generated **2026-05-31** from a report-only, multi-agent code review (7 specialists: AppSec, Dependency/Supply-chain, AI-Framework/LangGraph, Backend FastAPI, Frontend React/Vite, QA, UI/UX-a11y, Build/DevOps). **No code was changed.** Findings were web-grounded and verified where marked. This file is a triage list, not a changelog.

## Legend

- **Severity:** P0 (breaking / time-critical) · P1 (high) · P2 (medium) · P3 (low/polish). Security severities reflect the **single-user localhost** threat model (it lowers most of them).
- **Confidence:** ✅ Verified (confirmed in code / by running a tool / web source) · 🟡 Suspected (depends on runtime/version not executed).
- **Source IDs:** `SEC-*` AppSec · `DEP` dependency audit · `AIF-*` AI-framework · `BE-*` backend · `FE-*` frontend · `QA` qa · `OPS-*` devops · `UX-*/A11Y-*/FLOW-*/VISUAL-*/RESP-*/INTERACT-*` ui-ux.

**One-line takeaway:** the core LangGraph résumé pipeline is solid and well-defended; risk is concentrated in the two newer additions — the **web UI** (a high-fidelity prototype only partially wired to the backend, with demo data shown as real) and the **FastAPI layer** (no auth, async-correctness gaps, zero tests) — plus **stale model IDs, one of which stops working 2026-06-01.**

---

## Remediation status (updated 2026-05-31)

Worked top-down. **Verified after each change: 203 tests pass, frontend builds clean.**

| Item | Status | Notes |
|---|---|---|
| **P0-1** Model IDs | ✅ Done | All live IDs (gemini-2.5-flash, gpt-5.x, claude-opus-4-8) in config/wizard/frontend/pdf_validator; OpenAI factory uses the configured model; dead `_map_openai_model` removed. |
| **P0-3** API auth/SSRF | ✅ Done | New `api/security.py` loopback Origin/Host guard on mutating HTTP routes + both WS handshakes; CORS `allow_credentials=False`; SSRF now resolves DNS + validates every IP and re-validates each redirect hop. |
| **P0-2** Demo-data-as-real | 🟡 Partial | **Gating done** — fake PDF, sample lint/vision/retry, and notification footer no longer surface on real runs. **Real wiring still TODO** (upload, settings-save, résumé-save, doctor, fetch-preview remain no-ops). |
| **P1-1** Backend async | ✅ Done | Late-subscriber sentinel (`_TERMINAL_STATUSES`), parse-task retention, lifespan graceful shutdown, `--reload` warning. |
| **P1-2** Frontend WS/data | ✅ Done | WS is the single source of truth for events (removed duplicating getRun seed); `key={selectedRunId}` remount; guarded `JSON.parse`. |
| **P1-3** Dep CVEs + floors | ✅ Done | Lock bumped (idna 3.17, urllib3 2.7.0, langchain-core 1.4.0, langchain-openai 1.2.2, langsmith 0.8.7, lxml 6.1.1, starlette 1.2.1); pyproject floors raised to the 1.x line. |
| **P1-4** Broken test suite | ✅ Done | Smart-quote SyntaxError fixed; stale prompt snapshots regenerated. |
| **P1-7** SPA path traversal | ✅ Done | `resolve()` + `is_relative_to` containment guard on the catch-all route. |
| **OPS-01** Dual dev-group | ✅ Done | Consolidated into one `[dependency-groups].dev` → `uv sync` installs respx/pytest-asyncio. ⚠️ `uv sync --extra dev` no longer exists. |
| **P1-5** Untracked code + CI | ⬜ Open | `Frontend/`+`api/` still untracked; no CI. Commit needs explicit go-ahead. |
| **P1-6** A11y blockers | ⬜ Open | Focus trap + `prefers-reduced-motion` not yet done. |
| **P2 / P3** | ⬜ Open | Not started (incl. version drift, upload validation, exception scrubbing, a11y polish). |

---

## P0 — Do first (breaking / time-critical)

### P0-1 · Model IDs broken / expiring ✅ (AIF-01, AIF-02, AIF-03 + web-verified)
- **`gemini-2.0-flash` / `-lite` shut down 2026-06-01** (new projects must use `gemini-2.5-flash`+ / 3.x). Wizard Gemini list is stale (`gemini-1.5-*`, `-exp`). — `ui/setup_wizard.py:60,68`
- **Default model `gemma4:31b-cloud` does not exist** (no `gemma4`; no `:31b` Gemma tag) → fresh Ollama install can't pull the default. — `config.py:47`
- **Vision `claude-opus-4-6` does not exist** (current Opus is `claude-opus-4-8`; Sonnet `claude-sonnet-4-6` is valid). Same stale ID in wizard + `pdf_validator.py:4` docstring. — `config.py:48`, `ui/setup_wizard.py:62,70`
- **OpenAI factory silently discards the user's configured model** — `_map_openai_model` hardcodes `gpt-4o`/`gpt-4o-mini` (themselves dated; GPT-5.x is current) and ignores `model.default`. — `llm.py:50-60,112-118`
- **Fix:** correct all model IDs against live catalogs; for OpenAI use `model_name` directly; refresh wizard lists (Gemini/NVIDIA/OpenAI).

### P0-2 · Web UI: demo data shown as real + core actions are no-ops ✅ (FE-07/08/14/15, UX-01/02/03/05/08, FLOW-03/04/05)
- `FakePDFPage` ("Aldrin Carlos / Acme Corp") renders for a **real** completed run whenever `pdf_url` is missing. — `live-run.jsx:373,519-528`; hardcoded filename `live-run.jsx:501`
- `SAMPLE_*` / `LINT_WARNINGS` / `VISION_ISSUES` / `RETRY_ATTEMPTS` fallbacks fire on real runs (not gated on `!threadId`). — `live-run.jsx:649-652,869,872`
- Notification footer hardcodes "WebSocket connected · 2 runs active". — `app.jsx:117-122`
- **File upload is simulated** — drop zones call `onUpload("aldrin_carlos_resume.pdf")`; real `uploadResume(file)` never called. — `app.jsx:396`, `screens.jsx:910`
- **Settings has no Save path; Résumé editor uses `defaultValue`** ("autosaves on blur" but no handler) → user edits silently lost. — `screens.jsx:1524-1727,1162-1308`
- Setup wizard step 4 hardcodes Tectonic/Poppler/fs checks as green; "Test key" is a length check; URL "Fetch preview" has no handler. — `screens.jsx:835-858,759,1402`
- **Fix:** gate all demo data behind `import.meta.env.DEV`; finish real wiring (upload, settings save, resume save, doctor, fetch-preview); show real placeholders when data absent.

### P0-3 · New API has no auth + secret-write + SSRF ✅ (SEC-01, SEC-02)
- No authentication/CSRF on any endpoint; `allow_credentials=True`. `PUT /api/settings` is an **unauthenticated secret-write** (writes attacker-supplied API keys to `~/.resume_generator/.env`, mutates `os.environ`) and accepts an arbitrary provider `base_url` → second-order exfiltration via `test-connection`. — `app.py:21-37`, `settings.py:39-45,87-88,174-199`
- **SSRF:** literal-IP block only; DNS-rebinding + redirect→`169.254.169.254` not stopped (`follow_redirects=True`, only original URL validated). — `tools/scrape.py:50-74,138-143`
- *Medium under strict-localhost, but the highest-impact cluster.* **Fix:** loopback bearer-token or strict `Origin`/`Sec-Fetch-Site` checks on all mutating routes + WS handshakes; resolve hostname → validate every resolved IP at connect → re-validate each redirect hop.

---

## P1 — High

### P1-1 · Backend async correctness ✅ (BE-03, BE-01, BE-02, BE-06, BE-07)
- **BE-03:** a WebSocket connecting *after* a run finished **hangs forever** — `subscribe()` replays events then blocks on `queue.get()` with no terminal sentinel for late subscribers. — `run_manager.py:103-116`
- **BE-01/02:** graph run tasks and resume-parse jobs are **fire-and-forget, unretained** → GC mid-flight + swallowed exceptions. — `run_manager.py:76,99`, `routers/resume.py:65`
- **BE-06/07:** in-memory singleton breaks under `uvicorn --workers>1` / `--reload` (CLI exposes `--reload`); no `lifespan`, blocking history I/O at import, no graceful shutdown of in-flight graphs. — `run_manager.py:315`, `cli.py:792-807`, `app.py:19-52`
- **Fix:** enqueue a terminal `None` (or return) for late subscribers on terminal status; retain tasks in a set + done-callbacks; add a `lifespan`; document/enforce single-worker; warn on `--reload`.

### P1-2 · Frontend WS / data correctness ✅ (FE-03, FE-01, FE-02, FE-05, FE-06, FE-04)
- **FE-03:** REST-seed vs live-WS **race** — `setApiEvents(detail.events)` overwrites events the socket already pushed → dropped/duplicated. — `live-run.jsx:597-609`
- **FE-02:** `LiveRunView` doesn't remount on `threadId` reuse → dead WS (add `key={selectedRunId}`). — `app.jsx:969`, `live-run.jsx:596-610`
- **FE-01/05/06:** invalid hook deps (stale parse timer `app.jsx:890`), autoplay stale closure (`live-run.jsx:613-622`), sidebar feedback loop (`app.jsx:909-911`).
- **FE-04:** unguarded `JSON.parse` in WS `onmessage`. — `api/ws.js:27`
- **Fix:** per recommendations above; merge seed+live by event id (needs backend event ids), or buffer WS events until the seed applies.

### P1-3 · Dependency CVEs + stale version floors ✅ (pip-audit, AIF-09)
pip-audit on the locked deps (npm audit: **0**):

| Package | Locked | Advisory | Fix |
|---|---|---|---|
| idna | 3.11 | CVE-2026-45409 | 3.15 |
| urllib3 | 2.6.3 | PYSEC-2026-141/142 | 2.7.0 |
| langchain-core | 1.2.29 | CVE-2026-44843 | 1.3.3 |
| langsmith | 0.7.31 | CVE-2026-45134 | 0.8.0 |
| langchain-openai | 1.1.13 | PYSEC-2026-76 | 1.1.14 |
| lxml | 6.0.4 | PYSEC-2026-87 | 6.1.0 |
| starlette | 1.0.0 | PYSEC-2026-161 | 1.0.1 |

- **AIF-09:** `pyproject` floors (`langgraph>=0.3`, `langchain-core>=0.3`, …) are **3 majors behind** the lock (running LangGraph 1.1.6 / langchain-core 1.2.29) → a non-`uv sync` install can resolve an untested/incompatible mix. Raise floors to the 1.x line.

### P1-4 · Test suite is broken right now ✅ (QA, OPS-01)
- `test_pipeline.py:259` contains a smart-quote (U+201C) → **SyntaxError**, the whole file fails to collect (~25 tests lost).
- `respx` + `pytest-asyncio` not installed because of the **dual `[dev]` group** bug (below) → `asyncio_mode=auto` no-ops; async tests would false-green; `test_scraper.py` won't collect.
- 2 stale prompt snapshots (`polish_system`, `fix_system`). Current run: **166 passed, 2 errors, 2 failures.**
- **OPS-01:** `[project.optional-dependencies].dev` (pytest≥8.3, pytest-asyncio, respx, ruff) vs `[dependency-groups].dev` (only pytest≥9.0.3) — pick one (keep `[dependency-groups]`, migrate the rest). — `pyproject.toml:51-56,74-77`

### P1-5 · Untracked web layer + no CI ✅ (OPS-03, OPS-06)
- **All of `Frontend/` and `src/resume_agent/api/` are untracked** → a clone gets the CLI only; `resume-generator serve` fails for collaborators. Commit both.
- **No CI** (no `.github/`). Add a 2-job workflow (Python: `uv sync` + ruff + pytest; Frontend: `npm ci` + `npm run build`). DevOps agent supplied a ready `ci.yml`.

### P1-6 · Accessibility blockers ✅ (A11Y-01, A11Y-03)
- **No focus trap** in any modal/palette (`BaseResumeParseModal`, `ReplaceBaseResumeModal`, `CommandPalette`); only Cmd-K closes on Escape. — `app.jsx:166-311,352-415,728-798,914-921`
- **No `prefers-reduced-motion`** anywhere despite 10+ always-on animations (one CSS block covers most). — `styles.css` keyframes; inline `animation` in JSX.

### P1-7 · SPA path traversal ✅ (SEC-04)
- Catch-all `/{path:path}` → `FileResponse(frontend_dist / path)` has no base-dir containment check. Add `resolve()` + `is_relative_to` guard or serve via `StaticFiles(html=True)` (also bump starlette→1.0.1). — `app.py:45-50`

---

## P2 — Medium

**Security hardening (SEC-03/05/06/07/08/09/10/11/12):** stream response size-cap *before* buffering (`scrape.py:149`); scrub exception strings from client responses & WS stream (`settings.py:99`, `run_manager.py:179,190`, `streaming.py`); enforce upload size + magic-byte validation (`resume.py:50-66`); pass Tectonic `--untrusted` (shell-escape is off by default — verified — but `--untrusted` is the hardening) (`tools/tectonic_compile.py`); chmod project-root `.env` to 0600 (`config.py:99`); WS `Origin` check + run/session concurrency caps; drop `allow_credentials`/narrow CORS; reject alternate IP encodings (octal/decimal/IPv4-mapped-IPv6).

**Backend concurrency/perf (BE-04/08/10/11/12/13):** publish race (replay vs live append, no lock) `run_manager.py:255-258`; `cancel()` doesn't await the task `:127-136`; `resume_run` check-then-act TOCTOU `:79-101`; parse-job leak when client never connects `routers/resume.py`; blocking file/`httpx.get` I/O in async handlers (`settings.py:134`).

**AI-framework (AIF-04/07/08):** `StreamTranslator` couples to LangGraph internal event-dict shape → migrate UI to `astream(stream_mode=["updates","custom"])` or add a guard test (`api/streaming.py:134-176`); CLI path has no `recursion_limit` → `GraphRecursionError` risk under retries (`graph.py`/`cli.py` vs `run_manager.py:282`); ollama `format="json"` stacks with `with_structured_output` (`llm.py:91`).

**Build/release (OPS-02/04/07/08 + dist path):** version drift — 5 strings, 3 values (`pyproject 2.0.1` / `__init__ 0.2.1` / UI `v0.4.1` / `package.json 0.1.0`); **committed `Applicants for this job` PDF (28 KB) may contain applicant PII** → scrub from history; `playwright` as a prod dep needs `playwright install chromium`; installers never build the frontend; fragile `parents[3]` dist-path resolution breaks for wheel installs (`app.py:56`).

**Frontend/UX security-adjacent:** **hardcoded Anthropic API-key-prefix as a prefilled `defaultValue`** in Settings (secret-scanner bait, user-confusing) `screens.jsx:1645`; `postMessage('*')` from the tweaks panel `tweaks-panel.jsx:172`.

**UI/UX (RESP-01/02, A11Y-04/05/07/08/10/11, VISUAL-03):** no responsive breakpoints (Dashboard/NewRun 2-col, LiveRun 3-col) → WCAG 1.4.10 reflow fails; `<div role=button>` sidebar pill, zoom-out icon mismatch (`name="x"`), timeline node buttons lack `aria-pressed`/label, empty-label Toggle, JS-mutated focus rings invisible in high-contrast, table-row `onClick` keyboard-inaccessible; `--sidebar-w`/`--topbar-h` CSS vars appear **undefined** in `styles.css` (verify they aren't injected elsewhere).

---

## P3 — Low / polish

Remaining a11y (decorative-dot labels, color-only status, command-palette `setTimeout` focus, skills tag input label, iframe wrapper landmark); contrast audit of `--text-muted`/`--text-faint` and accent/contrast pairs; toast auto-dismiss + progress; false-affordance chevrons & dead nav (`FLOW-02/06/07/08` — history/new-run rows navigate to the *simulation*, not the run); `health` returns `{"ok":"true"}` (string); `resume_run` 404/409 error-class coupling (BE-15); leftover design-tool harness (~250 LOC) in `tweaks-panel.jsx`; WS reconnect backoff has no jitter (thundering herd); checkpointer dual sync/async path on one DB file (BE-12/AIF-12); dead imports (`RECENT_RUNS`/`RESUME`/`JD_TEXT`) and `mock-data.jsx` pure re-export; `requires-python <3.14` upper bound; missing `[project.urls]`; **opt-in Langfuse (self-host) tracing** — high payoff for debugging the retry loop (AIF observability rec).

---

## Cross-cutting themes

1. **"Finish the wiring" is one workstream.** Most Frontend/UX/Flow findings share a single root cause: the web UI is a polished prototype only partially connected to the real API. Decide explicitly — finish the integration, or clearly label/gate demo mode — rather than fixing symptoms one by one.
2. **The FastAPI layer carries the most concentrated risk** (security + async correctness + zero tests). It should get the most hardening and the first new test suite.
3. **Repo/release hygiene is a cluster of cheap structural wins** (untracked code, no CI, broken test collection, dual dev-groups, version drift) — fixing these unblocks everything else and stops regressions.

## Verified environment facts (as of 2026-05-31)
- `npm audit`: **0 vulnerabilities**. `pip-audit`: **8 CVEs across 7 packages** (table in P1-3).
- Test suite: **166 passed, 2 collection errors, 2 failures** via `uv run pytest`.
- Repo hygiene: root `.env` is **not tracked** (only `.env.example`) — good; but it's mode 0644 (P2).
- `gemini-2.0-flash` retires **2026-06-01**; `gpt-4o` retired in ChatGPT (still API-available, dated); current Claude Opus is `claude-opus-4-8`.

# Issue Page — Resume Generator (backend + frontend audit)

> **Purpose:** Single tracker of every problem found while walking the backend
> (`src/resume_agent/api`) and the React frontend (`Frontend/`), and while
> clicking through every screen of the live UI.
>
> **Status:** ✅ *Fixed — 2026-06-17.* All issues below have been addressed in
> code (backend + frontend). See the **Resolution** section right below the
> TL;DR for the per-issue summary, verification, and the one operational note
> (restart the FastAPI backend so the D1 change takes effect on the live server).
>
> **How it was tested**
> - FastAPI backend on `127.0.0.1:8000` with your real data: provider **Ollama**
>   (`nemotron-3-super` / vision `gemma4:31b`, base URL `https://ollama.com`),
>   real base resume (Aldrin Joseph / CogniCor), and 2 runs in history
>   (GE Healthcare = complete + PDF, NVIDIA = failed).
> - Vite dev server on `127.0.0.1:5173` proxying `/api` + `/ws` → backend.
> - Every nav item, tab, and button clicked. Live-run states driven through the
>   built-in snapshot tool. A real end-to-end generation was **not** triggered
>   (see N7) — it invokes a long real LLM run.
>
> **Severity:** 🔴 high (broken/misleading core function) · 🟠 medium (feature
> non-functional but contained) · 🟡 low (cosmetic/polish).
> **Status values:** `open` → `reviewed` → `fixing` → `fixed`.

---

## TL;DR

The backend is real and basically sound. The **frontend is a Claude-generated
prototype that is only partly wired to it**: a handful of read paths are live
(settings/runs/history/resume load, connection test), but most *write* paths and
several *navigation* paths are mock/simulated or dead. The single biggest theme:
**6 API functions exist but are never called**, so Save / Upload / Cancel /
Doctor / provider-catalogue all look functional but do nothing.

---

## ✅ Resolution (2026-06-17)

All items are fixed. Verified: `npm run build` (Frontend) is clean, `uv run
pytest` is green (203 passed), and the running app was walked screen-by-screen
in the preview (Dashboard/Settings/Base resume/Setup all render with real data;
Settings shows the real `nemotron-3-super` model and `https://ollama.com` base
URL — see the verification screenshot in the chat).

**Backend**
- **D1** `/api/resume/raw` now returns `PlainTextResponse` → the YAML tab renders
  real text. ⚠️ *Restart the FastAPI server* — a backend process started before
  this change still serves the old JSON-encoded body, so the YAML tab keeps
  showing the escaped one-liner until it restarts.
- `SettingsUpdate` extended with `generator_max`, `compile_timeout_seconds`,
  `scrape_timeout_seconds`, `output_dir`, `enable_hr_review`, plus real
  `vision_enabled` handling, so the Settings page can actually persist them.

**Wiring (A1–A6) — all six functions now called**
- A1 `updateSettings` — Settings has a **Save changes** button.
- A2 `updateResume` — Base-resume editor is controlled with a real **Save**; the
  false "autosaves on blur / Saved" labels are replaced with honest state
  (Unsaved / Saving / Saved / Error).
- A3 `uploadResume` — Replace + Setup step 5 use a real `<input type=file>` +
  drag-drop; parsing is driven by the real `/ws/resume-parse/{job_id}` socket.
- A4 `getProviders` — provider/model catalogue is fetched (`useProviders`).
- A5 `runDoctor` — used by the Dashboard card, top-bar pill, Settings, and Setup.
- A6 `cancelRun` — the live-run **Cancel run** button is wired.

**Data mismatches (B1–B5)** — B1 every surface (dashboard rows, history rows,
new-run cards, notifications, ⌘K "Open last run") passes the real thread id via
`openRun`; B2 the configured model is fetched and always kept selectable
(`withCurrent`); B3 `hr_review` added to `PIPELINE_NODES`, "14 nodes" is now
dynamic; B4 doctor is real everywhere; B5 base URL is bound to state.

**Screens (C1–C10)** — C1 responsive `@media` rules added; C2 Generate disabled
on empty input, URL mock + dead "Fetch preview" removed, stale error cleared on
tab switch; C3 Save + section-nav scroll + add-bullet/add-role/add-education;
C4 filter + range tabs + download wired, date bug fixed; C5/C6 full Settings +
Setup wiring; C7 real run header + cancel, playback gated to demo; C8 ⌘K uses
the most-recent run; C9 notifications derived from real runs; C10 theme/accent/
density now controllable from **Settings → Appearance**.

**Intentionally deferred (low value / no backend endpoint, called out so they
aren't mistaken for misses):**
- Settings "Reset all state" + "Open folder" and New-run "Auto-accept
  suggestions" / per-run "Skip HR review" were **removed** rather than left as
  dead controls — they have no backend endpoint (a browser can't open an OS
  folder; there's no reset/destructive route). Re-add once endpoints exist.
- Base-resume **Projects** and **Skills** remain display-only (their values are
  preserved on Save); inline add/remove of projects and skill chips is the
  remaining 🟡 polish.
- D2 (chatty polling) — the run poll is now centralized in `App`, but a shared
  cache/backoff across the remaining `useRuns`/`useSettings` hooks is left as-is.

---

## A. Wiring gaps — API client functions imported but never called

A repo-wide search (`Frontend/src`) shows **zero call sites** for each of these
(all defined in `api/client.js`). Each maps to a feature that appears to work.

| ID | Sev | Function | What's broken | Status |
|----|-----|----------|---------------|--------|
| A1 | 🔴 | `updateSettings` | Settings page has **no Save**. Provider/model/vision/retries/timeouts/output-dir never persist. | fixed |
| A2 | 🔴 | `updateResume` | Base-resume editor has **no Save**; the "autosaves on blur" label is false. Every edit is lost. | fixed |
| A3 | 🔴 | `uploadResume` | Resume upload (Setup step 5 + "Replace") never hits the backend; parsing is a fake timer animation. | fixed |
| A4 | 🟠 | `getProviders` | Provider/model catalogue is hardcoded in `data.jsx` instead of fetched, so it can't match real models (→ B2). | fixed |
| A5 | 🟠 | `runDoctor` | Doctor status is never actually checked anywhere (→ B4). | fixed |
| A6 | 🟠 | `cancelRun` | The live-run header "Cancel run" button has **no `onClick`**. | fixed |

---

## B. Backend ↔ frontend data mismatches

- **B1 — 🔴 Opening a run from most places loses the thread id → shows a fake demo run.**
  `setSelectedRunId` is only called from `openRun` (app.jsx:955). The Dashboard
  "Recent runs" rows, **all History rows**, the New-run sidebar cards, the
  notification items, and the command-palette "Open last run" all call
  `goto("run")` with **no id**. With `threadId == null`, `LiveRunView` renders
  the **demo simulation** (fake pipeline + fake "Aldrin Carlos / Acme Corp" PDF),
  not the real run. *Verified:* clicking the completed **GE Healthcare** run
  opened a generic run titled **"Unknown · Unknown"**, thread `thr_8af2c01d`,
  "via claude-sonnet-4-6 · offline" (WS never connected). History rows don't even
  set the run-state snapshot, so a *complete* run displays as *Running*.

- **B2 — 🟠 Settings never shows the actually-configured model.**
  Backend reports `nemotron-3-super` / `gemma4:31b`; these aren't in the
  hardcoded `PROVIDER_MODELS.ollama_local` / `PROVIDER_VISION_MODELS.ollama_local`
  (`data.jsx`). `SettingsView`'s `useEffect` then resets the selection to the
  first list entry. *Verified:* the summary card says `nemotron-3-super` but the
  model grid right below highlights `llama3.2` — a contradiction on one page.

- **B3 — 🟠 Pipeline node-count mismatch (16 backend vs 14 frontend).**
  `streaming.py:PIPELINE_NODE_IDS` has 16 nodes incl. `hr_review` and
  `terminal_failure`; `data.jsx:PIPELINE_NODES` has 14 and omits both.
  `computeEventsFromApi` does `findIndex(... === node_id)` → `-1` for those, so
  their events are silently dropped from the live timeline. Left rail also
  hardcodes the label **"14 nodes"**.

- **B4 — 🟠 Doctor health is faked everywhere.**
  TopBar "Doctor ok/issue" pill is driven only by the dev-panel toggle; the
  Dashboard Workspace card hardcodes "all checks passing"; Setup step 4 hardcodes
  Tectonic/Poppler/write-access as `ok: true`. None call `runDoctor`, so a broken
  environment still shows green.

- **B5 — 🟠 Settings "Base URL" is hardcoded.**
  Field shows `http://localhost:11434` via a literal `defaultValue`, but the real
  configured base URL is `https://ollama.com`. "GET /api/tags → 4 models detected"
  is also hardcoded text.

---

## C. Screen-by-screen findings

### C1 · Dashboard
- **🟠 No responsive layout at all** — `styles.css` has **0 `@media` queries**;
  all layouts are fixed inline grids. Below ~1100px the `minmax(0,1fr) 320px`
  grid crushes the hero so the headline wraps one word per line (verified at
  800px). Same risk on New-run and the live-run 3-column grid.
- **🟡 Hardcoded KPI trend chips** — "+5 / +3 / −1 from last month" are literal
  constants in `screens.jsx`, not computed.
- **🟡 Doctor card** always green (→ B4).
- **🟡 Activity chart empty** — expected, since the 2 runs fall outside the
  14-day window relative to today; only flagging in case it should backfill.

### C2 · New run
- **🟠 "Generate resume" is enabled with an empty textarea** → POSTs and the
  backend returns **422**; the **raw pydantic string** *"Value error, Provide
  jd_text, jd_url, or jd_file_id."* is shown to the user. (Verified via network.)
- **🟠 "From URL" preview is a hardcoded mock** — the "FETCHED · 2s / Senior
  Software Engineer — TechCorp / jobs.techcorp.io …" card is always shown
  regardless of the (empty) URL, and **"Fetch preview" has no handler**.
- **🟡 Advanced options** ("Skip HR review", "Auto-accept suggestions") are
  no-ops (`onChange => {}`) and are never sent to `createRun`.
- **🟡 Stale error persists** when switching tabs (the 422 message stayed
  visible after switching to the URL tab).

### C3 · Base resume
- Loads **real data** ✓ (`getResume`).
- **🔴 No Save** (→ A2); header says *"Last saved 2 minutes ago · autosaves on
  blur"* and shows a green "Saved" badge — both false.
- **🔴 YAML tab is broken** — shows the file as a JSON-escaped one-liner
  (`"certifications:\n- date: null\n …"`). Root cause is backend **D1**.
- **🟠 "Replace" upload is fully simulated** (→ A3): the dropzone is a `<button>`
  (no real `<input type=file>`/drop), clicking it runs a fake parse with a
  hardcoded filename **`aldrin_carlos_resume.pdf`** and a stage label
  **`claude-sonnet-4-6`** (wrong — provider is Ollama). On finish it claims
  *"Resume parsed and saved to base_resume.yaml"* though nothing was saved.
- **🟡 Section nav** (Profile/Experience/…/Links) buttons have no handler — they
  don't scroll/jump anywhere.
- **🟡 Add role / Add project / Add bullet / trash / skill-chip remove** all have
  no handlers.

### C4 · History
- Loads **real grouped data** ✓.
- **🔴 Row click → demo run** (→ B1).
- **🟠 Filter input + All/7d/30d tabs are non-functional** (`onChange => {}`).
- **🟠 Row action icons** (download / re-run / more) have no handlers.
- **🟡 "most recent · {date}"** uses `runs[0].date.split(" · ")[0]`, which won't
  contain " · " for API-derived `toLocaleString()` dates, so it prints the full
  timestamp.

### C5 · Settings
- Summary card + "Re-test" are **real** ✓ (`getSettings`, `testConnection`).
  Verified Re-test → `{ok:true, latency_ms:2734, reply:"OK"}`.
- **🔴 No Save anywhere** (→ A1) — provider picker, model grids, vision toggle,
  pipeline toggles, retries (5/180/30, hardcoded), output dir all dead.
- **🟠 Model grid can't show the real model** (→ B2); **Base URL hardcoded** (→ B5).
- **🟡 API-key field** shows a fake hardcoded `sk-ant-api03-…` value.
- **🟡 "Open folder"** and **"Reset all state"** (Danger zone) have no handlers.

### C6 · Setup wizard
- **🟠 Always defaults to Anthropic**, ignoring the real configured provider (Ollama).
- **🟠 "Test key" is fake** — only checks `apiKey.length > 8`.
- **🟠 Step-4 doctor rows are hardcoded `ok:true`** (→ B4); the LLM connection
  test on that step is real ✓.
- **🟠 Step-5 upload is simulated** (→ A3); completing the wizard persists nothing
  (no `updateSettings`).

### C7 · Live run
- All five states render ✓ (running / ask-missing / suggestions / complete /
  failed) — HITL forms, word-level suggestion diffs, lint, retry list.
- **🔴 Real runs unreachable from normal navigation** (→ B1); the playback
  rewind/play/forward controls only drive the **demo simulation**.
- **🟠 Dead action buttons:** "Cancel run" (→ A6), "Try again", "Edit base
  resume", "Open debug artifacts", "Copy path", PDF prev/next-page.
- **🟡 Mock header leakage on every run:** thread `thr_8af2c01d`, "started
  2:21 PM", "via claude-sonnet-4-6" (uses the `ACTIVE_LLM` constant, not real
  settings), company "Unknown".
- **🟡 Node mismatch / "14 nodes" hardcoded** (→ B3). Failed-state debug path is
  a hardcoded mock (`/output/_failed/20260517_142903`).

### C8 · Command palette (⌘K)
- Opens & filters ✓.
- **🟠 "Open last run" shows "NVIDIA · undefined"** — uses `lastRun.date` (API
  objects only have `created_at`) and picks `items[items.length-1]` (the
  *oldest* run, not the most recent). Selecting it also hits B1.
- **🟡 Displayed ⌘N / ⌘B / ⌘, shortcuts are decorative** — only ⌘K (and Esc) are
  wired in the global key handler.

### C9 · Notifications
- **🟠 Permanently empty / dead.** State initializes to `[]`; `NOTIFICATIONS_SEED`
  is defined but never used; nothing (incl. the WS layer) ever feeds it. The bell
  never shows a count and the demo HITL toast never fires.

### C10 · Theme / dev (Tweaks) panel
- **🟠 The Tweaks panel is unreachable in the real app** — it only opens on a host
  `postMessage({type:'__activate_edit_mode'})` (Claude's visual-edit harness).
  Since **theme (light/dark), accent, and density are *only* controllable there**,
  a normal user is permanently locked to light / emerald / comfortable.
- Dark mode itself renders correctly when forced ✓ (so it's purely an access gap).

---

## D. Backend findings

- **D1 — 🟠 `/api/resume/raw` returns a JSON-encoded string, not text.**
  The handler is annotated `-> str`, so FastAPI serializes it as JSON with
  `content-type: application/json` (verified: body begins `"certifications:\n…"`).
  The frontend renders that escaped blob → the broken YAML tab (C3). Fix is to
  return `PlainTextResponse` (or `media_type="text/plain"`).
- **D2 — 🟡 Chatty polling.** `useRuns` polls `GET /api/runs` every 5s and is
  instantiated independently in Dashboard, New-run, and History; `getSettings` /
  `getResume` are also fetched several times per load. No backoff or shared cache.

---

## N. Notes / what actually works (not issues)

- **N1** Backend boots cleanly and serves real `/api/settings`, `/api/runs`,
  `/api/runs/{id}`, `/api/resume`, history, and PDF endpoints.
- **N2** Connection test (`/api/settings/test-connection`) genuinely round-trips
  to your Ollama provider (`ok:true`, ~2.7s, reply "OK").
- **N3** Base-resume **Form** view and Dashboard/History load real data correctly.
- **N4** Loopback security guard, SPA fallback containment, and the WS
  replay-then-live subscription logic look correct on code review.
- **N5** Dark mode + all live-run UI surfaces are visually complete.
- **N6** Console is clean at runtime (only Vite HMR + React-devtools notices); no
  JS errors observed during the whole walkthrough.
- **N7** **Not exercised:** a real end-to-end generation (`createRun` → WS stream
  → live timeline → PDF). The wiring is present and looks correct, but a run was
  not started to avoid a long real LLM pipeline (your last real run took ~17 min)
  that can't be stopped from the UI (A6). Recommend one manual happy-path run
  once the above are addressed.

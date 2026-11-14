# Resume Generator

[![CI](https://github.com/ALDRIN121/resume-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/ALDRIN121/resume-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A local resume and job-search workflow with source-bound proposals, explicit content review and approval of the exact PDF bytes.

**Local candidate:** These upgrades are prepared in the current checkout and have not been pushed or published. See the [implementation status](docs/superpowers/plans/2026-11-13-r1-implementation-status.md). Public installers follow the published repository branch; they cannot install unpushed changes.

```
 ██████╗ ███████╗███████╗██╗   ██╗███╗   ███╗███████╗
 ██╔══██╗██╔════╝██╔════╝██║   ██║████╗ ████║██╔════╝
 ██████╔╝█████╗  ███████╗██║   ██║██╔████╔██║█████╗
 ██╔══██╗██╔══╝  ╚════██║██║   ██║██║╚██╔╝██║██╔══╝
 ██║  ██║███████╗███████║╚██████╔╝██║ ╚═╝ ██║███████╗
 ╚═╝  ╚═╝╚══════╝╚══════╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝
       G E N E R A T O R
```

---

## What it does

1. Import a text-based PDF or TEX source into a reviewable profile draft.
2. Save the complete job description as a fixed input.
3. Review evidence questions and source-bound wording proposals.
4. Choose changes, then inspect the complete content projection and omissions.
5. Review the exact compiled PDF before release.
6. Retain accepted memory, evaluate chosen roles, and record explicit application events when desired.

Use the local web app, interactive CLI or [agent JSON interface](docs/agent-json.md). State and PDFs stay on the local filesystem. Configured-provider mode sends required profile, posting, answer and accepted-rule text to the chosen provider. Local Ollama can perform model work locally. External-agent mode returns model requests to the calling agent and makes no configured-backend model calls.

Discovery reads only configured public Greenhouse, Lever and Ashby boards. Refresh is manual. Partial or failed scans preserve earlier jobs. Generating a PDF does not record a submission. Evidence scores are product-default advice, not hiring probabilities.

See [agent installation and tested hosts](docs/agent-hosts.md) and the [fictional demonstration](docs/demo.md).

---

## Get started in one line

Paste one command. It installs everything and opens the app in your browser.

**Mac / Linux:**
```bash
curl -sSL https://raw.githubusercontent.com/ALDRIN121/resume-agent/main/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/ALDRIN121/resume-agent/main/install.ps1 | iex
```

That single command:
1. Installs `uv` (a Python package manager) if you don't already have it — `uv` also manages the right Python version for you, so there's nothing else to install there.
2. Clones the repo and installs the `resume-generator` CLI.
3. Installs **Tectonic** and **Poppler** (the PDF tools) automatically for your OS.
4. Opens the web UI at **http://127.0.0.1:8000**, where you pick an AI provider and paste your API key on the Settings page.

The only thing you need beforehand is **Git** ([git-scm.com/downloads](https://git-scm.com/downloads)). Prefer the terminal instead of the browser? See the [Quickstart](#quickstart) below. Want to see every step, or install without the script? See [Manual installation & requirements](#manual-installation--requirements).

---

## Updating

When new code is pushed to GitHub, pull it in with one command:

```bash
resume-generator update
```

This pulls the latest changes from GitHub and reinstalls the CLI. If you're already on the latest version, it tells you so. Re-running the one-liner above does the same thing — it detects the existing install and updates it in place instead of cloning again.

If the web UI is running, stop it (Ctrl+C) and run `resume-generator serve` again afterwards to pick up the update.

Run `resume-generator doctor` once the update finishes to confirm everything still works.

> **Windows:** if the update reports the CLI executable is locked, open a **new** terminal window, `cd` into the install directory it prints, and run `uv tool install . --force`.

---

## Quickstart

This is the CLI-driven flow. If you used the one-liner above, the web UI is already open in your browser — configure your provider and generate resumes there instead, and skip straight to [First-time setup in detail](#first-time-setup-in-detail) if you just need the provider/API-key steps.

### Mac / Linux

```bash
# 1. First-time setup: choose your AI provider and enter your API key
resume-generator setup

# 2. Check everything is working
resume-generator doctor

# 3. Parse your existing resume (one-time step)
resume-generator init --source path/to/your_resume.tex
# or if you only have a PDF:
resume-generator init --source path/to/your_resume.pdf

# 4. Generate a tailored resume from a text file
resume-generator generate --jd-file job_description.txt
# or paste a job listing URL:
resume-generator generate --jd-url "https://jobs.example.com/senior-engineer"
```

### Windows PowerShell

```powershell
# 1. First-time setup: choose your AI provider and enter your API key
resume-generator setup

# 2. Check everything is working
resume-generator doctor

# 3. Parse your existing resume (one-time step)
resume-generator init --source C:\Users\you\Documents\resume.pdf

# 4. Generate a tailored resume from a text file
resume-generator generate --jd-file C:\Users\you\Documents\job_description.txt
# or paste a job listing URL:
resume-generator generate --jd-url "https://jobs.example.com/senior-engineer"
```

The released PDF is saved under the configured output directory after content and PDF review.

---

## First-time setup in detail

### Getting an AI provider API key

The tool needs to call an AI model. Pick one:

| Provider | Cost | Where to get a key |
|----------|------|--------------------|
| **Google Gemini** | Provider pricing and limits apply | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **NVIDIA NIM** | Provider pricing and limits apply | [build.nvidia.com](https://build.nvidia.com) |
| **Anthropic Claude** | Paid | [console.anthropic.com](https://console.anthropic.com) |
| **Command Code** | API access | [commandcode.ai/studio/api-keys](https://commandcode.ai/studio/api-keys) |
| **OpenAI GPT** | Paid | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| **Ollama** | Local compute; no cloud API key required | [ollama.com](https://ollama.com) — no key needed for local |

### Running the setup wizard

Run the setup wizard once. It will walk you through picking a provider and entering your API key:

```bash
resume-generator setup
```

The wizard asks you to:
1. Pick your AI provider (arrow keys).
2. Enter your API key (hidden as you type).
3. Pick a text model (sensible default is pre-selected).
4. Run the local readiness checks. The reviewed workflow uses deterministic PDF checks and human review.

Settings are saved to `~/.resume_generator/config.yaml`. Your API key is stored separately in `~/.resume_generator/.env` (chmod 600 on Mac/Linux).

You can also run `resume-generator` with no arguments. On a fresh install, it launches the same first-time setup flow, then asks for your resume and job description interactively.

> **Pasting a job description in interactive mode?** After pasting, press **Enter three times** on a blank line to finish — or press **Ctrl+D** for a quicker exit. Either works.

---

## All commands

```
resume-generator                           # Interactive mode (first run = setup wizard)
resume-generator setup                    # Re-run the setup wizard
resume-generator init --source <file>     # Parse your resume (one-time)
resume-generator generate --jd-file <file>  # Generate from a job description file
resume-generator generate --jd-text "…"     # Generate from pasted text
resume-generator generate --jd-url <url>    # Generate from a job listing URL
resume-generator resume <thread-id>       # Resume an interrupted session
resume-generator config show              # Show current settings
resume-generator config set provider openai
resume-generator doctor                   # Check tools and API keys
resume-generator install-deps             # Auto-install Tectonic and Poppler
resume-generator serve                    # Launch the local web UI (FastAPI + React)
resume-generator update                   # Pull latest version from GitHub
resume-generator jobs --help              # Save roles and preserve selected snapshots
resume-generator memory --help            # Propose and review durable corrections
resume-generator discover --help          # Configure and manually scan public boards
resume-generator applications --help      # Record local application events
resume-generator agent --help             # Non-interactive JSON commands
resume-generator skill export --destination PATH
```

### Overriding the AI model for one run

```bash
resume-generator generate --jd-url <url> --provider openai --model YOUR_MODEL_ID
resume-generator generate --jd-url <url> --provider anthropic --model YOUR_MODEL_ID
resume-generator generate --jd-url <url> --provider nvidia --model YOUR_MODEL_ID
```

---

## Web UI (optional)

Prefer a browser to the terminal? Launch the bundled local web app:

```bash
resume-generator serve            # serves on http://127.0.0.1:8000
resume-generator serve --port 9000
```

If you installed with the one-liner, this already ran automatically and a browser tab should have opened for you.

It runs a FastAPI backend plus a pre-built React frontend entirely on your machine — there is no hosted service and no telemetry. The UI covers the same flow as the CLI: configure your provider, upload/parse a base resume, paste or upload a job description (`.txt`/`.pdf`), watch the pipeline stream live (with the human-in-the-loop questions and suggestion review inline), and download the generated PDF. A dashboard tracks runs per company, and appearance (theme/accent/density) is remembered across reloads.

Notes:
- Bind address defaults to loopback (`127.0.0.1`). Because the app ships no login, state-changing requests and WebSocket connections are only accepted from loopback — a deliberate guard against malicious web pages or DNS-rebinding driving your local API.
- `--reload` is for frontend/static development only; it restarts the worker and drops in-flight runs (run state is in-memory).
- The frontend is pre-built and committed under `Frontend/dist/`. To develop the UI itself, see [Development](#development).

---

## Configuration

Config file: `~/.resume_generator/config.yaml`

```yaml
provider: gemini
model:
  default: gemini-2.5-flash     # Text model for writing and analysis
  vision: YOUR_MODEL_ID         # Legacy optional setting; reviewed v2 uses deterministic PDF checks
scraping:
  playwright_fallback: true     # Use a full browser for JS-heavy sites (e.g. LinkedIn)
latex:
  tectonic_path: tectonic
  compile_timeout_seconds: 180  # Increase if Tectonic times out (first run on Windows can be slow)
output:
  base_dir: ./output
retries:
  generator_max: 5              # How many times to retry if LaTeX compilation fails
```

API keys go in environment variables or `~/.resume_generator/.env`:
- `COMMAND_CODE_API_KEY` (provider: `commandcode`, model: `deepseek/deepseek-v4.1-flash`)
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GOOGLE_API_KEY`
- `NVIDIA_API_KEY`
- `OLLAMA_API_KEY` (required for remote/cloud Ollama endpoints; optional for local)
- `OLLAMA_BASE_URL` (default: `http://localhost:11434`)
- `NVIDIA_BASE_URL` (leave blank for NVIDIA cloud; set for self-hosted NIM)

Environment overrides (useful for CI or scripting):
- `RESUME_GENERATOR_PROVIDER=anthropic`
- `RESUME_GENERATOR_MODEL__DEFAULT=claude-sonnet-4-6`
- `RESUME_GENERATOR_RETRIES__GENERATOR_MAX=5`

---

## How the question-and-answer step works

When the AI finds a requirement in the job description that isn't documented in your resume (but might be in your background), it pauses and asks you directly:

```
╭── Human Input Needed ───────────────────────────────────────╮
│  Q1: Have you participated in on-call rotations?             │
│  Why: The JD requires on-call ownership of services          │
│                                                              │
│  Your answer: Yes, 2-week rotations at Acme, PagerDuty      │
╰─────────────────────────────────────────────────────────────╯
```

Answers become fixed evidence for proposals. Source references and selected changes are validated. You must still compare facts with the original source; schema validity does not prove a claim true.

If you press Ctrl-C mid-session, your progress is automatically saved. Resume with:

```bash
resume-generator resume <thread-id>
```

The thread ID is printed at the start of each generation run.

---

## How the suggestion review step works

Proposals show their target, before/after text and source references. All proposals start unselected. Appends require explicit answer or user-text evidence. Unsupported paths, stale hashes and invalid references fail validation.

Choose the changes you want. Review the complete projection, including omitted display fields, before confirmation. The renderer uses that approved snapshot. It does not ask a model to rewrite approved text or repair factual content.

After compilation, inspect the exact preview PDF. Approval binds its current review ID, content hash, render hash and PDF hash. Changed bytes invalidate that approval.

---

## Output

Released files go under the configured output directory. Filenames are reserved without overwriting an existing file. The released bytes match the approved canonical PDF.

Canonical sources, attempts, logs and reviews stay under the application state directory. The default is `~/.resume_generator/`. Set `RESUME_GENERATOR_STATE_DIR` before imports to use isolated state.

Interrupted work requires explicit recovery. Reexport copies previously approved canonical bytes and retains the original release record. Missing artifacts remain visibly missing.

---

## How the pipeline works (for the curious)

1. Freeze the complete job, reviewed profile and accepted memory.
2. Extract role metadata and collect confirmed answers.
3. Validate structured proposals against their fixed sources.
4. Apply only explicitly selected changes.
5. Freeze the complete approved display manifest.
6. Render a fixed template and compile it with Tectonic.
7. Check extracted PDF content, pages and layout limits.
8. Show the exact PDF for a separate human decision.
9. Export those approved bytes atomically.

Standard and compact layouts keep approved text intact. Layout failure stops with remedies. Optional HR advice cannot rewrite content. Host mode disables optional HR and vision calls.

Configured-provider and external-agent modes share this workflow. The latter pauses at durable model requests instead of calling the backend.

---

## Troubleshooting

**`resume-generator: command not found`**
- Mac/Linux: make sure `~/.local/bin` is in your PATH.
- Windows: make sure `%APPDATA%\uv\bin` is in your PATH (the installer prints the exact command to fix this).
- Try closing and reopening your terminal after updating PATH.
- Or run it directly:
  - Mac/Linux: `~/.local/bin/resume-generator`
  - Windows PowerShell: `& "$env:APPDATA\uv\bin\resume-generator.exe"`

**`tectonic: command not found` or `pdftoppm: command not found`**
- Run `resume-generator install-deps` to install automatically.
- Or install manually — see the Requirements section above.

**`Authentication Failed` or `401 Unauthorized`**
- Your API key is wrong or expired.
- Run `resume-generator setup` to re-enter it.

**`Ollama: Unauthorized (401)`**
- Your Ollama server requires an API key.
- Run `resume-generator setup` and enter your API key when prompted — it will be saved automatically.
- Or set it manually before running the tool:
  - Mac/Linux: `export OLLAMA_API_KEY=<your-key>`
  - Windows PowerShell: `$env:OLLAMA_API_KEY="<your-key>"`

**`No base resume found`**
- You haven't run `init` yet.
- Run: `resume-generator init --source path/to/your_resume.tex`

**The PDF looks bad (text overflow, wrong layout)**
- The deterministic content/layout checks stop invalid output. Review the diagnostics and choose content or layout remedies.
- If it keeps failing, try a stronger model: `--provider anthropic --model YOUR_MODEL_ID`

**Job description gets cut off when pasting on macOS**
- This was a known issue with libedit's ~1024-byte per-line buffer — fixed in v2.0.1.
- Update to the latest version: `resume-generator update`

**LinkedIn / Greenhouse job URLs don't scrape properly**
- These sites require JavaScript rendering.
- Make sure `scraping.playwright_fallback: true` is set in your config.
- Run `uv tool run --from playwright playwright install chromium` once after installation.

---

## Manual installation & requirements

Prefer to see every step, or need to install without the one-liner (e.g. no internet access to raw.githubusercontent.com)? Here's what it does under the hood, plus the underlying requirements.

If the `update` command can't find the repo (e.g., you moved the install folder), re-run the one-liner installer instead — it will pull the latest code and reinstall in one step.

### Requirements

| What | Why you need it | How to install |
|------|----------------|----------------|
| **Python 3.12 or 3.13** | Runs the tool | [python.org/downloads](https://python.org/downloads) |
| **Git** | Downloads and updates the project | [git-scm.com/downloads](https://git-scm.com/downloads) |
| **uv** | Installs the CLI and Python dependencies | The installer adds it automatically if missing |
| **Tectonic** | Converts the resume to PDF (a LaTeX compiler) | See below |
| **Poppler** | Extracts PDF text and renders pages for checks and review | See below |

Configured-provider mode needs the chosen provider's credentials, unless you use local Ollama. External-agent mode needs no backend key. Host subscription or API charges can still apply. Check provider terms directly; no universal free allowance is promised.

Local macOS acceptance has passed. Linux and native Windows CI are configured but remain unverified for this candidate.

### Installing Tectonic and Poppler manually

**macOS:**
```bash
brew install tectonic poppler
```

**Ubuntu / Debian:**
```bash
sudo apt install tectonic poppler-utils
```

**Arch Linux:**
```bash
sudo pacman -S tectonic poppler
```

**Fedora / RHEL / CentOS:**
```bash
sudo dnf install tectonic poppler-utils
```

**Windows (via Scoop — recommended):**
```powershell
# Install Scoop first (if you don't have it):
irm get.scoop.sh | iex

# Then install both tools:
scoop install tectonic poppler
```

> **Tip:** `resume-generator install-deps` installs both automatically (the one-liner already runs this for you). Tectonic downloads font packages from the internet on its **first run** — this can take 2–5 minutes on Windows, which is normal. Subsequent runs are fast.

> **Note:** `winget install TectonicProject.Tectonic` is not available in the winget catalog — use Scoop instead.

### Manual installation (any OS)

```bash
# 1. Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh   # Mac/Linux
# Windows: irm https://astral.sh/uv/install.ps1 | iex

# 2. Clone the repo
git clone https://github.com/ALDRIN121/resume-agent.git
cd resume-agent

# 3. Install the CLI
uv tool install .
```

After installation, `resume-generator` should be available in your terminal. If not, add the uv tools directory to your PATH:

- **Mac/Linux:** `~/.local/bin`
- **Windows (PowerShell):**
  ```powershell
  $env:PATH += ";$env:APPDATA\uv\bin"
  [System.Environment]::SetEnvironmentVariable('PATH', "$env:PATH", 'User')
  ```
  Then open a new terminal.

---

## Architecture

| Component | Technology |
|-----------|-----------|
| Durable workflow | SQLite commands and ownership with LangGraph checkpoints |
| LLM providers | LiteLLM SDK via `langchain-litellm`: Anthropic · OpenAI · Gemini · NVIDIA NIM · Ollama · OpenRouter · Command Code |
| Structured output | Capability-aware function calling or schema-guided JSON, validated with Pydantic v2 |
| Scraping | httpx + readability-lxml → Playwright fallback |
| LaTeX → PDF | [Tectonic](https://tectonic-typesetting.github.io/) |
| PDF → images | pdf2image + Poppler |
| CLI | Typer + Rich |
| State checkpointing | LangGraph SqliteSaver (`~/.resume_generator/state.sqlite`) |
| Local web app | FastAPI + WebSockets backend · React (Vite) SPA |

---

## Exit codes

The non-interactive `agent` commands use this contract:

| Code | Meaning |
| --- | --- |
| 0 | Success or saved pause |
| 1 | Invalid input or unknown resource |
| 2 | Missing prerequisites |
| 3 | Execution failure |
| 4 | Conflict requiring current state inspection |

Interactive commands retain their own usage exits. An unfinished human review on closed stdin exits instead of prompting. See the [JSON protocol](docs/agent-json.md).

---

## Development

```bash
git clone https://github.com/ALDRIN121/resume-agent.git
cd resume-agent
uv sync                 # installs the dev dependency group by default

uv run pytest -q
uv run ruff check src/
```

Configured-provider calls use the shared LiteLLM adapter in `src/resume_agent/llm.py`.
External-agent mode instead returns durable model requests to the caller. No proxy server is required. Existing provider IDs, model names, API keys, and endpoint
settings continue to work. Models with tool support use non-strict function calling
so skill categories can keep arbitrary names. Other models receive the output schema
in the prompt, use JSON mode when supported, and are validated locally with Pydantic.
Unknown models use the same JSON prompt fallback. Capability checks use LiteLLM's
bundled catalogue so local Ollama use does not require downloading model metadata.

### Working on the web UI

The committed `Frontend/dist/` is what `resume-generator serve` ships. To change the UI, edit the sources and rebuild:

```bash
cd Frontend
npm ci
npm run dev             # hot-reload dev server (proxies the API)
npm run build           # rebuild Frontend/dist/ before committing
```

To add a new LaTeX template, copy `src/resume_agent/templates/default.tex.jinja` and update `config.yaml` to point to it.

---

## License

MIT — see [LICENSE](LICENSE).

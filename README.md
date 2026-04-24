# Resume Generator

An AI-powered CLI tool that reads a job description and your existing resume, then produces a professionally formatted, tailored PDF — ready to send.

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

1. You paste or link a job description.
2. The tool reads your resume and the job description, then identifies gaps and tailoring opportunities.
3. It asks you a few questions (only what it can't figure out on its own).
4. You approve or reject suggested rewrites to your bullet points.
5. A polished, job-specific PDF lands on your desktop.

No web UI. No uploading your resume to a third-party service. Everything runs locally on your machine.

---

## Requirements

Before installing, you need three things on your computer:

| What | Why you need it | How to install |
|------|----------------|----------------|
| **Python 3.12+** | Runs the tool | [python.org/downloads](https://python.org/downloads) |
| **Tectonic** | Converts the resume to PDF (a LaTeX compiler) | See below |
| **Poppler** | Reads PDF pages as images so the AI can check the layout | See below |

You also need an API key for at least one AI provider. The easiest free options are **Google Gemini** (no credit card) and **NVIDIA NIM** (free tier, no credit card).

### Installing Tectonic and Poppler

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

scoop install tectonic poppler
```

**Windows (via winget + manual):**
```powershell
winget install TectonicProject.Tectonic
# Poppler: download from https://github.com/oschwartz10612/poppler-windows/releases
# Extract and add the bin/ folder to your PATH
```

> **Don't want to do this manually?** Run `resume-generator install-deps` after installing the tool — it will try to install both automatically using whatever package manager you have.

---

## Installation

### Mac / Linux (one-liner)

```bash
curl -sSL https://raw.githubusercontent.com/ALDRIN121/resume-agent/main/install.sh | bash
```

This script: checks for `uv` (installs it if missing), clones the repo, and installs the `resume-generator` command.

### Windows (PowerShell one-liner)

```powershell
irm https://raw.githubusercontent.com/ALDRIN121/resume-agent/main/install.ps1 | iex
```

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

After installation, `resume-generator` should be available in your terminal. If not, make sure `~/.local/bin` (Mac/Linux) or `%APPDATA%\Python\Scripts` (Windows) is in your `PATH`.

---

## Quickstart

```bash
# 1. Check everything is working
resume-generator doctor

# 2. First-time setup: parse your existing resume (one-time step)
resume-generator init --source path/to/your_resume.tex
# or if you only have a PDF:
resume-generator init --source path/to/your_resume.pdf

# 3. Generate a tailored resume
resume-generator generate --jd-text "$(cat job_description.txt)"
# or paste a job listing URL:
resume-generator generate --jd-url "https://jobs.example.com/senior-engineer"
```

Your tailored PDF will be saved to `./output/<company>/` and opened automatically.

---

## First-time setup in detail

### Getting an AI provider API key

The tool needs to call an AI model. Pick one:

| Provider | Cost | Where to get a key |
|----------|------|--------------------|
| **Google Gemini** | Free tier available | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **NVIDIA NIM** | Free tier available | [build.nvidia.com](https://build.nvidia.com) |
| **Anthropic Claude** | Paid | [console.anthropic.com](https://console.anthropic.com) |
| **OpenAI GPT** | Paid | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| **Ollama** | Free, runs locally | [ollama.ai](https://ollama.ai) — no key needed |

### Running the setup wizard

Just run `resume-generator` with no arguments — it will walk you through picking a provider and entering your API key:

```bash
resume-generator
```

The wizard asks you to:
1. Pick your AI provider (arrow keys).
2. Enter your API key (hidden as you type).
3. Pick a text model (sensible default is pre-selected).
4. Optionally enable PDF layout validation (uses a vision model to check the final PDF looks right).

Settings are saved to `~/.resume_generator/config.yaml`. Your API key is stored separately in `~/.resume_generator/.env` (chmod 600 on Mac/Linux).

---

## All commands

```
resume-generator                           # Interactive mode (first run = setup wizard)
resume-generator setup                    # Re-run the setup wizard
resume-generator init --source <file>     # Parse your resume (one-time)
resume-generator generate --jd-text "…"  # Generate from pasted text
resume-generator generate --jd-url <url> # Generate from a job listing URL
resume-generator resume <thread-id>       # Resume an interrupted session
resume-generator config show              # Show current settings
resume-generator config set provider openai
resume-generator config set retries.generator_max 5
resume-generator doctor                   # Check tools and API keys
resume-generator install-deps             # Auto-install Tectonic and Poppler
resume-generator update                   # Pull latest version from GitHub
```

### Overriding the AI model for one run

```bash
resume-generator generate --jd-url <url> --provider openai --model gpt-4o
resume-generator generate --jd-url <url> --provider anthropic --model claude-sonnet-4-6
resume-generator generate --jd-url <url> --provider nvidia --model meta/llama-3.1-70b-instruct
```

---

## Configuration

Config file: `~/.resume_generator/config.yaml`

```yaml
provider: gemini
model:
  default: gemini-2.0-flash     # Text model for writing and analysis
  vision: gemini-2.0-flash      # Vision model for PDF layout checking
scraping:
  playwright_fallback: true     # Use a full browser for JS-heavy sites (e.g. LinkedIn)
latex:
  tectonic_path: tectonic
output:
  base_dir: ./output
retries:
  generator_max: 5              # How many times to retry if LaTeX compilation fails
```

API keys go in environment variables or `~/.resume_generator/.env`:
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GOOGLE_API_KEY`
- `NVIDIA_API_KEY`
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

Your answers are used to write more accurate bullet points. Nothing is fabricated — the tool only includes what you actually told it.

If you press Ctrl-C mid-session, your progress is automatically saved. Resume with:

```bash
resume-generator resume <thread-id>
```

The thread ID is printed at the start of each generation run.

---

## How the suggestion review step works

After the Q&A, the tool proposes rewrites to specific bullet points — adding keywords from the job description, quantifying achievements, etc. You review each one:

```
  Suggestion 1 of 4
  Original:  Built a data pipeline for ETL processing
  Suggested: Architected a high-throughput ETL pipeline processing 10M+ records/day,
             reducing data latency by 40% — aligned with their "real-time data" requirement

  [a]pprove  [s]kip  [q]uit reviewing
```

Only approved suggestions make it into the final resume. You stay in control.

---

## Output

```
./output/
└── techcorp/
    └── jane-doe_techcorp_2026-04-15.pdf
    └── jane-doe_techcorp_2026-04-15_v2.pdf   ← versioned if the file already exists
```

You're also prompted for a custom save location after each generation — press Enter to keep the default, or type a path.

Failed generations are saved for debugging:
```
./output/_failed/20260415_143022/
    resume.tex       ← last LaTeX attempt
    errors.txt       ← error log
```

---

## How the pipeline works (for the curious)

```
Input (text / URL)
    │
    ▼
[Scraper]       — httpx + readability → Playwright fallback for JS-heavy sites
    │
    ▼
[JD Extractor]  — LLM extracts: company, role, skills, keywords, requirements
    │
    ▼
[Resume Loader] — reads your base resume YAML (parsed once on init)
    │
    ▼
[Gap Analyzer]  — LLM cross-checks resume vs JD: matched skills, gaps, open questions
    │
    ├── (if questions) → [You answer questions] ← pauses and asks you
    │
    ▼
[Suggestion Presenter] ← pauses so you can approve/reject bullet rewrites
    │
    ▼
[Resume Generator] — Jinja2 template + LLM writing → LaTeX source
    │
    ▼
[LaTeX Validator]  — checks brace/environment balance
    │
    ├── (fail) ──► retry Generator (up to 5 times)
    ▼
[PDF Compiler]     — Tectonic compiles LaTeX to PDF
    │
    ├── (fail) ──► retry Generator
    ▼
[PDF → Images]     — Poppler renders each page as PNG
    │
    ▼
[Vision Validator] — Vision LLM checks layout, overflow, spacing
    │
    ├── (issues) ──► retry Generator with fix instructions
    ▼
[Output]           — PDF saved to ./output/<company>/
```

---

## Troubleshooting

**`resume-generator: command not found`**
- Make sure `~/.local/bin` (Mac/Linux) or `%APPDATA%\Python\Scripts` (Windows) is in your PATH.
- Try closing and reopening your terminal.
- Or run directly: `uv run resume-generator`

**`tectonic: command not found` or `pdftoppm: command not found`**
- Run `resume-generator install-deps` to install automatically.
- Or install manually — see the Requirements section above.

**`Authentication Failed` or `401 Unauthorized`**
- Your API key is wrong or expired.
- Run `resume-generator setup` to re-enter it.

**`Ollama: Unauthorized (401)`**
- Your Ollama server requires an API key.
- Run: `export OLLAMA_API_KEY=<your-key>` before running the tool.

**`No base resume found`**
- You haven't run `init` yet.
- Run: `resume-generator init --source path/to/your_resume.tex`

**The PDF looks bad (text overflow, wrong layout)**
- The vision validator should catch this and retry automatically.
- If it keeps failing, try a stronger model: `--provider anthropic --model claude-sonnet-4-6`

**LinkedIn / Greenhouse job URLs don't scrape properly**
- These sites require JavaScript rendering.
- Make sure `scraping.playwright_fallback: true` is set in your config.
- Run `playwright install chromium` once after installation.

---

## Updating

```bash
resume-generator update
```

This pulls the latest code from GitHub and reinstalls the tool. Run `doctor` afterwards to make sure everything still works.

---

## Architecture

| Component | Technology |
|-----------|-----------|
| Agent graph | [LangGraph](https://github.com/langchain-ai/langgraph) StateGraph |
| LLM providers | Anthropic Claude · OpenAI GPT · Google Gemini · NVIDIA NIM · Ollama |
| Structured output | Pydantic v2 + `llm.with_structured_output()` |
| Scraping | httpx + readability-lxml → Playwright fallback |
| LaTeX → PDF | [Tectonic](https://tectonic-typesetting.github.io/) |
| PDF → images | pdf2image + Poppler |
| CLI | Typer + Rich |
| State checkpointing | LangGraph SqliteSaver (`~/.resume_generator/state.sqlite`) |

---

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | User error (bad input, missing config, missing API key) |
| 2 | External tool missing (tectonic, poppler) |
| 3 | Generation exhausted retry budget |

---

## Development

```bash
git clone https://github.com/ALDRIN121/resume-agent.git
cd resume-agent
uv sync --extra dev

pytest -q
ruff check src/
```

To add a new LaTeX template, copy `src/resume_agent/templates/default.tex.jinja` and update `config.yaml` to point to it.

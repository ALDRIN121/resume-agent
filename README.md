# Resume Agent

An AI-powered, multi-agent CLI tool that generates a tailored, laser-sharp LaTeX/PDF resume for any job. Paste or scrape the job description, answer a few questions, and get a professionally compiled PDF — in your terminal, with no web UI required.

```
 ██████╗ ███████╗███████╗██╗   ██╗███╗   ███╗███████╗
 ██╔══██╗██╔════╝██╔════╝██║   ██║████╗ ████║██╔════╝
 ██████╔╝█████╗  ███████╗██║   ██║██╔████╔██║█████╗
 ██╔══██╗██╔══╝  ╚════██║██║   ██║██║╚██╔╝██║██╔══╝
 ██║  ██║███████╗███████║╚██████╔╝██║ ╚═╝ ██║███████╗
 ╚═╝  ╚═╝╚══════╝╚══════╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝
       A G E N T
```

---

## Agent pipeline

```
Input (text / URL)
    │
    ▼
[Scraper Agent]  — httpx + readability → Playwright fallback for JS-gated sites
    │
    ▼
[JD Extractor]   — LLM structured output → JobDescription (company, skills, keywords …)
    │
    ▼
[Base Resume Loader] — YAML parsed once from your .tex or .pdf on first init
    │
    ▼
[Gap Analyzer]   — LLM cross-check: matched skills, missing skills, open questions, suggestions
    │
    ├── (if questions) → [HITL: Human Input] ← interrupt, CLI prompts you
    │
    ▼
[Suggestion Presenter] ← interrupt, you approve/reject bullet rewrites
    │
    ▼
[Resume Generator] — Jinja2 template + LLM polish → LaTeX source
    │
    ▼
[LaTeX Validator]  — brace/env balance + optional chktex
    │
    ├── (fail) ──► loop back to Generator (max 3 retries)
    ▼
[PDF Compiler]     — Tectonic (self-contained, auto-fetches packages)
    │
    ├── (fail) ──► loop back to Generator
    ▼
[PDF → Images]     — pdf2image renders each page as PNG
    │
    ▼
[Vision Validator] — Vision LLM checks alignment, overflow, spacing per page
    │
    ├── (issues) ──► loop back to Generator with detailed fix instructions
    ▼
[Output Saver]     — ./output/<Company>/<User>_<Company>_<YYYY-MM-DD>.pdf
```

---

## Requirements

| Tool | Purpose | Install |
|------|---------|---------|
| Python ≥ 3.12 | Runtime | [python.org](https://python.org) |
| [uv](https://docs.astral.sh/uv/) | Package manager | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| [Tectonic](https://tectonic-typesetting.github.io/) | LaTeX → PDF | `cargo install tectonic` or download binary |
| [Poppler](https://poppler.freedesktop.org/) | PDF → images | `brew install poppler` / `sudo apt install poppler-utils` |
| API key | LLM provider | Anthropic, OpenAI, Google Gemini, or local Ollama |

Playwright (for JS-heavy job sites like LinkedIn) is optional — installed automatically by `uv sync` but requires `playwright install chromium` separately.

---

## Quickstart

```bash
# 1. Clone and install
git clone https://github.com/ALDRIN121/resume-agent
cd resume-agent
uv sync

# 2. Set your API key
cp .env.example .env
# Edit .env: add ANTHROPIC_API_KEY=sk-ant-...

# 3. Parse your existing resume (one-time)
resume-agent init --source examples/sample_resume.tex

# 4. Check all tools are working
resume-agent doctor

# 5. Generate a tailored resume from a job description
resume-agent generate --jd-text "$(cat examples/sample_jd.txt)"
# or
resume-agent generate --jd-url "https://jobs.example.com/senior-engineer"
```

The PDF lands at: `./output/<company>/<you>_<company>_<date>.pdf`

---

## Commands

```
resume-agent init     --source <path>          # One-time: parse your base resume
resume-agent generate --jd-text "..."          # Generate from pasted JD text
resume-agent generate --jd-url <url>           # Generate from scraped URL
resume-agent generate --jd-url <url> \
                      --provider openai \
                      --model gpt-4o           # Override provider/model
resume-agent resume   <thread-id>              # Resume a paused HITL session
resume-agent config show                       # View current config
resume-agent config set provider openai        # Change provider
resume-agent config set retries.generator_max 5
resume-agent doctor                            # Check tools + API keys
```

---

## Configuration

Config lives at `~/.resume_agent/config.yaml` (auto-created on first run):

```yaml
provider: anthropic          # anthropic | openai | google | ollama
model:
  default: claude-sonnet-4-6
  vision:  claude-opus-4-6   # Used for PDF layout validation
scraping:
  playwright_fallback: true
latex:
  tectonic_path: tectonic
output:
  base_dir: ./output
retries:
  generator_max: 3
```

API keys are read from environment variables or a `.env` file:
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GOOGLE_API_KEY`
- `OLLAMA_BASE_URL` (default: `http://localhost:11434`)

---

## How HITL works

When the gap analyzer finds experience that *might* be in your background but isn't documented, it pauses and asks you directly:

```
╭── Human Input Needed ───────────────────────────────────────╮
│  Q1: Have you participated in on-call rotations?             │
│  Why: The JD requires on-call ownership of services          │
│                                                              │
│  Your answer: Yes, 2-week rotations at Acme, PagerDuty      │
╰─────────────────────────────────────────────────────────────╯
```

The answer is incorporated (honestly — nothing is fabricated). If you get interrupted (Ctrl-C), your session is saved. Resume with:

```bash
resume-agent resume <thread-id>
```

---

## Output format

```
./output/
└── techcorp/
    └── jane-doe_techcorp_2026-04-15.pdf
    └── jane-doe_techcorp_2026-04-15_v2.pdf   ← version suffix if file exists
```

Failed generations are saved for debugging:
```
./output/_failed/20260415_143022/
    resume.tex       ← last LaTeX attempt
    errors.txt       ← error log
```

---

## Development

```bash
uv sync --extra dev
pytest -q
ruff check src/
```

To add a new LaTeX template, copy `src/resume_agent/templates/default.tex.jinja` and update `config.yaml` to point to it (future: `--template` flag).

---

## Architecture

| Component | Technology |
|-----------|-----------|
| Agent graph | [LangGraph](https://github.com/langchain-ai/langgraph) StateGraph |
| LLM | Claude (Anthropic) / GPT-4o (OpenAI) / Ollama |
| Structured output | Pydantic v2 + `llm.with_structured_output()` |
| Scraping | httpx + readability-lxml → Playwright fallback |
| LaTeX → PDF | [Tectonic](https://tectonic-typesetting.github.io/) |
| PDF → images | pdf2image + poppler |
| CLI | Typer + Rich |
| State checkpointing | LangGraph SqliteSaver (`~/.resume_agent/state.sqlite`) |

---

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | User error (bad input, missing config, missing API key) |
| 2 | External tool missing (tectonic, poppler, etc.) |
| 3 | Generation exhausted retry budget |

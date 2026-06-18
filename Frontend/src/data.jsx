// Static data: pipeline nodes, sample run events, history, etc.

export const PIPELINE_NODES = [
  { id: "route_input",         label: "Reading your input",      avgMs: 320 },
  { id: "scrape_url",          label: "Fetching the posting",    avgMs: 2400 },
  { id: "extract_jd",          label: "Understanding the role",  avgMs: 3100 },
  { id: "load_base_resume",    label: "Loading your resume",     avgMs: 280 },
  { id: "analyze_gaps",        label: "Checking for gaps",       avgMs: 4200 },
  { id: "hitl_ask_missing",    label: "Asking you about gaps",   avgMs: 0,  hitl: true, kind: "ask_missing" },
  { id: "present_suggestions", label: "Suggesting rewrites",     avgMs: 5400, hitl: true, kind: "present_suggestions" },
  { id: "generate_latex",      label: "Writing tailored LaTeX",  avgMs: 8200 },
  { id: "resume_lint",         label: "Linting",                 avgMs: 1100 },
  { id: "validate_latex",      label: "Validating syntax",       avgMs: 600 },
  { id: "compile_pdf",         label: "Compiling PDF",           avgMs: 3300 },
  { id: "render_pages",        label: "Rendering pages",         avgMs: 1800 },
  { id: "validate_alignment",  label: "Reviewing layout",        avgMs: 1400 },
  { id: "hr_review",           label: "HR review pass",          avgMs: 3600 },
  { id: "save_output",         label: "Saving to disk",          avgMs: 220 },
];

export const SAMPLE_HITL_QUESTIONS = [
  { id: "q1", q: "Have you used Kafka in production at TechCorp or StartupXYZ? If so, briefly describe what for.",                                                                       why: "JD weights Kafka heavily; your resume only lists it under skills." },
  { id: "q2", q: "TechCorp asks for Go experience. Your resume says \"Go (learning)\" — could you quantify? (e.g. \"one internal CLI tool\" or \"6 months of side projects\")",            why: "JD requires Go for distributed services." },
  { id: "q3", q: "Any on-call or incident-response experience you'd like surfaced? The JD lists on-call rotations under responsibilities.",                                              why: "JD lists on-call rotations as a key duty." },
];

export const GAP_ANALYSIS_STATS = { matched: 4, missing: 1, questions: 3, suggestions: 4 };

// Deterministic lint warnings (non-blocking, shown after generate_latex)
export const LINT_WARNINGS = [
  { code: "TENSE_MISMATCH", severity: "warn", message: "Current role 'Software Engineer II' at 'Acme Corp' has a past-tense bullet starting with 'migrated'. Use present tense for current roles." },
  { code: "WEAK_VERB",      severity: "warn", message: "Weak opener in 'Software Engineer at StartupXYZ': 'Collaborated with…' — consider a stronger verb (Led, Built, Designed)." },
  { code: "NO_GITHUB",      severity: "info", message: "Senior-level candidate has no GitHub profile. Add personal.github for ATS and recruiter credibility." },
];

// Structured vision-model layout issues (validate_alignment node)
export const VISION_ISSUES = [
  { page: 1, section: "Professional Experience", issue: "First bullet under Acme Corp extends slightly beyond the right margin of the section rule.", fix: "Shorten the first bullet to under 180 chars or adjust the line break." },
  { page: 1, section: "Professional Experience", issue: "\"Mentored 2 junior engineers\" is a soft-skill fragment that disrupts the technical density.", fix: "Merge with the bullet above or expand with specific mentoring outcomes." },
];

// Self-correction attempt log (shown on terminal failure)
export const RETRY_ATTEMPTS = [
  { n: 1, stage: "compile_pdf",        verdict: "fail",    detail: "Tectonic: File ended while scanning use of \\resumeItem" },
  { n: 2, stage: "compile_pdf",        verdict: "fail",    detail: "Tectonic: same unterminated \\resumeItem at line 42" },
  { n: 3, stage: "validate_alignment", verdict: "layout",  detail: "2 layout issues found by vision model (margin + bullet rhythm)" },
  { n: 4, stage: "validate_alignment", verdict: "layout",  detail: "1 layout issue: date 'May 2026 — Present' reads as future" },
  { n: 5, stage: "validate_alignment", verdict: "layout",  detail: "1 layout issue: bullet extends past right margin" },
];

export const FAILED_DEBUG_PATH = "/output/_failed/20260517_142903";

// Expected backend parse stages (mirrors api/routers/resume.py::_parse_resume_job).
// Statuses are overlaid from the real /ws/resume-parse WebSocket events.
export const PARSE_STAGES = [
  { id: "upload",     label: "Uploading file",            sub: "transferring to ~/.resume_generator/source/" },
  { id: "extract",    label: "Extracting resume text",     sub: "Poppler / LaTeX source" },
  { id: "write_yaml", label: "Writing base_resume.yaml",   sub: "~/.resume_generator/base_resume.yaml" },
];

export const SAMPLE_SUGGESTIONS = [
  {
    id: "s1",
    title: "Experience › Acme Corp › bullet 2",
    rationale: "Surfaces distributed-systems framing the JD weights heavily.",
    before: "Reduced API p99 latency from 450ms to 90ms via caching and query optimization",
    after:  "Cut p99 latency 80% (450ms → 90ms) on a distributed Python/FastAPI service handling 2M req/day, via Redis caching and a query-plan rewrite",
    approved: true,
  },
  {
    id: "s2",
    title: "Experience › StartupXYZ › bullet 1",
    rationale: "Adds Kafka-shaped vocabulary the JD scans for.",
    before: "Designed and implemented a real-time event processing pipeline using Python",
    after:  "Built a real-time event-processing pipeline (Python, Celery, Redis Streams) — 12k events/sec sustained, exactly-once semantics, backpressure handling",
    approved: true,
  },
  {
    id: "s3",
    title: "Summary",
    rationale: "Aligns headline to the platform-team framing in the JD.",
    before: "Backend engineer with 6 years building scalable distributed systems.",
    after:  "Backend engineer (6 yrs) building distributed data infrastructure — high-throughput services in Python, observability-first, comfortable on-call.",
    approved: false,
  },
  {
    id: "s4",
    title: "Skills › Infrastructure",
    rationale: "JD lists EKS specifically; keep ECS but lead with EKS.",
    before: "Docker, Kubernetes, Terraform, AWS (ECS, S3, RDS, SQS)",
    after:  "Docker, Kubernetes (EKS), Terraform, AWS (EKS, ECS, S3, RDS, SQS), Helm",
    approved: false,
  },
];

export const SAMPLE_LOG_LINES = [
  "[14:22:01.118] route_input        | input_kind=text length=1897",
  "[14:22:01.451] extract_jd         | model=claude-sonnet-4 tokens_in=1822 tokens_out=412",
  "[14:22:04.580] extract_jd         | company=\"TechCorp\" role=\"Senior Software Engineer\" seniority=\"senior\"",
  "[14:22:04.612] load_base_resume   | source=~/.resume_generator/base.yaml sections=6",
  "[14:22:04.889] analyze_gaps       | starting…",
  "[14:22:09.103] analyze_gaps       | gaps={kafka_prod_use, go_quantification, oncall_history}",
  "[14:22:09.140] hitl_ask_missing   | interrupt → awaiting user response",
];

export const RECENT_RUNS = [
  { id: "thr_8af2", company: "TechCorp",         role: "Senior Software Engineer",  date: "May 17, 2026  ·  2:21 PM", status: "running",       duration: "—",     retries: 0, pdf: null },
  { id: "thr_c11b", company: "Lattice Robotics", role: "Staff Backend Engineer",    date: "May 17, 2026  ·  2:18 PM", status: "awaiting-input",duration: "—",     retries: 0, pdf: null, hitlDetail: "3 questions about your experience" },
  { id: "thr_4ce0", company: "Lattice Robotics", role: "Staff Backend Engineer",    date: "May 16, 2026  ·  9:14 AM", status: "complete",      duration: "47s",   retries: 0, pdf: "aldrin_lattice_2026-05-16.pdf" },
  { id: "thr_2bb9", company: "Northwind Data",   role: "Senior Platform Engineer",  date: "May 15, 2026  ·  6:02 PM", status: "complete",      duration: "53s",   retries: 1, pdf: "aldrin_northwind_2026-05-15.pdf" },
  { id: "thr_9f1c", company: "Boltline",         role: "Senior Software Engineer",  date: "May 14, 2026  ·  11:47 AM",status: "failed",        duration: "1m 12s",retries: 3, pdf: null },
  { id: "thr_71a3", company: "TechCorp",         role: "Backend Engineer II",       date: "May 12, 2026  ·  4:30 PM", status: "complete",      duration: "39s",   retries: 0, pdf: "aldrin_techcorp_2026-05-12.pdf" },
  { id: "thr_30dd", company: "Lattice Robotics", role: "Senior Software Engineer",  date: "May 10, 2026  ·  10:21 AM",status: "complete",      duration: "44s",   retries: 0, pdf: "aldrin_lattice_2026-05-10.pdf" },
  { id: "thr_5ee7", company: "Halocode",         role: "Founding Engineer",         date: "May 9, 2026  ·  3:55 PM",  status: "complete",      duration: "1m 04s",retries: 2, pdf: "aldrin_halocode_2026-05-09.pdf" },
  { id: "thr_b2a0", company: "Northwind Data",   role: "Backend Engineer",          date: "May 7, 2026  ·  8:11 AM",  status: "complete",      duration: "41s",   retries: 0, pdf: "aldrin_northwind_2026-05-07.pdf" },
];

export const RESUME = {
  profile: {
    name: "Aldrin Carlos",
    email: "aldrin@hey.com",
    phone: "+1-415-555-0142",
    location: "San Francisco, CA",
    linkedin: "linkedin.com/in/aldrincarlos",
    github: "github.com/aldrincarlos",
    summary: "Backend engineer with 6 years building scalable distributed systems. Passionate about developer tooling, data pipelines, and clean API design. Led teams of up to 4 engineers and shipped products serving millions of users.",
  },
  experience: [
    {
      id: "e1", role: "Software Engineer II", company: "Acme Corp", location: "San Francisco, CA",
      start: "Jan 2022", end: "Present",
      bullets: [
        "Built a Python-based microservices platform handling 2M requests/day",
        "Reduced API p99 latency from 450ms to 90ms via caching and query optimization",
        "Migrated monolith to Docker containers, enabling 10x faster deployments",
        "Mentored 2 junior engineers through code review and pair programming",
      ],
      tech: "Python, FastAPI, PostgreSQL, Docker, AWS ECS, Redis",
    },
    {
      id: "e2", role: "Software Engineer", company: "StartupXYZ", location: "Remote",
      start: "Mar 2019", end: "Dec 2021",
      bullets: [
        "Designed and implemented a real-time event processing pipeline using Python",
        "Built CI/CD pipelines with GitHub Actions, cutting deployment time by 60%",
        "Owned the data ingestion API used by 50+ enterprise customers",
        "Collaborated with data science team to productionize ML model serving",
      ],
      tech: "Python, Flask, Celery, MySQL, Redis, Terraform, GitHub Actions",
    },
  ],
  projects: [
    {
      id: "p1", name: "pystream", url: "github.com/aldrincarlos/pystream", tech: "Python, Kafka, asyncio",
      bullets: [
        "Open-source library for building event-driven microservices in Python",
        "800+ GitHub stars; used in production by 3 companies",
        "Implemented backpressure handling and exactly-once delivery semantics",
      ],
    },
  ],
  education: [
    { id: "ed1", school: "University of California, Berkeley", degree: "B.S. Computer Science", end: "May 2019", extra: "GPA: 3.7" },
  ],
  skills: {
    Languages: ["Python", "SQL", "Go (learning)", "Bash"],
    Frameworks: ["FastAPI", "Flask", "SQLAlchemy", "Celery"],
    Infrastructure: ["Docker", "Kubernetes", "Terraform", "AWS"],
    Databases: ["PostgreSQL", "MySQL", "Redis", "MongoDB"],
    Tools: ["Git", "GitHub Actions", "Jenkins", "Prometheus", "Grafana"],
  },
};

export const JD_TEXT = `Senior Software Engineer — TechCorp

About TechCorp:
TechCorp builds cloud-native data infrastructure used by Fortune 500 companies.
Our platform processes over 10 billion events per day with sub-millisecond latency.

Role: Senior Software Engineer, Platform Team
Location: San Francisco, CA (Hybrid)
Seniority: Senior (5+ years)

Responsibilities:
- Design and implement distributed microservices in Python and Go
- Build and maintain high-throughput data pipelines using Apache Kafka
- Drive technical decisions and mentor junior engineers
- Own system reliability, participate in on-call rotations
- Collaborate with cross-functional teams to define system architecture

Must-Have Skills:
- 5+ years of software engineering experience
- Strong proficiency in Python (asyncio, FastAPI, or similar)
- Experience with distributed systems and microservices architecture
- Hands-on experience with Kubernetes and Docker
- Familiarity with cloud platforms (AWS preferred)`;

// ─── Provider catalogue (mirrors src/resume_agent/ui/setup_wizard.py) ────────
export const PROVIDERS = [
  { id: "gemini",         name: "Gemini",            sub: "Google",                 cost: "Free tier", url: "aistudio.google.com/apikey",        needsKey: true,  hint: "Best free option", logo: "G" },
  { id: "nvidia",         name: "NVIDIA NIM",        sub: "Hosted endpoints",       cost: "Free tier", url: "build.nvidia.com",                   needsKey: true,  hint: "Free playground", logo: "N" },
  { id: "ollama_local",   name: "Ollama",            sub: "Local — runs offline",   cost: "Free",      url: null,                                  needsKey: false, hint: "No internet", logo: "○" },
  { id: "ollama_remote",  name: "Ollama",            sub: "Remote — self-hosted",   cost: "Free*",     url: null,                                  needsKey: "maybe", hint: "Cloud or LAN", logo: "↗" },
  { id: "anthropic",      name: "Anthropic",         sub: "Claude",                 cost: "Paid",      url: "console.anthropic.com",               needsKey: true,  hint: "Recommended", logo: "A", recommended: true },
  { id: "openai",         name: "OpenAI",            sub: "GPT",                    cost: "Paid",      url: "platform.openai.com/api-keys",        needsKey: true,  hint: null, logo: "◐" },
];

export const PROVIDER_MODELS = {
  gemini:        ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"],
  nvidia:        ["meta/llama-3.3-70b-instruct", "meta/llama-3.1-70b-instruct", "nvidia/llama-3.1-nemotron-70b-instruct", "mistralai/mixtral-8x7b-instruct-v0.1"],
  anthropic:     ["claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5-20251001"],
  openai:        ["gpt-5.5", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.2"],
  ollama_local:  ["llama3.2", "gemma2", "mistral", "qwen2.5", "phi3", "codellama"],
  ollama_remote: ["llama3.2", "gemma2", "mistral", "qwen2.5", "phi3", "codellama"],
};

export const PROVIDER_VISION_MODELS = {
  gemini:        ["gemini-2.5-flash", "gemini-2.5-pro"],
  nvidia:        ["meta/llama-3.2-11b-vision-instruct", "microsoft/phi-3.5-vision-instruct"],
  anthropic:     ["claude-opus-4-8", "claude-sonnet-4-6"],
  openai:        ["gpt-5.5", "gpt-5.4-mini"],
  ollama_local:  ["llava", "llava:13b", "llava:34b"],
  ollama_remote: ["llava", "llava:13b", "llava:34b"],
};

// "Active" connection that the sidebar/topbar surface as the current model.
export const ACTIVE_LLM = {
  providerId: "anthropic",
  providerName: "Anthropic",
  defaultModel: "claude-sonnet-4-6",
  visionModel: "claude-opus-4-8",
  visionEnabled: true,
  baseUrl: null,
  status: "connected",          // connected | reconnecting | error
  latencyMs: 412,
  lastTested: "3 min ago",
  testReply: "OK",
};


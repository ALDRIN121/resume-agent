import React from "react";
import { Icon } from "./icons.jsx";
import { Button, IconButton, StatusPill, Badge, Textarea, MonoTicker } from "./components.jsx";
import { PipelineTimeline } from "./timeline.jsx";
import { resumeRun, getRun, cancelRun, pdfUrl } from "./api/client.js";
import { subscribeRun } from "./api/ws.js";
import { ACTIVE_LLM, FAILED_DEBUG_PATH, GAP_ANALYSIS_STATS, LINT_WARNINGS, PIPELINE_NODES, RETRY_ATTEMPTS, SAMPLE_HITL_QUESTIONS, SAMPLE_LOG_LINES, SAMPLE_SUGGESTIONS, VISION_ISSUES } from "./data.jsx";

// Live run view — the centerpiece.
// Three columns: pipeline timeline / activity (HITL) / PDF preview.
// Drives a stepped simulation. Run state can be controlled by Tweaks or in-page playback.

// -------------- Run state machines --------------
// Each "run state" defines the prototype snapshot.
const computeEventsForState = (runState, manualIdx) => {
  // Returns { events[], currentNodeIdx, isPaused, hitlState, completed, failed, elapsedMs, retryFor }
  const events = PIPELINE_NODES.map(() => ({ status: "pending", durationMs: null }));
  let elapsed = 0;

  const markDone = (i) => {
    events[i] = { status: "done", durationMs: PIPELINE_NODES[i].avgMs || 200 };
    elapsed += events[i].durationMs;
  };

  if (runState === "running" && manualIdx == null) {
    // We're 4 nodes in, gap_analyzer running.
    for (let i = 0; i < 4; i++) markDone(i);
    events[4] = { status: "running", durationMs: null };
    return { events, currentNodeIdx: 4, isPaused: false, hitlState: null, elapsedMs: elapsed + 1800, retryFor: null };
  }
  if (runState === "awaiting-input" && manualIdx == null) {
    // Through gap analyzer, now waiting at hitl_ask_missing.
    for (let i = 0; i < 5; i++) markDone(i);
    events[5] = { status: "running", durationMs: null };
    return { events, currentNodeIdx: 5, isPaused: true, hitlState: "ask_missing", elapsedMs: elapsed + 1200, retryFor: null };
  }
  if (runState === "suggestions" && manualIdx == null) {
    for (let i = 0; i < 6; i++) markDone(i);
    events[6] = { status: "running", durationMs: null };
    return { events, currentNodeIdx: 6, isPaused: true, hitlState: "present_suggestions", elapsedMs: elapsed + 600, retryFor: null };
  }
  if (runState === "complete" && manualIdx == null) {
    for (let i = 0; i < PIPELINE_NODES.length; i++) markDone(i);
    return { events, currentNodeIdx: PIPELINE_NODES.length, isPaused: false, hitlState: null, completed: true, elapsedMs: 47000, retryFor: null };
  }
  if (runState === "failed" && manualIdx == null) {
    // Failed after 5 self-correction attempts that spanned compile_pdf and validate_alignment.
    // Mark earlier compile/render as done (the final attempt did compile), and fail at validate_alignment.
    for (let i = 0; i < 12; i++) markDone(i);
    events[10] = { status: "done", durationMs: 4100 };       // compile_pdf eventually OK
    events[12] = { status: "failed", durationMs: 5200 };     // validate_alignment finally fails
    return { events, currentNodeIdx: 12, isPaused: false, hitlState: null, failed: true, elapsedMs: 64800, retryFor: 12 };
  }

  // Manual override — step through events
  const k = manualIdx ?? 0;
  for (let i = 0; i < Math.min(k, PIPELINE_NODES.length); i++) markDone(i);
  if (k < PIPELINE_NODES.length) {
    const node = PIPELINE_NODES[k];
    if (node.hitl) {
      events[k] = { status: "running", durationMs: null };
      return { events, currentNodeIdx: k, isPaused: true,
               hitlState: node.kind, elapsedMs: elapsed + 600, retryFor: null };
    }
    events[k] = { status: "running", durationMs: null };
    return { events, currentNodeIdx: k, isPaused: false, hitlState: null, elapsedMs: elapsed + 1500, retryFor: null };
  }
  return { events, currentNodeIdx: PIPELINE_NODES.length, isPaused: false, hitlState: null, completed: true, elapsedMs: elapsed, retryFor: null };
};

const fmtElapsed = (ms) => {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const ss = String(s % 60).padStart(2, "0");
  const cs = String(Math.floor((ms % 1000) / 10)).padStart(2, "0");
  return `${m}:${ss}.${cs}`;
};

const computeEventsFromApi = (events) => {
  const timeline = PIPELINE_NODES.map(() => ({ status: "pending", durationMs: null }));
  let currentNodeIdx = 0;
  let hitlState = null;
  let hitlPayload = null;
  let completed = false;
  let failed = false;
  let retryFor = null;
  let elapsedMs = 0;

  for (const event of events) {
    if (event.type === "node_start") {
      const idx = PIPELINE_NODES.findIndex(n => n.id === event.node_id);
      if (idx >= 0) {
        timeline[idx] = { ...timeline[idx], status: "running" };
        currentNodeIdx = idx;
        hitlState = null;
        hitlPayload = null;
      }
    }
    if (event.type === "hitl_resolved") {
      hitlState = null;
      hitlPayload = null;
    }
    if (event.type === "node_end") {
      const idx = PIPELINE_NODES.findIndex(n => n.id === event.node_id);
      if (idx >= 0) {
        timeline[idx] = { status: "done", durationMs: event.duration_ms };
        elapsedMs += event.duration_ms || PIPELINE_NODES[idx].avgMs || 0;
        currentNodeIdx = Math.min(idx + 1, PIPELINE_NODES.length - 1);
      }
    }
    if (event.type === "hitl_pending") {
      hitlState = event.kind;
      hitlPayload = event;
      const nodeId = event.kind === "ask_missing" ? "hitl_ask_missing" : "present_suggestions";
      const idx = PIPELINE_NODES.findIndex(n => n.id === nodeId);
      if (idx >= 0) {
        timeline[idx] = { status: "running", durationMs: null };
        currentNodeIdx = idx;
      }
    }
    if (event.type === "retry") {
      retryFor = PIPELINE_NODES.findIndex(n => n.id === event.attempt.stage);
    }
    if (event.type === "complete") {
      completed = true;
      hitlState = null;
      for (let i = 0; i < timeline.length; i++) {
        if (timeline[i].status === "pending" || timeline[i].status === "running") {
          timeline[i] = { status: "done", durationMs: timeline[i].durationMs || PIPELINE_NODES[i].avgMs || 0 };
        }
      }
      currentNodeIdx = PIPELINE_NODES.length;
    }
    if (event.type === "failed") {
      failed = true;
      hitlState = null;
    }
  }

  return {
    events: timeline,
    currentNodeIdx,
    isPaused: !!hitlState,
    hitlState,
    hitlPayload,
    completed,
    failed,
    elapsedMs,
    retryFor,
  };
};

// -------------- HITL: ask_missing form --------------
const AskMissingForm = ({ questions = SAMPLE_HITL_QUESTIONS, onSubmit, onSkip }) => {
  const [answers, setAnswers] = React.useState(questions.map(q => ""));
  const hasAny = answers.some(a => a.trim().length > 0);
  const submitAnswers = () => {
    const payload = {};
    questions.forEach((q, i) => {
      payload[q.id || `q${i + 1}`] = answers[i] || "";
    });
    onSubmit(payload);
  };

  return (
    <div className="fade-in" style={{ padding: 24 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <span style={{
          width: 26, height: 26, borderRadius: 99, background: "var(--warning-soft)",
          color: "var(--warning)", display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <Icon name="alert" size={14} stroke={2.4}/>
        </span>
        <div style={{ fontSize: 16, fontWeight: 600, letterSpacing: -0.1 }}>Quick questions about your experience</div>
      </div>
      <div style={{ fontSize: 13, color: "var(--text-muted)", marginLeft: 36, marginBottom: 14 }}>
        Answer honestly — the agent will never fabricate experience.
      </div>

      {/* Gap analysis stats banner */}
      <div style={{
        display: "flex", alignItems: "center", flexWrap: "wrap", gap: "10px 14px",
        padding: "10px 14px", marginBottom: 18,
        background: "var(--surface-2)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
      }}>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--text-faint)", textTransform: "uppercase", letterSpacing: 0.6, flexShrink: 0 }}>gap analysis</span>
        {[
          { l: "matched",     v: GAP_ANALYSIS_STATS.matched,     c: "var(--success)" },
          { l: "missing",     v: GAP_ANALYSIS_STATS.missing,     c: "var(--warning)" },
          { l: "questions",   v: GAP_ANALYSIS_STATS.questions,   c: "var(--text)" },
          { l: "suggestions", v: GAP_ANALYSIS_STATS.suggestions, c: "var(--text)" },
        ].map(s => (
          <span key={s.l} style={{ display: "inline-flex", alignItems: "baseline", gap: 6, flexShrink: 0 }}>
            <span className="mono" style={{ fontSize: 14, fontWeight: 600, color: s.c, fontVariantNumeric: "tabular-nums" }}>{s.v}</span>
            <span style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{s.l}</span>
          </span>
        ))}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {questions.map((q, i) => (
          <div key={q.id} style={{
            display: "grid", gridTemplateColumns: "24px 1fr", gap: 12,
          }}>
            <div className="mono" style={{
              fontSize: 11, color: "var(--text-faint)", paddingTop: 8, lineHeight: 1.2,
            }}>Q{i+1}</div>
            <div>
              <div style={{ fontSize: 13.5, lineHeight: 1.55, marginBottom: 4, color: "var(--text)" }}>
                {q.q || q.prompt}
              </div>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 5, marginBottom: 8 }}>
                <span className="mono" style={{ fontSize: 10.5, color: "var(--text-faint)", flexShrink: 0, paddingTop: 1 }}>why</span>
                <span style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>{q.why || q.why_asking}</span>
              </div>
              <Textarea
                value={answers[i]}
                onChange={(e) => setAnswers(a => { const next = [...a]; next[i] = e.target.value; return next; })}
                onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && hasAny) { e.preventDefault(); submitAnswers(); } }}
                placeholder="Your answer…"
                style={{ minHeight: 58, fontSize: 13.5 }}
              />
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 22, paddingTop: 16, borderTop: "1px solid var(--border)", flexWrap: "wrap", gap: 10 }}>
        <Button variant="ghost" icon="skip" onClick={onSkip}>Skip all</Button>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {answers.filter(a => a.trim()).length} of {questions.length} answered
          </span>
          <Button variant="primary" iconRight="arrow-right" disabled={!hasAny}
            onClick={submitAnswers}>Submit answers</Button>
        </div>
      </div>
    </div>
  );
};

// Diff renderer for present_suggestions
const SuggestionDiff = ({ before, after }) => {
  // Word-level diff — naive but visually correct.
  const wA = before.split(/(\s+)/);
  const wB = after.split(/(\s+)/);
  const setB = new Set(wB.map(w => w.toLowerCase()));
  const setA = new Set(wA.map(w => w.toLowerCase()));

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12 }}>
      <div style={{
        padding: 12, background: "var(--danger-soft)",
        border: "1px solid color-mix(in oklab, var(--danger) 20%, transparent)",
        borderRadius: "var(--radius-md)",
        fontSize: 12.5, lineHeight: 1.55, color: "var(--text)",
      }}>
        <div className="mono" style={{ fontSize: 10.5, color: "var(--danger)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>before</div>
        {wA.map((w, i) => /\s+/.test(w) ? w : (
          <span key={i} style={!setB.has(w.toLowerCase()) ? { background: "color-mix(in oklab, var(--danger) 28%, transparent)", padding: "0 2px", borderRadius: 2 } : {}}>{w}</span>
        ))}
      </div>
      <div style={{
        padding: 12, background: "var(--success-soft)",
        border: "1px solid color-mix(in oklab, var(--success) 22%, transparent)",
        borderRadius: "var(--radius-md)",
        fontSize: 12.5, lineHeight: 1.55, color: "var(--text)",
      }}>
        <div className="mono" style={{ fontSize: 10.5, color: "var(--success)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>after</div>
        {wB.map((w, i) => /\s+/.test(w) ? w : (
          <span key={i} style={!setA.has(w.toLowerCase()) ? { background: "color-mix(in oklab, var(--success) 24%, transparent)", padding: "0 2px", borderRadius: 2 } : {}}>{w}</span>
        ))}
      </div>
    </div>
  );
};

const normalizeSuggestion = (suggestion) => ({
  ...suggestion,
  title: suggestion.title || [suggestion.section, suggestion.role_company].filter(Boolean).join(" › ") || "Suggestion",
  approved: suggestion.approved ?? true,
});

const SuggestionList = ({ suggestions = SAMPLE_SUGGESTIONS, onContinue }) => {
  const [items, setItems] = React.useState(suggestions.map(normalizeSuggestion));
  React.useEffect(() => setItems(suggestions.map(normalizeSuggestion)), [suggestions]);
  const approvedCount = items.filter(i => i.approved).length;
  const toggle = (id) => setItems(items.map(it => it.id === id ? { ...it, approved: !it.approved } : it));
  const setAll = (v) => setItems(items.map(it => ({ ...it, approved: v })));

  return (
    <div className="fade-in" style={{ padding: 24 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{
            width: 26, height: 26, borderRadius: 99, background: "var(--accent-soft)",
            color: "var(--accent)", display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <Icon name="sparkles" size={14} stroke={2.4}/>
          </span>
          <div style={{ fontSize: 16, fontWeight: 600, letterSpacing: -0.1 }}>Suggested rewrites</div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <Button size="sm" variant="ghost" onClick={() => setAll(true)}>Approve all</Button>
          <Button size="sm" variant="ghost" onClick={() => setAll(false)}>Reject all</Button>
        </div>
      </div>
      <div style={{ fontSize: 13, color: "var(--text-muted)", marginLeft: 36, marginBottom: 18 }}>
        {approvedCount} of {items.length} approved · these rewrite your bullets just for this run
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {items.map(it => (
          <div key={it.id} style={{
            border: "1px solid var(--border)", borderRadius: "var(--radius-lg)",
            background: "var(--surface)",
            padding: 14,
          }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="mono" style={{ fontSize: 11, color: "var(--text-muted)", letterSpacing: 0.2 }}>{it.title}</div>
                <div style={{ fontSize: 12.5, color: "var(--text-muted)", marginTop: 4, lineHeight: 1.5 }}>{it.rationale}</div>
              </div>
              <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", flexShrink: 0 }}>
                <span style={{ fontSize: 12, color: it.approved ? "var(--success)" : "var(--text-muted)", fontWeight: 500 }}>
                  {it.approved ? "Approved" : "Approve"}
                </span>
                <button
                  role="switch" aria-checked={it.approved} onClick={() => toggle(it.id)}
                  style={{
                    width: 32, height: 18, position: "relative",
                    border: "1px solid " + (it.approved ? "var(--success)" : "var(--border-strong)"),
                    background: it.approved ? "var(--success)" : "var(--surface)",
                    borderRadius: 99, cursor: "pointer",
                  }}>
                  <span style={{
                    position: "absolute", top: 1, left: it.approved ? 14 : 1,
                    width: 14, height: 14, background: it.approved ? "white" : "var(--text-muted)",
                    borderRadius: 99, transition: `left var(--t-fast)`,
                  }}/>
                </button>
              </label>
            </div>
            <SuggestionDiff before={it.before} after={it.after} />
          </div>
        ))}
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
        <Button variant="primary" iconRight="arrow-right" onClick={() => onContinue(items.filter(i => i.approved).map(i => i.id))}>Continue</Button>
      </div>
    </div>
  );
};

// Fake PDF preview — HTML rendered to look like a tailored resume page
const FakePDFPage = ({ scale = 1 }) => (
  <div style={{
    width: 612 * scale, height: 792 * scale, // letter
    background: "white",
    boxShadow: "var(--shadow-md)",
    borderRadius: 3,
    padding: `${48 * scale}px ${48 * scale}px`,
    color: "#111",
    fontFamily: "'Times New Roman', Georgia, serif",
    fontSize: 10.5 * scale,
    lineHeight: 1.35,
    overflow: "hidden",
  }}>
    <div style={{ textAlign: "center", marginBottom: 12 * scale }}>
      <div style={{ fontSize: 18 * scale, fontWeight: 700, letterSpacing: -0.2 }}>Aldrin Carlos</div>
      <div style={{ fontSize: 9.5 * scale, marginTop: 4 * scale, color: "#333" }}>
        aldrin@hey.com · +1-415-555-0142 · San Francisco, CA · linkedin.com/in/aldrincarlos · github.com/aldrincarlos
      </div>
    </div>

    <div style={{ borderTop: "1px solid #aaa", paddingTop: 8 * scale, marginBottom: 10 * scale }}>
      <div style={{ fontWeight: 700, textTransform: "uppercase", fontSize: 10 * scale, letterSpacing: 0.6, marginBottom: 4 * scale }}>Summary</div>
      <div>Backend engineer (6 yrs) building distributed data infrastructure — high-throughput services in Python, observability-first, comfortable on-call. Shipped products serving millions of users.</div>
    </div>

    <div style={{ borderTop: "1px solid #aaa", paddingTop: 8 * scale, marginBottom: 10 * scale }}>
      <div style={{ fontWeight: 700, textTransform: "uppercase", fontSize: 10 * scale, letterSpacing: 0.6, marginBottom: 4 * scale }}>Experience</div>
      <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 600 }}>
        <span>Software Engineer II · Acme Corp</span>
        <span style={{ color: "#555" }}>Jan 2022 — Present</span>
      </div>
      <div style={{ fontStyle: "italic", color: "#555", fontSize: 9.5 * scale, marginBottom: 3 * scale }}>San Francisco, CA</div>
      <ul style={{ margin: 0, paddingLeft: 14 * scale }}>
        <li>Built a Python-based microservices platform handling 2M requests/day</li>
        <li>Cut p99 latency 80% (450ms → 90ms) on a distributed Python/FastAPI service handling 2M req/day, via Redis caching and a query-plan rewrite</li>
        <li>Migrated monolith to Docker containers, enabling 10× faster deployments</li>
        <li>Mentored 2 junior engineers through code review and pair programming</li>
      </ul>
      <div style={{ fontStyle: "italic", color: "#444", fontSize: 9.5 * scale, marginTop: 3 * scale }}>Tech: Python, FastAPI, PostgreSQL, Docker, AWS ECS, Redis</div>

      <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 600, marginTop: 8 * scale }}>
        <span>Software Engineer · StartupXYZ</span>
        <span style={{ color: "#555" }}>Mar 2019 — Dec 2021</span>
      </div>
      <div style={{ fontStyle: "italic", color: "#555", fontSize: 9.5 * scale, marginBottom: 3 * scale }}>Remote</div>
      <ul style={{ margin: 0, paddingLeft: 14 * scale }}>
        <li>Built a real-time event-processing pipeline (Python, Celery, Redis Streams) — 12k events/sec sustained, exactly-once semantics, backpressure handling</li>
        <li>Built CI/CD pipelines with GitHub Actions, cutting deployment time by 60%</li>
        <li>Owned the data ingestion API used by 50+ enterprise customers</li>
        <li>Collaborated with data science team to productionize ML model serving</li>
      </ul>
    </div>

    <div style={{ borderTop: "1px solid #aaa", paddingTop: 8 * scale, marginBottom: 10 * scale }}>
      <div style={{ fontWeight: 700, textTransform: "uppercase", fontSize: 10 * scale, letterSpacing: 0.6, marginBottom: 4 * scale }}>Projects</div>
      <div style={{ fontWeight: 600 }}>pystream <span style={{ fontWeight: 400, color: "#444" }}>(github.com/aldrincarlos/pystream) — Python, Kafka, asyncio</span></div>
      <ul style={{ margin: 0, paddingLeft: 14 * scale }}>
        <li>Open-source library for building event-driven microservices in Python</li>
        <li>800+ GitHub stars; used in production by 3 companies</li>
        <li>Implemented backpressure handling and exactly-once delivery semantics</li>
      </ul>
    </div>

    <div style={{ borderTop: "1px solid #aaa", paddingTop: 8 * scale, marginBottom: 10 * scale }}>
      <div style={{ fontWeight: 700, textTransform: "uppercase", fontSize: 10 * scale, letterSpacing: 0.6, marginBottom: 4 * scale }}>Skills</div>
      <div><b>Languages:</b> Python, SQL, Go, Bash</div>
      <div><b>Frameworks:</b> FastAPI, Flask, SQLAlchemy, Celery, asyncio</div>
      <div><b>Infrastructure:</b> Docker, Kubernetes (EKS), Terraform, AWS (EKS, ECS, S3, RDS, SQS), Helm</div>
      <div><b>Databases:</b> PostgreSQL, MySQL, Redis, MongoDB</div>
    </div>

    <div style={{ borderTop: "1px solid #aaa", paddingTop: 8 * scale }}>
      <div style={{ fontWeight: 700, textTransform: "uppercase", fontSize: 10 * scale, letterSpacing: 0.6, marginBottom: 4 * scale }}>Education</div>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span><b>University of California, Berkeley</b> — B.S. Computer Science</span>
        <span style={{ color: "#555" }}>May 2019 · GPA 3.7</span>
      </div>
    </div>
  </div>
);

const PDFPreviewPane = ({ visible, scale, setScale, page, setPage, onCollapse, pdfUrl, pdfName, isDemo }) => {
  const wrapRef = React.useRef(null);
  if (!visible) {
    // Shimmer placeholder
    return (
      <div style={{
        flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
        background: "var(--surface-2)",
        flexDirection: "column", gap: 18, padding: 24,
        position: "relative",
      }}>
        {onCollapse && (
          <button onClick={onCollapse} title="Hide PDF pane"
            style={{
              position: "absolute", top: 10, right: 12,
              width: 26, height: 26,
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: "var(--radius-md)", color: "var(--text-muted)",
              cursor: "pointer",
            }}>
            <Icon name="chevron-right" size={12}/>
          </button>
        )}
        <div style={{ width: 220, height: 286, position: "relative" }}>
          {[0, 1].map(k => (
            <div key={k} style={{
              position: "absolute",
              top: 8 + k * 4, left: 8 + k * 4, right: 8 - k * 4, bottom: 8 - k * 4,
              background: "linear-gradient(110deg, var(--surface) 30%, var(--surface-3) 50%, var(--surface) 70%)",
              backgroundSize: "200% 100%",
              animation: "shimmer 2.4s linear infinite",
              border: "1px solid var(--border)",
              borderRadius: 3,
              boxShadow: "var(--shadow-sm)",
            }}/>
          ))}
        </div>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 13, color: "var(--text-muted)" }}>PDF preview will appear here</div>
          <div className="mono" style={{ fontSize: 11, color: "var(--text-faint)", marginTop: 4 }}>waiting for compile_pdf →</div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      {/* Header bar */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "10px 14px", borderBottom: "1px solid var(--border)",
        background: "var(--surface)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span style={{ width: 22, height: 22, display: "flex", alignItems: "center", justifyContent: "center",
            background: "var(--danger-soft)", color: "var(--danger)", borderRadius: 4, flexShrink: 0 }}>
            <Icon name="file-text" size={13}/>
          </span>
          <div style={{ minWidth: 0 }}>
            <div className="mono truncate" style={{ fontSize: 12, color: "var(--text)" }}>{pdfName}</div>
            <div className="mono" style={{ fontSize: 10.5, color: "var(--text-faint)" }}>{isDemo ? "1 page · 84 KB" : "PDF document"}</div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Button size="sm" variant="secondary" icon="download" onClick={() => pdfUrl && window.open(pdfUrl, "_blank")}>Download</Button>
          {onCollapse && (
            <IconButton name="chevron-right" label="Hide PDF pane" onClick={onCollapse}/>
          )}
        </div>
      </div>

      {/* Scrollable preview */}
      <div ref={wrapRef} style={{
        flex: 1, overflow: "auto",
        background: "var(--surface-2)",
        display: "flex", justifyContent: "center", padding: 20,
      }}>
        {pdfUrl ? (
          <iframe
            title="Generated PDF"
            src={pdfUrl}
            style={{ width: "100%", minHeight: "100%", border: "none", background: "white" }}
          />
        ) : isDemo ? (
          <div style={{ transformOrigin: "top center" }}>
            <FakePDFPage scale={scale}/>
          </div>
        ) : (
          <div className="mono" style={{ alignSelf: "center", color: "var(--text-faint)", fontSize: 12 }}>
            PDF preview unavailable
          </div>
        )}
      </div>

      {/* Footer controls */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "8px 14px", borderTop: "1px solid var(--border)", background: "var(--surface)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <IconButton name="chevron-up" label="Prev page" />
          <span className="mono" style={{ fontSize: 11.5, color: "var(--text-muted)", padding: "0 6px" }}>1 / 1</span>
          <IconButton name="chevron-down" label="Next page" />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <IconButton name="x" label="Zoom out" onClick={() => setScale(s => Math.max(0.4, s - 0.1))} />
          <span className="mono" style={{ fontSize: 11.5, color: "var(--text-muted)", width: 40, textAlign: "center" }}>{Math.round(scale * 100)}%</span>
          <IconButton name="plus" label="Zoom in" onClick={() => setScale(s => Math.min(1.4, s + 0.1))} />
        </div>
      </div>
    </div>
  );
};

// Log tail
const LogTail = ({ visibleLines, density }) => (
  <div style={{
    background: "var(--surface-2)",
    borderTop: "1px solid var(--border)",
    padding: density === "compact" ? "8px 14px" : "12px 14px",
  }}>
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      marginBottom: 6,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: "var(--text-muted)" }}>
        <Icon name="dot" size={10} stroke={2} style={{ color: "var(--success)" }}/>
        <span className="mono" style={{ letterSpacing: 0.3 }}>log tail · last {visibleLines.length}</span>
      </div>
      <span style={{ fontSize: 11, color: "var(--text-faint)" }}>hover to pause</span>
    </div>
    <div className="mono" style={{
      fontSize: 11, color: "var(--text-muted)", lineHeight: 1.55,
      maxHeight: density === "compact" ? 80 : 110, overflow: "auto",
    }}>
      {visibleLines.map((l, i) => (
        <div key={i} style={{ whiteSpace: "nowrap" }}>{l}</div>
      ))}
    </div>
  </div>
);

// -------------- LiveRunView (the orchestrator) --------------
const LiveRunView = ({ threadId, density, runState: tweakRunState, setRunState, settings }) => {
  // Local state for advancing through nodes (simulation)
  const [manualIdx, setManualIdx] = React.useState(null); // when set, overrides tweakRunState
  const [autoplay, setAutoplay] = React.useState(false);
  const [pdfScale, setPdfScale] = React.useState(0.55);
  const [pdfPage, setPdfPage] = React.useState(1);
  const [selectedIdx, setSelectedIdx] = React.useState(null);
  const [tickMs, setTickMs] = React.useState(0); // live elapsed counter
  const [pdfCollapsed, setPdfCollapsed] = React.useState(false);
  const [apiEvents, setApiEvents] = React.useState([]);
  const [runDetail, setRunDetail] = React.useState(null);
  const [wsStatus, setWsStatus] = React.useState("offline");
  const [cancelling, setCancelling] = React.useState(false);

  // When tweakRunState changes externally, drop manualIdx
  React.useEffect(() => { setManualIdx(null); }, [tweakRunState]);

  React.useEffect(() => {
    if (!threadId) return;
    setApiEvents([]);
    // getRun seeds metadata only. The WS replays the full event history (then
    // live events), so it is the single source of truth for apiEvents — seeding
    // events from getRun too would duplicate the replayed history.
    getRun(threadId)
      .then(setRunDetail)
      .catch(() => {});
    return subscribeRun(
      threadId,
      (event) => setApiEvents(items => [...items, event]),
      setWsStatus,
    );
  }, [threadId]);

  // Autoplay advances manualIdx
  React.useEffect(() => {
    if (!autoplay) return;
    let i = manualIdx ?? 0;
    const interval = setInterval(() => {
      i++;
      if (i > PIPELINE_NODES.length) { setAutoplay(false); clearInterval(interval); return; }
      setManualIdx(i);
    }, 900);
    return () => clearInterval(interval);
  }, [autoplay]);

  // Live ticker for running state
  React.useEffect(() => {
    if (tweakRunState !== "running" || manualIdx != null) return;
    const start = Date.now();
    const id = setInterval(() => setTickMs(Date.now() - start), 47);
    return () => clearInterval(id);
  }, [tweakRunState, manualIdx]);

  const apiSim = threadId ? computeEventsFromApi(apiEvents) : null;
  const sim = apiSim || computeEventsForState(tweakRunState, manualIdx);
  const elapsedDisplay = (tweakRunState === "running" && manualIdx == null)
    ? fmtElapsed(sim.elapsedMs + tickMs)
    : (tweakRunState === "complete" ? "0:47.00" : fmtElapsed(sim.elapsedMs));

  // Auto-collapse PDF pane during HITL — the input is the focus, not a non-existent PDF.
  React.useEffect(() => {
    if (sim.hitlState) setPdfCollapsed(true);
    else if (sim.completed) setPdfCollapsed(false);
  }, [sim.hitlState, sim.completed]);

  const pdfVisible = sim.completed;
  const runStatusForPill = sim.failed ? "failed" : sim.completed ? "complete" : sim.isPaused ? "awaiting-input" : "running";
  const company = runDetail?.company || "Unknown";
  const role = runDetail?.role || "Unknown";
  const logLines = apiEvents.filter(e => e.type === "log_line").map(e => e.line);
  // For real runs (threadId set) never fall back to sample data — show what the
  // run actually produced (possibly empty). Samples are only for the demo view.
  const lintWarnings = apiEvents.find(e => e.type === "lint")?.warnings || (threadId ? [] : LINT_WARNINGS);
  const visionIssues = apiEvents.find(e => e.type === "vision")?.issues || (threadId ? [] : VISION_ISSUES);
  const retryAttempts = apiEvents.filter(e => e.type === "retry").map(e => e.attempt);
  const effectiveRetries = retryAttempts.length ? retryAttempts : (threadId ? [] : RETRY_ATTEMPTS);
  const completeEvent = apiEvents.find(e => e.type === "complete");
  const failedEvent = apiEvents.find(e => e.type === "failed");
  const isDemo = !threadId;
  const pdfName = isDemo ? "aldrin_techcorp_2026-05-17.pdf" : (runDetail?.pdf || "resume.pdf");

  // Real header values for real runs; demo placeholders otherwise (C7).
  const startedLabel = isDemo
    ? "started 2:21 PM"
    : runDetail?.created_at
      ? `started ${new Date(runDetail.created_at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
      : "";
  const viaModel = isDemo ? (ACTIVE_LLM.defaultModel || "claude-sonnet-4-6") : (settings?.defaultModel || "model");
  const downloadUrl = completeEvent?.pdf_url || (isDemo ? null : (threadId ? pdfUrl(threadId) : null));
  const debugPath = failedEvent?.debug_path || (isDemo ? FAILED_DEBUG_PATH : null);

  const cancel = async () => {
    if (!threadId) return;
    setCancelling(true);
    try { await cancelRun(threadId); } catch { /* failure surfaces via the WS failed event */ }
    setCancelling(false);
  };

  const submitMissing = async (answers) => {
    if (!threadId) {
      setManualIdx(6);
      return;
    }
    setApiEvents(items => [...items, { type: "hitl_resolved" }]);
    await resumeRun(threadId, "ask_missing", { answers });
  };

  const submitSuggestions = async (approvedIds) => {
    if (!threadId) {
      setManualIdx(7);
      return;
    }
    setApiEvents(items => [...items, { type: "hitl_resolved" }]);
    await resumeRun(threadId, "present_suggestions", { approved_ids: approvedIds });
  };

  // Activity panel content
  const renderActivity = () => {
    if (sim.failed) {
      return (
        <div className="fade-in" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{
            border: "1px solid color-mix(in oklab, var(--danger) 30%, transparent)",
            background: "var(--danger-soft)",
            borderRadius: "var(--radius-lg)", padding: 18,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <span style={{ width: 26, height: 26, borderRadius: 99, background: "var(--danger)", color: "white", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Icon name="x" size={14} stroke={2.6}/>
              </span>
              <div>
                <div style={{ fontSize: 15, fontWeight: 600 }}>Generation failed</div>
                <div className="mono" style={{ fontSize: 11.5, color: "var(--danger)" }}>{failedEvent?.reason || `retry budget exhausted · ${effectiveRetries[0].stage} ↻ ${effectiveRetries[effectiveRetries.length - 1].stage}`}</div>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <Button variant="primary" icon="refresh">Try again</Button>
              <Button variant="secondary" icon="edit">Edit base resume</Button>
              <Button variant="ghost" icon="folder">Open debug artifacts</Button>
            </div>
          </div>

          {/* Self-correction attempts */}
          <div style={{
            border: "1px solid var(--border)", borderRadius: "var(--radius-lg)",
            background: "var(--surface)", overflow: "hidden",
          }}>
            <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Icon name="refresh" size={13} style={{ color: "var(--text-muted)" }}/>
                <span style={{ fontSize: 13, fontWeight: 600 }}>Self-correction attempts</span>
              <Badge tone="warning">{effectiveRetries.length} attempts</Badge>
              </div>
            </div>
            <div>
              {effectiveRetries.map((a, i) => (
                <div key={a.n} style={{
                  display: "grid", gridTemplateColumns: "40px 110px 1fr",
                  alignItems: "flex-start", gap: 12,
                  padding: "10px 16px",
                  borderTop: i > 0 ? "1px solid var(--border)" : "none",
                }}>
                  <span className="mono" style={{ fontSize: 12, color: "var(--text-faint)", paddingTop: 2 }}>#{a.n}</span>
                  <span className="mono" style={{ fontSize: 11.5, color: "var(--text-muted)", paddingTop: 2 }}>{a.stage}</span>
                  <span style={{ fontSize: 12.5, color: "var(--text)", lineHeight: 1.5 }}>{a.detail}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Vision layout issues from the last attempt */}
          <div style={{
            border: "1px solid var(--border)", borderRadius: "var(--radius-lg)",
            background: "var(--surface)", overflow: "hidden",
          }}>
            <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 8 }}>
              <Icon name="eye" size={13} style={{ color: "var(--accent)" }}/>
              <span style={{ fontSize: 13, fontWeight: 600 }}>Last vision-model verdict</span>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>{ACTIVE_LLM.visionModel}</span>
            </div>
            <div>
              {visionIssues.map((iss, i) => (
                <div key={i} style={{
                  padding: "12px 16px", borderTop: i > 0 ? "1px solid var(--border)" : "none",
                  display: "grid", gridTemplateColumns: "1fr", gap: 4,
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5 }} className="mono">
                    <Badge tone="info">page {iss.page}</Badge>
                    <span style={{ color: "var(--text-faint)" }}>{iss.section}</span>
                  </div>
                  <div style={{ fontSize: 12.5, color: "var(--text)", lineHeight: 1.55 }}>
                    <span style={{ color: "var(--warning)", fontWeight: 500 }}>Issue · </span>{iss.issue}
                  </div>
                  <div style={{ fontSize: 12.5, color: "var(--text-muted)", lineHeight: 1.55 }}>
                    <span style={{ color: "var(--success)", fontWeight: 500 }}>Fix · </span>{iss.fix}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Debug artifacts path */}
          {debugPath && (
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "10px 14px",
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-md)",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                <Icon name="folder" size={13} style={{ color: "var(--text-muted)" }}/>
                <span style={{ fontSize: 11.5, color: "var(--text-muted)" }}>Debug artifacts saved to</span>
                <span className="mono truncate" style={{ fontSize: 11.5, color: "var(--text)" }}>{debugPath}</span>
              </div>
              <Button size="sm" variant="ghost" icon="copy" onClick={() => navigator.clipboard?.writeText(debugPath)}>Copy path</Button>
            </div>
          )}
        </div>
      );
    }

    if (sim.completed) {
      return (
        <div className="fade-in" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 14,
            padding: 18,
            background: "var(--success-soft)",
            border: "1px solid color-mix(in oklab, var(--success) 30%, transparent)",
            borderRadius: "var(--radius-lg)",
            position: "relative", overflow: "hidden",
          }}>
            {/* Sparkle burst */}
            {[0,1,2,3,4,5].map(i => (
              <span key={i} style={{
                position: "absolute",
                left: `${28 + (i % 3) * 6}px`,
                top: "50%",
                width: 6, height: 6, borderRadius: 99,
                background: i % 2 ? "var(--success)" : "var(--accent)",
                opacity: 0,
                animation: `sparkle-up 1.4s ${i * 90}ms var(--ease-bounce) both`,
              }}/>
            ))}
            <div className="pop-in" style={{
              width: 46, height: 46, borderRadius: 99,
              background: "var(--success)", color: "white",
              display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
              position: "relative", zIndex: 1,
            }}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                <path d="M5 12l5 5L20 7" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"
                  style={{ strokeDasharray: 24, animation: "draw-check 380ms 180ms cubic-bezier(.2,.7,.3,1) both" }}/>
              </svg>
            </div>
            <div style={{ flex: 1, minWidth: 0, position: "relative", zIndex: 1 }}>
            <div style={{ fontSize: 17, fontWeight: 600, letterSpacing: -0.2 }}>Done in {completeEvent?.duration_s ? `${Math.round(completeEvent.duration_s)}s` : "47s"}</div>
            <div style={{ fontSize: 12.5, color: "var(--text-muted)", marginTop: 3 }}>
                Tailored to {company} · PDF ready
              </div>
            </div>
            <Button variant="primary" icon="download" onClick={() => downloadUrl && window.open(downloadUrl, "_blank")}>Download PDF</Button>
          </div>

          {/* Lint warnings — non-blocking but useful */}
          <div style={{
            border: "1px solid var(--border)", borderRadius: "var(--radius-lg)",
            background: "var(--surface)", overflow: "hidden",
          }}>
            <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 8 }}>
              <Icon name="info" size={13} style={{ color: "var(--text-muted)" }}/>
              <span style={{ fontSize: 13, fontWeight: 600 }}>Resume lint</span>
              <Badge tone="warning">{lintWarnings.length} hints</Badge>
              <span style={{ fontSize: 11.5, color: "var(--text-muted)" }}>· non-blocking · consider editing the base resume</span>
            </div>
            <div>
              {lintWarnings.map((w, i) => (
                <div key={i} style={{
                  display: "grid", gridTemplateColumns: "auto 1fr",
                  alignItems: "flex-start", gap: 10,
                  padding: "10px 16px",
                  borderTop: i > 0 ? "1px solid var(--border)" : "none",
                }}>
                  <Badge tone={w.severity === "warn" ? "warning" : "neutral"}>{w.code}</Badge>
                  <span style={{ fontSize: 12.5, color: "var(--text)", lineHeight: 1.55 }}>{w.message}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Generate-another prompt */}
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "12px 16px",
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-md)",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Icon name="sparkles" size={13} style={{ color: "var(--text-muted)" }}/>
              <span style={{ fontSize: 12.5, color: "var(--text)" }}>Generate another resume?</span>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <Button size="sm" variant="secondary" icon="folder">Open folder</Button>
              <Button size="sm" variant="primary" icon="plus">New run</Button>
            </div>
          </div>
        </div>
      );
    }

    if (sim.hitlState === "ask_missing") {
      return <AskMissingForm questions={sim.hitlPayload?.questions || SAMPLE_HITL_QUESTIONS} onSubmit={submitMissing} onSkip={() => submitMissing({})} />;
    }
    if (sim.hitlState === "present_suggestions") {
      return <SuggestionList suggestions={sim.hitlPayload?.suggestions || SAMPLE_SUGGESTIONS} onContinue={submitSuggestions} />;
    }

    // Default: running state
    return (
      <div className="fade-in" style={{
        padding: 24, height: "100%", display: "flex",
        flexDirection: "column", justifyContent: "center", alignItems: "center", textAlign: "center", gap: 18
      }}>
        <div style={{
          width: 80, height: 80, borderRadius: 99, position: "relative",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          {/* Outer dotted orbit */}
          <span style={{
            position: "absolute", inset: -2,
            borderRadius: 99,
            border: "1.5px dashed var(--accent-ring)",
            animation: "spin 8s linear infinite",
          }}/>
          {/* Arc spinner */}
          <span style={{
            position: "absolute", inset: 6,
            border: "2.5px solid var(--accent-ring)",
            borderTopColor: "var(--accent)",
            borderRightColor: "var(--accent)",
            borderRadius: 99,
            animation: "spin 1.2s cubic-bezier(.45,.05,.55,.95) infinite",
          }}/>
          <span className="mono" style={{ fontSize: 18, fontWeight: 600, color: "var(--text)", zIndex: 1 }}>
            {Math.min(sim.currentNodeIdx + 1, PIPELINE_NODES.length)}<span style={{ color: "var(--text-faint)" }}>/{PIPELINE_NODES.length}</span>
          </span>
        </div>
        <div>
          <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: -0.2 }}>
            {PIPELINE_NODES[sim.currentNodeIdx]?.label}
          </div>
          <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 6 }}>
            Generating your tailored resume for {company}…
          </div>
        </div>
        <div style={{
          display: "flex", flexDirection: "column", gap: 6, alignItems: "center",
          padding: "10px 14px", background: "var(--surface-2)", borderRadius: "var(--radius-md)",
          border: "1px solid var(--border)",
        }}>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>elapsed</span>
          <MonoTicker style={{ fontSize: 18, fontWeight: 600, color: "var(--text)" }}>{elapsedDisplay}</MonoTicker>
        </div>
      </div>
    );
  };

  // Visible log lines depend on progress
  const visibleLogs = (logLines.length ? logLines : SAMPLE_LOG_LINES).slice(0, Math.min((logLines.length ? logLines : SAMPLE_LOG_LINES).length, sim.currentNodeIdx + 3));

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>

      {/* Top bar of run page */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "14px 24px", borderBottom: "1px solid var(--border)",
        background: "var(--surface)", flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
          <StatusPill status={runStatusForPill}/>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: -0.1 }}>{company} · {role}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 2, flexWrap: "wrap" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-faint)" }}>{threadId || "thr_8af2c01d"}</span>
              {startedLabel && <><span style={{ fontSize: 11, color: "var(--text-faint)" }}>·</span>
              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{startedLabel}</span></>}
              <span style={{ fontSize: 11, color: "var(--text-faint)" }}>·</span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <span style={{ width: 5, height: 5, borderRadius: 99, background: "var(--success)" }}/>
                <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>via {viaModel} · {wsStatus}</span>
              </span>
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {/* Mini playback controls — demo simulation only */}
          {isDemo && (
            <div style={{
              display: "flex", alignItems: "center", gap: 1, padding: 3,
              border: "1px solid var(--border)", borderRadius: "var(--radius-md)", background: "var(--surface)",
            }}>
              <IconButton name="rewind" label="Step back" onClick={() => { setAutoplay(false); setManualIdx(i => Math.max(0, (i ?? sim.currentNodeIdx) - 1)); }} />
              <IconButton name={autoplay ? "pause" : "play"} label="Autoplay" active={autoplay}
                onClick={() => setAutoplay(a => !a)} />
              <IconButton name="ff" label="Step forward" onClick={() => { setAutoplay(false); setManualIdx(i => Math.min(PIPELINE_NODES.length, (i ?? sim.currentNodeIdx) + 1)); }} />
            </div>
          )}
          {threadId && !sim.completed && !sim.failed && (
            <Button size="sm" variant="secondary" icon="x" onClick={cancel} disabled={cancelling}>{cancelling ? "Cancelling…" : "Cancel run"}</Button>
          )}
        </div>
      </div>

      {/* Three columns */}
      <div style={{
        display: "grid",
        gridTemplateColumns: pdfCollapsed ? "minmax(240px, 320px) minmax(0, 1fr) 36px"
                                          : "minmax(240px, 320px) minmax(0, 1fr) minmax(320px, 520px)",
        gap: 1,
        flex: 1, minHeight: 0,
        background: "var(--border)",
        transition: "grid-template-columns 320ms var(--ease-spring)",
      }}>
        {/* LEFT — timeline */}
        <div style={{ background: "var(--bg)", display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={{ padding: density === "compact" ? "10px 14px" : "14px 16px 8px", flexShrink: 0 }}>
            <div className="mono" style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 8 }}>Pipeline</div>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
              <span style={{ fontSize: 13.5, color: "var(--text)" }}>{PIPELINE_NODES.length} nodes</span>
              <MonoTicker style={{ color: "var(--text-muted)" }}>{elapsedDisplay}</MonoTicker>
            </div>
          </div>
          <div style={{ flex: 1, overflow: "auto", padding: "4px 6px 6px" }}>
            <PipelineTimeline
              events={sim.events} currentNodeIdx={sim.currentNodeIdx}
              density={density}
              isPaused={sim.isPaused}
              selectedIdx={selectedIdx}
              retryFor={sim.retryFor}
              retryCount={sim.failed ? 5 : 2}
              onNodeClick={(i) => setSelectedIdx(i === selectedIdx ? null : i)}
            />
          </div>
          <LogTail visibleLines={visibleLogs} density={density}/>
        </div>

        {/* MIDDLE — activity / HITL */}
        <div style={{
          background: "var(--bg)", overflow: "auto", minHeight: 0,
        }}>
          {renderActivity()}
        </div>

        {/* RIGHT — PDF preview (collapsible) */}
        <div style={{ background: "var(--bg)", display: "flex", flexDirection: "column", minHeight: 0, position: "relative" }}>
          {pdfCollapsed ? (
            <button onClick={() => setPdfCollapsed(false)} title="Show PDF preview"
              style={{
                width: "100%", height: "100%", background: "var(--surface)",
                border: "none", cursor: "pointer",
                display: "flex", flexDirection: "column", alignItems: "center", gap: 14,
                padding: "16px 0", color: "var(--text-muted)",
                transition: "background var(--t-fast), color var(--t-fast)",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--surface-2)"; e.currentTarget.style.color = "var(--text)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "var(--surface)"; e.currentTarget.style.color = "var(--text-muted)"; }}
            >
              <Icon name="chevron-up" size={14} style={{ transform: "rotate(-90deg)" }}/>
              <span style={{
                writingMode: "vertical-rl", transform: "rotate(180deg)",
                fontSize: 11.5, fontWeight: 500, letterSpacing: 0.5,
              }} className="mono">
                {sim.completed ? "PDF preview" : "PDF (pending)"}
              </span>
              <Icon name="file-text" size={14}/>
            </button>
          ) : (
            <PDFPreviewPane visible={pdfVisible} scale={pdfScale} setScale={setPdfScale} page={pdfPage} setPage={setPdfPage} onCollapse={() => setPdfCollapsed(true)} pdfUrl={downloadUrl} pdfName={pdfName} isDemo={isDemo}/>
          )}
        </div>
      </div>
    </div>
  );
};

export { LiveRunView };

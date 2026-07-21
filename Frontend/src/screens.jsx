import React from "react";
import { Icon } from "./icons.jsx";
import { Button, IconButton, StatusPill, Card, Input, Textarea, Tabs, Badge, Toggle, EmptyState, SectionHeader, MonoTicker, Kbd, UploadDropzone } from "./components.jsx";
import { createRun, listRuns, getResume, getResumeRaw, updateResume, getSettings, getProviders, updateSettings, testConnection, runDoctor, listLibraryResumes, pdfUrl, uploadJdFile } from "./api/client.js";
import { ACTIVE_LLM, PROVIDERS, PROVIDER_MODELS, PROVIDER_VISION_MODELS, PARSE_STAGES } from "./data.jsx";

// Fetch the live provider catalogue (A4); fall back to the static data.jsx
// catalogue until the request resolves.
const useProviders = () => {
  const [data, setData] = React.useState({ providers: PROVIDERS, models: PROVIDER_MODELS, visionModels: PROVIDER_VISION_MODELS });
  React.useEffect(() => {
    getProviders()
      .then(res => { if (res?.providers?.length) setData({ providers: res.providers, models: res.models || {}, visionModels: res.visionModels || {} }); })
      .catch(() => {});
  }, []);
  return data;
};

// Keep the currently-selected model visible even if it isn't in the catalogue (B2).
const withCurrent = (list, current) => (current && !(list || []).includes(current) ? [current, ...(list || [])] : (list || []));

// All screens except live-run.

const normalizeRun = (run) => ({
  id: run.id || run.thread_id,
  company: run.company || "Unknown",
  role: run.role || "Unknown",
  date: run.date || (run.created_at ? new Date(run.created_at * 1000).toLocaleString() : "Just now"),
  ts: run.created_at || null,
  status: run.status || "queued",
  duration: run.duration || "-",
  retries: run.retries || 0,
  pdf: run.pdf || null,
  pdf_url: run.pdf_url || null,
  hitlDetail: run.hitlDetail || (run.status === "awaiting-input" ? "Input needed to continue" : null),
});

const useRuns = () => {
  const [runs, setRuns] = React.useState([]);
  React.useEffect(() => {
    let alive = true;
    const fetch = () => listRuns()
      .then(items => { if (alive && Array.isArray(items)) setRuns(items.map(normalizeRun)); })
      .catch(() => { if (alive) setRuns([]); });
    fetch();
    const id = setInterval(fetch, 5000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  return runs;
};

const resumeForUi = (resume) => {
  if (!resume?.personal) return null;
  return {
    profile: {
      name: resume.personal.full_name,
      email: resume.personal.email,
      phone: resume.personal.phone,
      location: resume.personal.location,
      linkedin: resume.personal.linkedin,
      github: resume.personal.github,
      website: resume.personal.website,
      portfolio: resume.personal.portfolio,
      summary: resume.summary,
    },
    experience: (resume.experience || []).map((role, i) => ({
      id: `e${i + 1}`,
      role: role.title,
      company: role.company,
      location: role.location,
      start: role.start,
      end: role.end || "Present",
      bullets: role.bullets || [],
      tech: (role.tech || []).join(", "),
    })),
    projects: (resume.projects || []).map((project, i) => ({
      id: `p${i + 1}`,
      name: project.name,
      url: project.url,
      tech: (project.tech || []).join(", "),
      bullets: project.bullets || [],
    })),
    education: resume.education || [],
    skills: resume.skills || {},
  };
};

// ============== DASHBOARD ==============

// 14-day run history
const computeActivity = (runs, days = 14) => {
  const now = Date.now();
  const buckets = Array(days).fill(0);
  runs.forEach(run => {
    if (!run.ts) return;
    const dayIndex = days - 1 - Math.floor((now - run.ts * 1000) / 86400000);
    if (dayIndex >= 0 && dayIndex < days) buckets[dayIndex]++;
  });
  return buckets;
};

const parseDurationSecs = (d) => {
  if (!d || d === "-") return null;
  const m = parseInt(d.match(/(\d+)m/)?.[1] || 0);
  const s = parseInt(d.match(/(\d+)s/)?.[1] || 0);
  return m * 60 + s;
};

const timeAgo = (ts) => {
  if (!ts) return "";
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
};

const useSettings = () => {
  const [settings, setSettings] = React.useState(ACTIVE_LLM);
  React.useEffect(() => { getSettings().then(setSettings).catch(() => {}); }, []);
  return settings;
};

const Dashboard = ({ goto, openRun, locked, doctor }) => {
  const runs = useRuns();
  const settings = useSettings();
  const [tab, setTab] = React.useState("overview");

  const totalRuns = runs.length;
  const activityData = computeActivity(runs);
  const durations = runs.map(r => parseDurationSecs(r.duration)).filter(n => n !== null);
  const avgDuration = durations.length
    ? (() => { const a = Math.round(durations.reduce((x, y) => x + y, 0) / durations.length); return a >= 60 ? `${Math.floor(a / 60)}m ${a % 60}s` : `${a}s`; })()
    : "—";
  const completed = runs.filter(r => r.status === "complete").length;
  const failed = runs.filter(r => r.status === "failed").length;
  const companies = Array.from(new Set(runs.map(r => r.company)));
  const doctorOk = doctor ? doctor.ok : true;
  const doctorFailing = (doctor?.checks || []).filter(c => !c.ok).length;

  const weekCount = activityData.slice(-7).reduce((a, b) => a + b, 0);
  const needsInput = runs.filter(r => r.status === "awaiting-input").length;
  const successRate = totalRuns ? Math.round((completed / totalRuns) * 100) : 0;
  // Full lists for tab content (no artificial cap)
  const activeRuns = runs.filter(r => ["running", "awaiting-input", "queued", "retrying"].includes(r.status));
  const activeRunsSummary = activeRuns.slice(0, 3);
  const completedRuns = runs.filter(r => r.status === "complete");
  const recentDone = completedRuns.slice(0, 4);
  const needsRuns = runs.filter(r => r.status === "awaiting-input");
  const failedRuns = runs.filter(r => r.status === "failed");
  const activityFeed = [...runs].sort((a, b) => (b.ts || 0) - (a.ts || 0)).slice(0, 5);
  const maxBar = Math.max(1, ...activityData);

  const Stat = ({ icon, label, value, sub, alert }) => (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", background: "var(--surface)", padding: "15px 16px 13px", boxShadow: alert ? "0 0 0 1px var(--text) inset" : "none" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12.5, color: "var(--text-muted)", fontWeight: 500 }}>
        <Icon name={icon} size={15} style={{ color: "var(--text-faint)" }}/>{label}
      </div>
      <div className="serif" style={{ fontSize: 32, fontWeight: 800, letterSpacing: -1, lineHeight: 1.15, marginTop: 6, fontVariantNumeric: "tabular-nums" }}>{value}</div>
      <div style={{ marginTop: 3, fontSize: 12, color: "var(--text-faint)" }}>{sub}</div>
    </div>
  );

  const RunRow = ({ r }) => {
    const needsYou = r.status === "awaiting-input";
    const done = r.status === "complete";
    const bad = r.status === "failed";
    const tone = needsYou ? { bg: "var(--warning-soft)", fg: "var(--warning)", ic: "alert" }
      : bad ? { bg: "var(--danger-soft)", fg: "var(--danger)", ic: "x" }
      : done ? { bg: "var(--success-soft)", fg: "var(--success)", ic: "file-text" }
      : { bg: "var(--info-soft)", fg: "var(--info)", ic: "loader" };
    return (
      <div onClick={() => openRun(r.id, r.status, r)} style={{
        display: "flex", alignItems: "center", gap: 13, flexWrap: "wrap",
        border: "1px solid " + (needsYou ? "var(--border-strong)" : "var(--border)"),
        borderRadius: "var(--radius-lg)", padding: "13px 15px", background: "var(--surface)", cursor: "pointer",
      }}
        onMouseEnter={(e) => e.currentTarget.style.borderColor = "var(--border-strong)"}
        onMouseLeave={(e) => e.currentTarget.style.borderColor = needsYou ? "var(--border-strong)" : "var(--border)"}
      >
        <span style={{ width: 40, height: 40, borderRadius: 10, flexShrink: 0, display: "grid", placeItems: "center", background: tone.bg, color: tone.fg }}>
          <Icon name={tone.ic} size={16}/>
        </span>
        <div style={{ minWidth: 150, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 14, fontWeight: 600 }}>
            <span className={r.pdf ? "mono" : ""} style={{ fontSize: r.pdf ? 12.5 : 14 }}>{r.pdf || `${r.company} — ${r.role}`}</span>
            <StatusPill status={r.status} size="sm"/>
          </div>
          <div style={{ fontSize: 12.5, color: "var(--text-faint)", marginTop: 2 }}>
            {r.company} · {r.role}<span className="mono"> · {r.duration !== "-" ? r.duration : r.date}</span>
          </div>
        </div>
        {needsYou
          ? <Button size="sm" variant="primary" iconRight="arrow-right">Answer</Button>
          : bad ? <Button size="sm" variant="secondary" icon="refresh">Retry</Button>
          : done && r.pdf_url ? <IconButton name="download" label="Download" onClick={(e) => { e.stopPropagation(); window.open(pdfUrl(r.id), "_blank"); }}/>
          : <IconButton name="arrow-right" label="Open" onClick={(e) => { e.stopPropagation(); openRun(r.id, r.status, r); }}/>}
      </div>
    );
  };

  const kvRow = (k, v, last) => (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "7px 0", borderBottom: last ? "none" : "1px dashed var(--border)", fontSize: 13 }}>
      <span style={{ color: "var(--text-muted)" }}>{k}</span><span className="mono truncate" style={{ fontWeight: 600, maxWidth: 160, textAlign: "right" }}>{v}</span>
    </div>
  );

  // ── Tab definitions ──
  const TABS = [
    { id: "overview", label: "Overview", count: null },
    { id: "active", label: "Active runs", count: activeRuns.length },
    { id: "final", label: "Resumes", count: completedRuns.length },
    { id: "needs", label: "Questions asked", count: needsRuns.length },
    { id: "failed", label: "Failures", count: failedRuns.length },
  ];

  // ── Run-list view (used by active / final / needs / failed tabs) ──
  const RunListView = ({ items, emptyIcon, emptyTitle, emptySub, fullLibraryLink }) => {
    if (items.length === 0) {
      return (
        <Card padding={0}>
          <EmptyState icon={emptyIcon} title={emptyTitle} sub={emptySub}
            action={fullLibraryLink ? <Button variant="secondary" iconRight="arrow-right" onClick={() => goto("library")}>Open full library</Button> : null}/>
        </Card>
      );
    }
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {items.map(r => <RunRow key={r.id} r={r}/>)}
      </div>
    );
  };

  // ── Render tab content ──
  const renderTabContent = () => {
    switch (tab) {
      case "active":
        return <RunListView items={activeRuns} emptyIcon="check-circle" emptyTitle="No active runs" emptySub="Start a tailored resume and it will show up here live." fullLibraryLink/>;
      case "final":
        return <RunListView items={completedRuns} emptyIcon="folder" emptyTitle="No resumes filed yet" emptySub="Your generated PDFs will be filed here by company." fullLibraryLink/>;
      case "needs":
        return <RunListView items={needsRuns} emptyIcon="check-circle" emptyTitle="Nothing needs your attention" emptySub="All questions have been answered. Good work." fullLibraryLink/>;
      case "failed":
        return <RunListView items={failedRuns} emptyIcon="check-circle" emptyTitle="No failures" emptySub="Every run has succeeded so far." fullLibraryLink/>;
      default: // overview
        return (
          <div className="two-col-grid" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.9fr) minmax(280px, 1fr)", gap: 24, alignItems: "start" }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "4px 0 12px" }}>
                <span style={{ fontSize: 16, fontWeight: 700 }}>Active runs</span>
                <span className="mono" style={{ fontSize: 11.5, color: "var(--text-muted)", background: "var(--surface-2)", borderRadius: 99, padding: "2px 9px" }}>{activeRuns.length} live</span>
              </div>
              {activeRunsSummary.length === 0
                ? <Card padding={0}><EmptyState icon="check-circle" title="No active runs" sub="Start a tailored resume and it will show up here live."/></Card>
                : <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>{activeRunsSummary.map(r => <RunRow key={r.id} r={r}/>)}</div>}

              <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "26px 0 12px" }}>
                <span style={{ fontSize: 16, fontWeight: 700 }}>Recent resumes</span>
                <span className="mono" style={{ fontSize: 11.5, color: "var(--text-muted)", background: "var(--surface-2)", borderRadius: 99, padding: "2px 9px" }}>{completed} filed</span>
              </div>
              {recentDone.length === 0
                ? <Card padding={0}><EmptyState icon="folder" title="No resumes filed yet" sub="Your generated PDFs will be filed here by company." action={<Button variant="primary" iconRight="arrow-right" onClick={() => goto("new")}>Create a résumé</Button>}/></Card>
                : <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>{recentDone.map(r => <RunRow key={r.id} r={r}/>)}</div>}
            </div>

            {/* right column */}
            <div style={{ display: "flex", flexDirection: "column", gap: 18, minWidth: 0 }}>
              <Card padding={18}>
                <div style={{ display: "flex", alignItems: "center", fontSize: 15, fontWeight: 700 }}>
                  Activity
                  <button onClick={() => goto("library")} style={{ marginLeft: "auto", background: "transparent", border: "none", cursor: "pointer", fontSize: 12.5, fontWeight: 600, color: "var(--text-muted)" }}>See all</button>
                </div>
                {activityFeed.length === 0 ? (
                  <div style={{ fontSize: 12.5, color: "var(--text-faint)", marginTop: 12 }}>No activity yet — start a run to see it here.</div>
                ) : (
                  <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 14 }}>
                    {activityFeed.map(r => {
                      const tone = r.status === "awaiting-input" ? { bg: "var(--warning-soft)", fg: "var(--warning)", ic: "alert" }
                        : r.status === "failed" ? { bg: "var(--danger-soft)", fg: "var(--danger)", ic: "x" }
                        : r.status === "complete" ? { bg: "var(--success-soft)", fg: "var(--success)", ic: "check" }
                        : { bg: "var(--info-soft)", fg: "var(--info)", ic: "loader" };
                      const verb = r.status === "awaiting-input" ? "is waiting on your input"
                        : r.status === "failed" ? "failed to generate"
                        : r.status === "complete" ? "filed — ready to send"
                        : "is generating";
                      return (
                        <div key={r.id} onClick={() => openRun(r.id, r.status, r)} style={{ display: "flex", gap: 10, cursor: "pointer" }}>
                          <span style={{ width: 26, height: 26, borderRadius: 99, flexShrink: 0, display: "grid", placeItems: "center", background: tone.bg, color: tone.fg }}>
                            <Icon name={tone.ic} size={12} stroke={2.4}/>
                          </span>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: 12.5, lineHeight: 1.4 }}><b style={{ fontWeight: 600 }}>{r.company}</b> {verb}</div>
                            <div className="mono" style={{ fontSize: 10.5, color: "var(--text-faint)", marginTop: 2 }}>{r.role} · {timeAgo(r.ts)}</div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </Card>

              <Card padding={18}>
                <div style={{ display: "flex", alignItems: "center", fontSize: 15, fontWeight: 700 }}>
                  This week
                  <button onClick={() => goto("library")} style={{ marginLeft: "auto", background: "transparent", border: "none", cursor: "pointer", fontSize: 12.5, fontWeight: 600, color: "var(--text-muted)" }}>Details</button>
                </div>
                <div style={{ display: "flex", alignItems: "flex-end", gap: 5, height: 74, marginTop: 14 }}>
                  {activityData.map((v, i) => (
                    <div key={i} title={`${v} run${v === 1 ? "" : "s"}`} style={{ flex: 1, height: `${Math.max(6, (v / maxBar) * 100)}%`, borderRadius: "4px 4px 2px 2px", background: i >= activityData.length - 3 ? "var(--text)" : "var(--surface-3)" }}/>
                  ))}
                </div>
                <div style={{ marginTop: 14 }}>
                  {kvRow("Completed", completed)}
                  {kvRow("Failed", failed)}
                  {kvRow("Avg generation", avgDuration, true)}
                </div>
              </Card>

              <Card padding={18}>
                <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>Engine</div>
                {kvRow("Provider", settings.providerName || settings.provider)}
                {kvRow("Model", settings.defaultModel)}
                {kvRow("Doctor", doctor ? (doctorOk ? "all checks ok" : `${doctorFailing} issue${doctorFailing === 1 ? "" : "s"}`) : "checking…", true)}
                <Button variant="secondary" onClick={() => goto("settings")} style={{ width: "100%", marginTop: 12, justifyContent: "center" }}>Open settings</Button>
              </Card>

              {companies.length > 0 && (
                <Card padding={18}>
                  <div style={{ display: "flex", alignItems: "baseline", marginBottom: 12 }}><span style={{ fontSize: 15, fontWeight: 700 }}>Companies</span><span className="mono" style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-faint)" }}>{companies.length}</span></div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {companies.map(c => (
                      <button key={c} onClick={() => goto("companies")} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 10px", background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: 99, fontSize: 11.5, cursor: "pointer" }}>
                        <span style={{ width: 15, height: 15, borderRadius: 4, background: "var(--accent-soft)", color: "var(--accent)", display: "grid", placeItems: "center", fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 700 }}>{c[0]}</span>
                        {c}<span className="mono" style={{ fontSize: 10, color: "var(--text-faint)" }}>{runs.filter(r => r.company === c).length}</span>
                      </button>
                    ))}
                  </div>
                </Card>
              )}
            </div>
          </div>
        );
    }
  };

  return (
    <div className="page-pad" style={{ padding: "24px 32px 48px", maxWidth: 1500, margin: "0 auto" }}>
      <div className="mono" style={{ fontSize: 11, letterSpacing: 0.6, color: "var(--text-faint)", textTransform: "uppercase", marginBottom: 8 }}>Workspace / Overview</div>

      {/* head */}
      <div style={{ display: "flex", alignItems: "flex-end", gap: 18, flexWrap: "wrap" }}>
        <div style={{ minWidth: 0 }}>
          <div className="serif" style={{ fontSize: 34, fontWeight: 800, letterSpacing: -1.2, lineHeight: 1.05 }}>
            Job hunt, on autopilot.
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginTop: 10, fontSize: 13, color: "var(--text-muted)" }}>
            {new Date().toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })}
            <span style={{ color: "var(--border-strong)" }}>·</span>
            {weekCount} this week
            {needsInput > 0 && <span style={{ display: "inline-flex", alignItems: "center", gap: 6, background: "var(--warning-soft)", color: "var(--warning)", fontWeight: 600, fontSize: 12, padding: "3px 10px", borderRadius: 7 }}>{needsInput} need{needsInput === 1 ? "s" : ""} your input</span>}
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, border: "1px solid var(--border)", borderRadius: 7, padding: "3px 10px", fontSize: 12 }}>
              <span style={{ width: 6, height: 6, borderRadius: 99, background: "var(--success)" }}/>
              <span className="mono truncate" style={{ maxWidth: 180 }}>{settings.defaultModel}{settings.latencyMs != null ? ` · ${settings.latencyMs}ms` : ""}</span>
            </span>
          </div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Button variant="secondary" icon="upload" onClick={() => goto("resume")}>Replace base resume</Button>
          <Button variant="primary" icon="play" disabled={locked} onClick={() => !locked && goto("new")}>New tailored resume</Button>
        </div>
      </div>

      {/* In-page tabs — switch content within the Dashboard, no navigation away. */}
      <div style={{ display: "flex", gap: 2, borderBottom: "1px solid var(--border)", marginTop: 22, overflowX: "auto" }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            display: "inline-flex", alignItems: "center", gap: 7,
            padding: "10px 14px", background: "transparent", border: "none",
            cursor: "pointer", fontSize: 13.5, fontWeight: tab === t.id ? 600 : 500, whiteSpace: "nowrap",
            color: tab === t.id ? "var(--text)" : "var(--text-muted)",
            borderBottom: "2px solid " + (tab === t.id ? "var(--text)" : "transparent"), marginBottom: -1,
            transition: `color var(--t-fast), border-color var(--t-fast)`,
          }}>
            {t.label}
            {t.count != null && (
              <span className="mono" style={{
                fontSize: 10.5, padding: "1px 6px", borderRadius: 99,
                background: tab === t.id ? "var(--text)" : "var(--surface-2)",
                color: tab === t.id ? "var(--bg)" : "var(--text-muted)",
                fontWeight: 600,
              }}>{t.count}</span>
            )}
          </button>
        ))}
        <span style={{ flex: 1, borderBottom: "2px solid transparent", marginBottom: -1 }}/>
        <button onClick={() => goto("companies")} style={{
          display: "inline-flex", alignItems: "center", gap: 5,
          padding: "10px 14px", background: "transparent", border: "none",
          cursor: "pointer", fontSize: 13.5, fontWeight: 500, whiteSpace: "nowrap",
          color: "var(--text-muted)", marginBottom: -1,
        }}
          onMouseEnter={(e) => { e.currentTarget.style.color = "var(--text)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = "var(--text-muted)"; }}
        >Companies <Icon name="arrow-right" size={12} style={{ opacity: 0.5 }}/></button>
      </div>

      {/* KPI stats — visible on every tab */}
      <div className="kpi-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, margin: "22px 0" }}>
        <Stat icon="file-text" label="Resumes generated" value={completed} sub={<><span style={{ color: "var(--success)", fontWeight: 600 }}>+{weekCount}</span> this week</>}/>
        <Stat icon="check-circle" label="Success rate" value={`${successRate}%`} sub={`${completed} of ${totalRuns || 0} compiled`}/>
        <Stat icon="loader" label="Avg generation" value={avgDuration} sub="across all runs"/>
        <Stat icon="alert" label="Needs your input" value={needsInput} alert sub={needsInput ? <span style={{ color: "var(--warning)", fontWeight: 600 }}>waiting on you</span> : "all clear"}/>
        <Stat icon="building" label="Companies" value={companies.length} sub="targeted"/>
      </div>

      {/* Tab content */}
      <div key={tab} className="route-in">
        {renderTabContent()}
      </div>
    </div>
  );
};

// ============== SETUP / ONBOARDING ==============
const ProviderLogo = ({ p, size = 28 }) => (
  <span style={{
    width: size, height: size, borderRadius: 6,
    background: "var(--surface-2)",
    border: "1px solid var(--border)",
    color: "var(--text)",
    display: "inline-flex", alignItems: "center", justifyContent: "center",
    fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: size * 0.5,
    flexShrink: 0,
  }}>{p.logo}</span>
);

const SetupWizard = ({ goto, startParse, parsing }) => {
  const TOTAL = 5;
  const { providers, models, visionModels } = useProviders();
  const [step, setStep] = React.useState(1);
  const [providerId, setProviderId] = React.useState("anthropic");
  const provider = providers.find(p => p.id === providerId) || providers[0] || {};
  const [apiKey, setApiKey] = React.useState("");
  const [showKey, setShowKey] = React.useState(false);
  const [baseUrl, setBaseUrl] = React.useState("http://localhost:11434");
  const [keyTested, setKeyTested] = React.useState(null); // null | running | ok | fail
  const [defaultModel, setDefaultModel] = React.useState("");
  const [visionEnabled, setVisionEnabled] = React.useState(true);
  const [visionModel, setVisionModel] = React.useState("");
  const [testing, setTesting] = React.useState(null); // null | "running" | "ok" | "fail"
  const [testResult, setTestResult] = React.useState(null);
  const [doctor, setDoctor] = React.useState(null);

  // Seed from the real configured provider rather than always Anthropic (C6).
  React.useEffect(() => {
    getSettings().then(s => {
      if (s.providerId || s.provider) setProviderId(s.providerId || s.provider);
      if (s.defaultModel) setDefaultModel(s.defaultModel);
      if (s.visionModel) setVisionModel(s.visionModel);
      setVisionEnabled(!!s.visionEnabled);
      if (s.baseUrl) setBaseUrl(s.baseUrl);
    }).catch(() => {});
  }, []);

  const selectProvider = (pid) => {
    setProviderId(pid);
    setDefaultModel((models[pid] || [""])[0] || "");
    setVisionModel((visionModels[pid] || [""])[0] || "");
    if (pid === "ollama_local") { setApiKey(""); setBaseUrl("http://localhost:11434"); }
    else if (pid === "ollama_remote") setBaseUrl("https://ollama.example.com");
    setKeyTested(null);
  };

  const stepNames = ["Provider", "Credentials", "Vision", "System check", "Base resume"];
  const isOllama = providerId === "ollama_local" || providerId === "ollama_remote";
  const isOllamaLocal = providerId === "ollama_local";
  const needsKeyNow = !!provider.needsKey && !isOllama;
  const credsValid = needsKeyNow ? apiKey.length > 8 : true;

  // Real key check — round-trips to the provider instead of measuring key length (C6).
  const testKey = async () => {
    setKeyTested("running");
    try {
      const r = await testConnection({ provider: providerId, default_model: defaultModel, base_url: baseUrl, api_key: apiKey || undefined });
      setKeyTested(r.ok ? "ok" : "fail");
    } catch {
      setKeyTested("fail");
    }
  };

  const runConnectionTest = async () => {
    setTesting("running");
    runDoctor().then(setDoctor).catch(() => setDoctor(null));
    try {
      const result = await testConnection({
        provider: providerId,
        default_model: defaultModel,
        vision_model: visionEnabled ? visionModel : defaultModel,
        base_url: baseUrl,
        api_key: apiKey || undefined,
      });
      setTestResult(result);
      setTesting(result.ok ? "ok" : "fail");
    } catch {
      setTesting("fail");
    }
  };

  const persistSettings = () => updateSettings({
    provider: providerId,
    default_model: defaultModel,
    vision_model: visionModel,
    vision_enabled: visionEnabled,
    base_url: baseUrl || undefined,
    api_key: apiKey || undefined,
  }).catch(() => {});

  return (
    <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", padding: 40, overflow: "auto" }}>
      <div style={{ width: "100%", maxWidth: 660 }}>

        {/* Stepper */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, justifyContent: "center", marginBottom: 24, flexWrap: "wrap" }}>
          {stepNames.map((name, i) => {
            const n = i + 1;
            return (
              <React.Fragment key={n}>
                <button onClick={() => n < step && setStep(n)} style={{
                  display: "flex", alignItems: "center", gap: 7,
                  padding: "4px 8px",
                  background: "transparent", border: "none",
                  color: n === step ? "var(--text)" : n < step ? "var(--success)" : "var(--text-faint)",
                  fontSize: 12, fontWeight: n === step ? 600 : 500,
                  cursor: n < step ? "pointer" : "default",
                }}>
                  <span style={{
                    width: 22, height: 22, borderRadius: 99,
                    background: n < step ? "var(--success)" : n === step ? "var(--accent)" : "var(--surface-2)",
                    color: n < step ? "white" : n === step ? "var(--accent-contrast)" : "var(--text-muted)",
                    border: "1px solid " + (n === step ? "var(--accent)" : n < step ? "var(--success)" : "var(--border-strong)"),
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 11, fontWeight: 600,
                  }} className="mono">
                    {n < step ? <Icon name="check" size={11} stroke={3}/> : n}
                  </span>
                  <span style={{ whiteSpace: "nowrap" }}>{name}</span>
                </button>
                {n < TOTAL && <div style={{ width: 14, height: 1, background: "var(--border)" }}/>}
              </React.Fragment>
            );
          })}
        </div>

        <Card padding={28}>
          <div key={step} className="route-in">

          {/* STEP 1 — PROVIDER */}
          {step === 1 && (
            <div>
              <SectionHeader eyebrow={`Step 1 of ${TOTAL} · Provider`} title="Pick a model provider" sub="Any of these work — you can change later in Settings."/>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10, marginBottom: 8 }}>
                {providers.map(p => (
                  <button key={p.id} onClick={() => selectProvider(p.id)}
                    style={{
                      position: "relative", textAlign: "left",
                      padding: "14px", borderRadius: "var(--radius-md)",
                      background: providerId === p.id ? "var(--accent-soft)" : "var(--surface)",
                      border: "1px solid " + (providerId === p.id ? "var(--accent)" : "var(--border)"),
                      cursor: "pointer", transition: `all var(--t-fast)`,
                      display: "flex", gap: 12, alignItems: "flex-start",
                    }}>
                    <ProviderLogo p={p}/>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ fontSize: 13.5, fontWeight: 600 }}>{p.name}</span>
                        {p.recommended && (
                          <span style={{ fontSize: 9.5, padding: "1px 6px", background: "var(--accent)", color: "var(--accent-contrast)", borderRadius: 99, fontWeight: 600, letterSpacing: 0.3, textTransform: "uppercase" }}>Rec</span>
                        )}
                      </div>
                      <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 2 }}>{p.sub}</div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
                        <span className="mono" style={{ fontSize: 10.5, color: "var(--text-faint)" }}>{p.cost}</span>
                        {p.hint && <><span style={{ color: "var(--text-faint)" }}>·</span><span style={{ fontSize: 11, color: "var(--text-muted)" }}>{p.hint}</span></>}
                      </div>
                    </div>
                  </button>
                ))}
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 22 }}>
                <Button variant="primary" iconRight="arrow-right" onClick={() => setStep(2)}>Continue</Button>
              </div>
            </div>
          )}

          {/* STEP 2 — CREDENTIALS + DEFAULT MODEL */}
          {step === 2 && (
            <div>
              <SectionHeader eyebrow={`Step 2 of ${TOTAL} · Credentials & model`} title={
                <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
                  <ProviderLogo p={provider} size={26}/>{provider.name} · {provider.sub}
                </span>
              } sub={provider.url ? <>Get an API key at <span className="mono" style={{ color: "var(--text)" }}>{provider.url}</span></> : "No API key required."}/>

              {/* Credentials */}
              {needsKeyNow && (
                <div style={{ marginBottom: 18 }}>
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>API key · saved to <span className="mono" style={{ color: "var(--text-faint)" }}>~/.resume_generator/.env</span></div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <Input type={showKey ? "text" : "password"} value={apiKey}
                      onChange={(e) => { setApiKey(e.target.value); setKeyTested(null); }}
                      placeholder={providerId === "anthropic" ? "sk-ant-api03-…" : providerId === "openai" ? "sk-proj-…" : "your key"}
                      style={{ flex: 1 }}
                      suffix={<IconButton name={showKey ? "eye-off" : "eye"} label="Toggle visibility" onClick={() => setShowKey(s => !s)}/>}
                    />
                    <Button variant="secondary" disabled={!apiKey || keyTested === "running"} onClick={testKey}>{keyTested === "running" ? "Testing…" : "Test key"}</Button>
                  </div>
                  {keyTested === "ok"   && <div className="mono" style={{ fontSize: 11.5, color: "var(--success)", marginTop: 6 }}>✓ verified · model responded</div>}
                  {keyTested === "fail" && <div className="mono" style={{ fontSize: 11.5, color: "var(--danger)",  marginTop: 6 }}>✗ rejected — check the key and try again</div>}
                </div>
              )}

              {isOllama && (
                <div style={{ marginBottom: 18 }}>
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>Base URL</div>
                  <Input icon="link" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}/>
                  {!isOllamaLocal && (
                    <div style={{ marginTop: 10 }}>
                      <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>API key <span style={{ color: "var(--text-faint)" }}>(if your server requires one)</span></div>
                      <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="bearer token"/>
                    </div>
                  )}
                </div>
              )}

              {/* Default (text) model */}
              <div>
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6, display: "flex", alignItems: "center", gap: 6 }}>
                  Text / reasoning model
                  <Icon name="info" size={11} style={{ color: "var(--text-faint)" }}/>
                </div>
                <ModelGrid value={defaultModel} onChange={setDefaultModel}
                  options={withCurrent(models[providerId], defaultModel)}
                  recommended={(models[providerId] || [])[0]}/>
              </div>

              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 24 }}>
                <Button variant="ghost" icon="arrow-left" onClick={() => setStep(1)}>Back</Button>
                <Button variant="primary" iconRight="arrow-right" disabled={!credsValid} onClick={() => setStep(3)}>Continue</Button>
              </div>
            </div>
          )}

          {/* STEP 3 — VISION */}
          {step === 3 && (
            <div>
              <SectionHeader eyebrow={`Step 3 of ${TOTAL} · Vision`} title="Vision validation" sub="A multimodal model inspects the compiled PDF for layout issues (overlapping text, cut-off sections). Used in the validate_alignment step."/>

              <Card padding={16} style={{ background: "var(--surface-2)", marginBottom: 16 }}>
                <Toggle checked={visionEnabled} onChange={setVisionEnabled}
                  label="Enable vision validation"
                  sub="Adds ~6s to each run. Skips on failures rather than blocking the pipeline."/>
              </Card>

              {visionEnabled && (
                <>
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>Vision model</div>
                  <ModelGrid value={visionModel} onChange={setVisionModel}
                    options={withCurrent(visionModels[providerId], visionModel)}
                    recommended={(visionModels[providerId] || [])[0]}/>
                </>
              )}

              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 24 }}>
                <Button variant="ghost" icon="arrow-left" onClick={() => setStep(2)}>Back</Button>
                <Button variant="primary" iconRight="arrow-right" onClick={() => { setStep(4); runConnectionTest(); }}>Continue</Button>
              </div>
            </div>
          )}

          {/* STEP 4 — DOCTOR + TEST */}
          {step === 4 && (
            <div>
              <SectionHeader eyebrow={`Step 4 of ${TOTAL} · System check`} title="Doctor &amp; connection test" sub="Verifying binaries and saying hello to your LLM."/>

              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
                {doctor === null && <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "6px 2px" }}>Running environment checks…</div>}
                {(doctor?.checks || []).map(r => (
                  <div key={r.label} style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10,
                    padding: "11px 14px", border: "1px solid var(--border)", borderRadius: "var(--radius-md)",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                      <span style={{ width: 22, height: 22, borderRadius: 99, flexShrink: 0,
                        background: r.ok ? "var(--success-soft)" : "var(--danger-soft)",
                        color: r.ok ? "var(--success)" : "var(--danger)",
                        display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <Icon name={r.ok ? "check" : "x"} size={11} stroke={3}/>
                      </span>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 500 }}>{r.label}</div>
                        {!r.ok && r.hint && <div className="truncate" style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{r.hint}</div>}
                      </div>
                    </div>
                    <span className="mono" style={{ fontSize: 11.5, color: r.ok ? "var(--success)" : "var(--danger)" }}>{r.ok ? "ok" : "fail"}</span>
                  </div>
                ))}

                {/* LLM test row */}
                <div style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  padding: "11px 14px",
                  border: "1px solid " + (testing === "ok" ? "color-mix(in oklab, var(--success) 30%, transparent)" : testing === "fail" ? "color-mix(in oklab, var(--danger) 30%, transparent)" : "var(--border)"),
                  borderRadius: "var(--radius-md)",
                  background: testing === "ok" ? "var(--success-soft)" : testing === "fail" ? "var(--danger-soft)" : "transparent",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ width: 22, height: 22, borderRadius: 99,
                      background: testing === "ok" ? "var(--success)" : testing === "fail" ? "var(--danger)" : "var(--accent-soft)",
                      color: testing === "ok" || testing === "fail" ? "white" : "var(--accent)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                      {testing === "running" ? <Icon name="loader" size={12} style={{ animation: "spin 1s linear infinite" }}/>
                        : testing === "ok" ? <Icon name="check" size={11} stroke={3}/>
                        : testing === "fail" ? <Icon name="x" size={11} stroke={3}/>
                        : <Icon name="zap" size={11} stroke={2.4}/>}
                    </span>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>Live LLM round-trip</div>
                      <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                        {testing === "running" && <>sending <span className="mono" style={{ color: "var(--text)" }}>"Reply with the single word: OK"</span> →</>}
                        {testing === "ok" && <span className="mono" style={{ color: "var(--success)" }}>Connected · replied "{testResult?.reply || "OK"}"{testResult?.latency_ms != null ? ` · ${testResult.latency_ms} ms` : ""}</span>}
                        {testing === "fail" && <span className="mono" style={{ color: "var(--danger)" }}>{testResult?.error ? `Failed · ${testResult.error}` : "Failed · check credentials"}</span>}
                        {!testing && "ready"}
                      </div>
                    </div>
                  </div>
                  <Button size="sm" variant="secondary" icon="refresh" onClick={runConnectionTest} disabled={testing === "running"}>Retest</Button>
                </div>
              </div>

              <div style={{ fontSize: 11.5, color: "var(--text-muted)", lineHeight: 1.55 }} className="mono">
                provider: {providerId} · model: {defaultModel}{visionEnabled && visionModel ? ` · vision: ${visionModel}` : ""}
              </div>

              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 24 }}>
                <Button variant="ghost" icon="arrow-left" onClick={() => setStep(3)}>Back</Button>
                <Button variant="primary" iconRight="arrow-right" disabled={testing !== "ok"} onClick={async () => { await persistSettings(); setStep(5); }}>Continue</Button>
              </div>
            </div>
          )}

          {/* STEP 5 — UPLOAD */}
          {step === 5 && (
            <div>
              <SectionHeader eyebrow={`Step 5 of ${TOTAL} · Base resume`} title="Upload your resume" sub="We only need this once. We'll parse it into a YAML you can edit anytime."/>

              {!parsing && (
                <UploadDropzone onUpload={startParse} padding="40px 20px" hint="parsed into ~/.resume_generator/base_resume.yaml"/>
              )}

              {parsing && (
                <InlineParseProgress parsing={parsing}/>
              )}

              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 24 }}>
                <Button variant="ghost" icon="arrow-left" onClick={() => setStep(4)}>Back</Button>
                <Button variant="primary" iconRight="arrow-right"
                  disabled={parsing && !parsing.completed && !parsing.failed}
                  onClick={() => goto("resume")}>
                  {parsing && !parsing.completed && !parsing.failed ? "Parsing…" : "Open editor"}
                </Button>
              </div>
            </div>
          )}
          </div>
        </Card>
      </div>
    </div>
  );
};

// Inline parse-progress view (Setup wizard step 5) — driven by real WS statuses.
const InlineParseProgress = ({ parsing }) => {
  const stages = PARSE_STAGES;
  const completed = parsing.completed;
  const failed = parsing.failed;
  const [elapsed, setElapsed] = React.useState(0);

  React.useEffect(() => {
    if (completed || failed) return;
    const id = setInterval(() => setElapsed(Date.now() - parsing.startedAt), 200);
    return () => clearInterval(id);
  }, [completed, failed, parsing.startedAt]);

  const doneCount = stages.filter(s => parsing.statuses?.[s.id] === "done").length;
  const pct = Math.min(100, completed ? 100 : (doneCount / stages.length) * 100);
  const accent = failed ? "var(--danger)" : completed ? "var(--success)" : "var(--accent)";

  return (
    <div style={{
      border: "1px solid " + (failed ? "color-mix(in oklab, var(--danger) 30%, transparent)" : completed ? "color-mix(in oklab, var(--success) 30%, transparent)" : "var(--accent)"),
      background: failed ? "var(--danger-soft)" : completed ? "var(--success-soft)" : "var(--accent-soft)",
      borderRadius: "var(--radius-lg)", padding: "18px 18px 8px",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{
            width: 28, height: 28, borderRadius: 99,
            background: accent,
            color: "white",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {failed ? <Icon name="x" size={14} stroke={2.8}/>
                    : completed ? <Icon name="check" size={14} stroke={2.8}/>
                    : <Icon name="loader" size={13} style={{ animation: "spin 1.2s linear infinite" }}/>}
          </span>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>{failed ? "Parsing failed" : completed ? "Parsed" : "Parsing…"}</div>
            <div className="mono" style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{parsing.file}</div>
          </div>
        </div>
        <span className="mono" style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
          {(elapsed / 1000).toFixed(1)}s
        </span>
      </div>
      <div style={{ height: 4, background: "var(--surface)", borderRadius: 99, overflow: "hidden", marginBottom: 14 }}>
        <div style={{ height: "100%", width: `${pct}%`, background: accent, borderRadius: 99, transition: "width 300ms" }}/>
      </div>
      {failed && parsing.error && (
        <div style={{ fontSize: 12, color: "var(--danger)", marginBottom: 10 }}>{parsing.error}</div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {stages.map((s) => {
          const status = completed ? "done" : (parsing.statuses?.[s.id] || "pending");
          return (
            <div key={s.id} style={{
              display: "flex", alignItems: "center", gap: 10, padding: "5px 0",
              fontSize: 12.5,
              color: status === "pending" ? "var(--text-faint)" : "var(--text)",
            }}>
              <span style={{
                width: 14, height: 14, borderRadius: 99,
                background: status === "done" ? "var(--success)" : status === "failed" ? "var(--danger)" : status === "running" ? "var(--accent)" : "var(--surface-2)",
                border: "1px solid " + (status === "done" ? "var(--success)" : status === "failed" ? "var(--danger)" : status === "running" ? "var(--accent)" : "var(--border-strong)"),
                display: "flex", alignItems: "center", justifyContent: "center",
                flexShrink: 0,
              }}>
                {status === "done" && <Icon name="check" size={8} stroke={3.4} style={{ color: "white" }}/>}
                {status === "failed" && <Icon name="x" size={8} stroke={3.4} style={{ color: "white" }}/>}
              </span>
              <span style={{ fontWeight: status === "running" ? 600 : 400 }}>{s.label}</span>
              {s.sub && status !== "pending" && (
                <span className="mono truncate" style={{ fontSize: 11, color: "var(--text-faint)" }}>· {s.sub}</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

// Compact model-picker grid used in the wizard + settings
const ModelGrid = ({ value, onChange, options, recommended }) => (
  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
    {options.map(m => (
      <button key={m} onClick={() => onChange(m)}
        style={{
          textAlign: "left", padding: "10px 12px",
          background: value === m ? "var(--accent-soft)" : "var(--surface)",
          border: "1px solid " + (value === m ? "var(--accent)" : "var(--border)"),
          borderRadius: "var(--radius-md)",
          cursor: "pointer", transition: `all var(--t-fast)`,
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
        }}>
        <span className="mono" style={{ fontSize: 12, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis" }}>{m}</span>
        {m === recommended && <Badge tone="accent" style={{ fontSize: 10 }}>rec</Badge>}
      </button>
    ))}
  </div>
);

// ============== BASE RESUME EDITOR ==============
// Merge the editable UI shape back onto the raw resume so untouched fields
// (certifications, publications, project descriptions, headline) are preserved.
const uiToResume = (ui, base = {}) => ({
  ...base,
  personal: {
    ...(base.personal || {}),
    full_name: ui.profile.name || "",
    email: ui.profile.email || "",
    phone: ui.profile.phone || null,
    location: ui.profile.location || null,
    linkedin: ui.profile.linkedin || null,
    github: ui.profile.github || null,
    website: ui.profile.website || null,
    portfolio: ui.profile.portfolio || null,
  },
  summary: ui.profile.summary || null,
  experience: (ui.experience || []).map((e, i) => ({
    ...((base.experience || [])[i] || {}),
    title: e.role || "",
    company: e.company || "",
    location: e.location || null,
    start: e.start || "",
    end: e.end && e.end !== "Present" ? e.end : null,
    bullets: (e.bullets || []).filter(b => b.trim()),
    tech: (e.tech || "").split(",").map(s => s.trim()).filter(Boolean),
  })),
  education: (ui.education || []).map((ed, i) => ({
    ...((base.education || [])[i] || {}),
    institution: ed.institution || ed.school || "",
    degree: ed.degree || "",
    graduation: ed.graduation || ed.end || null,
    gpa: ed.gpa || ed.extra || null,
  })),
});

const ResumeEditor = ({ onReplace, parsing }) => {
  const [tab, setTab] = React.useState("form");
  const [expanded, setExpanded] = React.useState({});
  const [resume, setResume] = React.useState(null);
  const [base, setBase] = React.useState({});
  const [rawYaml, setRawYaml] = React.useState(null);
  const [dirty, setDirty] = React.useState(false);
  const [saveState, setSaveState] = React.useState("idle"); // idle | saving | saved | error
  const parsingDone = parsing && parsing.completed;

  const load = React.useCallback(() => {
    getResume()
      .then(data => {
        const ui = resumeForUi(data);
        if (!ui) { setResume(false); return; }
        setBase(data);
        setResume(ui);
        setDirty(false);
        setSaveState("idle");
        const initExpanded = {};
        if (ui.experience?.length) initExpanded[ui.experience[0].id] = true;
        setExpanded(initExpanded);
      })
      .catch(() => setResume(false));
  }, []);
  React.useEffect(() => { load(); }, [load]);
  // Reload the freshly-parsed resume once a re-parse completes.
  React.useEffect(() => { if (parsingDone) { setRawYaml(null); load(); } }, [parsingDone, load]);

  React.useEffect(() => {
    if (tab === "yaml" && rawYaml === null) {
      getResumeRaw().then(setRawYaml).catch(() => setRawYaml("# Could not load YAML"));
    }
  }, [tab, rawYaml]);

  const edit = (updater) => { setResume(updater); setDirty(true); setSaveState("idle"); };
  const updProfile = (field, val) => edit(r => ({ ...r, profile: { ...r.profile, [field]: val } }));
  const updExp = (i, field, val) => edit(r => ({ ...r, experience: r.experience.map((e, idx) => idx === i ? { ...e, [field]: val } : e) }));
  const updBullet = (i, j, val) => edit(r => ({ ...r, experience: r.experience.map((e, idx) => idx === i ? { ...e, bullets: e.bullets.map((b, bj) => bj === j ? val : b) } : e) }));
  const addBullet = (i) => edit(r => ({ ...r, experience: r.experience.map((e, idx) => idx === i ? { ...e, bullets: [...e.bullets, ""] } : e) }));
  const addRole = () => edit(r => ({ ...r, experience: [...r.experience, { id: `e${Date.now()}`, role: "", company: "", location: "", start: "", end: "Present", bullets: [""], tech: "" }] }));
  const updEdu = (i, field, val) => edit(r => ({ ...r, education: (r.education || []).map((ed, idx) => idx === i ? { ...ed, [field]: val } : ed) }));

  const save = async () => {
    if (!resume) return;
    setSaveState("saving");
    try {
      const saved = await updateResume(uiToResume(resume, base));
      setBase(saved);
      setRawYaml(null);
      setDirty(false);
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  };

  const scrollToSection = (id) => document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });

  const r = resume || {};
  const sections = [
    { id: "profile",    label: "Profile",    count: null },
    { id: "experience", label: "Experience", count: r.experience?.length ?? null },
    { id: "projects",   label: "Projects",   count: r.projects?.length ?? null },
    { id: "education",  label: "Education",  count: r.education?.length ?? null },
    { id: "skills",     label: "Skills",     count: Object.keys(r.skills || {}).length || null },
    { id: "links",      label: "Links",      count: null },
  ];

  return (
    <div className="editor-layout" style={{ display: "grid", gridTemplateColumns: "280px minmax(0, 1fr)", height: "100%", minHeight: 0 }}>
      {/* Left nav */}
      <div style={{
        borderRight: "1px solid var(--border)", background: "var(--surface)",
        padding: "20px 16px", overflow: "auto",
      }}>
        <div className="mono" style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 10 }}>Sections</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {sections.map(s => (
            <button key={s.id} onClick={() => scrollToSection(s.id)} style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "8px 10px", background: "transparent", border: "1px solid transparent",
              borderRadius: "var(--radius-md)", textAlign: "left", cursor: "pointer",
              transition: "all var(--t-fast)",
            }}
              onMouseEnter={(e) => e.currentTarget.style.background = "var(--surface-2)"}
              onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
            >
              <span style={{ fontSize: 13, color: "var(--text)" }}>{s.label}</span>
              {s.count != null && <Badge>{s.count}</Badge>}
            </button>
          ))}
        </div>
      </div>

      {/* Editor */}
      <div style={{ flex: 1, overflow: "auto", minWidth: 0 }}>
        <div style={{
          padding: "20px 32px",
          borderBottom: "1px solid var(--border)",
          background: "var(--surface)",
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
        }}>
          <div>
            <div style={{ fontSize: 20, fontWeight: 600, letterSpacing: -0.3 }}>Base resume</div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
              {parsing && !parsing.completed
                ? <span style={{ color: "var(--accent)" }}>Re-parsing from <span className="mono">{parsing.file}</span>…</span>
                : saveState === "saving" ? "Saving changes…"
                : saveState === "error" ? <span style={{ color: "var(--danger)" }}>Save failed — try again</span>
                : dirty ? "Unsaved changes"
                : "All changes saved"}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {parsing && !parsing.completed ? (
              <Badge tone="info" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <Icon name="loader" size={10} stroke={2.6} style={{ animation: "spin 1s linear infinite" }}/> Parsing
              </Badge>
            ) : (
              <Badge tone={saveState === "error" ? "danger" : dirty || saveState === "saving" ? "warning" : "success"} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                {saveState === "saving" ? <><Icon name="loader" size={10} stroke={2.6} style={{ animation: "spin 1s linear infinite" }}/> Saving</>
                  : saveState === "error" ? <><Icon name="x" size={10} stroke={3}/> Error</>
                  : dirty ? <><Icon name="edit" size={10} stroke={2.4}/> Unsaved</>
                  : <><Icon name="check" size={10} stroke={3}/> Saved</>}
              </Badge>
            )}
            <Tabs value={tab} onChange={setTab} options={[{value:"form",label:"Form"},{value:"yaml",label:"YAML"}]}/>
            <Button size="sm" variant="primary" icon="check" onClick={save} disabled={!dirty || saveState === "saving" || !resume}>Save</Button>
            <Button size="sm" variant="secondary" icon="upload" onClick={onReplace}>Replace</Button>
          </div>
        </div>

        <div style={{ maxWidth: 820, margin: "0 auto", padding: "28px 32px 80px" }}>
          <div key={tab + String(!!resume)} className="route-in">
          {resume === null ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 80, gap: 10, color: "var(--text-muted)" }}>
              <Icon name="loader" size={16} style={{ animation: "spin 1s linear infinite" }}/>
              <span style={{ fontSize: 13 }}>Loading resume…</span>
            </div>
          ) : resume === false ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "60px 32px", textAlign: "center" }}>
              <div style={{
                width: 60, height: 60, borderRadius: 16,
                background: "var(--surface)", border: "1px solid var(--border)",
                display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20,
              }}>
                <Icon name="file-text" size={26} stroke={1.5} style={{ color: "var(--text-muted)" }}/>
              </div>
              <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: -0.2, marginBottom: 8 }}>No base resume yet</div>
              <div style={{ fontSize: 13.5, color: "var(--text-muted)", maxWidth: 400, lineHeight: 1.65, marginBottom: 24 }}>
                Upload a <span className="mono">.pdf</span> or <span className="mono">.tex</span> file to get started.
                Resume Generator will parse it into a structured YAML that every run uses as its source of truth.
              </div>
              <Button variant="primary" icon="upload" onClick={onReplace}>Upload base resume</Button>
            </div>
          ) : tab === "form" ? (
            <>
              {/* Profile card */}
              <Card id="sec-profile" style={{ marginBottom: 16 }} padding={20}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>Profile</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
                  <div><div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>Name</div><Input value={r.profile.name || ""} onChange={(e) => updProfile("name", e.target.value)}/></div>
                  <div><div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>Location</div><Input value={r.profile.location || ""} onChange={(e) => updProfile("location", e.target.value)}/></div>
                  <div><div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>Email</div><Input value={r.profile.email || ""} onChange={(e) => updProfile("email", e.target.value)}/></div>
                  <div><div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>Phone</div><Input value={r.profile.phone || ""} onChange={(e) => updProfile("phone", e.target.value)}/></div>
                  <div><div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>LinkedIn</div><Input icon="link" value={r.profile.linkedin || ""} onChange={(e) => updProfile("linkedin", e.target.value)} placeholder="linkedin.com/in/yourname"/></div>
                  <div><div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>GitHub</div><Input icon="link" value={r.profile.github || ""} onChange={(e) => updProfile("github", e.target.value)} placeholder="github.com/yourname"/></div>
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>Summary</div>
                <Textarea value={r.profile.summary || ""} onChange={(e) => updProfile("summary", e.target.value)} style={{ minHeight: 70 }}/>
              </Card>

              {/* Experience */}
              <Card id="sec-experience" style={{ marginBottom: 16 }} padding={20}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>Experience</div>
                  <Button size="sm" variant="ghost" icon="plus" onClick={addRole}>Add role</Button>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {r.experience.map((e, ei) => (
                    <div key={e.id} style={{
                      border: "1px solid var(--border)", borderRadius: "var(--radius-md)",
                      background: "var(--surface)",
                    }}>
                      <button
                        onClick={() => setExpanded(x => ({ ...x, [e.id]: !x[e.id] }))}
                        style={{
                          display: "flex", alignItems: "center", justifyContent: "space-between",
                          width: "100%", padding: "10px 12px",
                          background: "transparent", border: "none", cursor: "pointer", textAlign: "left",
                        }}
                      >
                        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <Icon name="grip" size={14} style={{ color: "var(--text-faint)" }}/>
                          <Icon name={expanded[e.id] ? "chevron-down" : "chevron-right"} size={14} style={{ color: "var(--text-muted)" }}/>
                          <span style={{ fontSize: 13, fontWeight: 500 }}>{e.role || "New role"}</span>
                          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>· {e.company}</span>
                        </span>
                        <span className="mono" style={{ fontSize: 11.5, color: "var(--text-faint)" }}>{e.start} — {e.end}</span>
                      </button>
                      {expanded[e.id] && (
                        <div style={{ padding: "0 16px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
                          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                            <div><div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 4 }}>Role</div><Input value={e.role || ""} onChange={(ev) => updExp(ei, "role", ev.target.value)}/></div>
                            <div><div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 4 }}>Company</div><Input value={e.company || ""} onChange={(ev) => updExp(ei, "company", ev.target.value)}/></div>
                            <div><div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 4 }}>Start</div><Input value={e.start || ""} onChange={(ev) => updExp(ei, "start", ev.target.value)}/></div>
                            <div><div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 4 }}>End</div><Input value={e.end || ""} onChange={(ev) => updExp(ei, "end", ev.target.value)}/></div>
                          </div>
                          <div>
                            <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 4 }}>Bullets</div>
                            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                              {e.bullets.map((b, i) => (
                                <Textarea key={i} value={b} onChange={(ev) => updBullet(ei, i, ev.target.value)} style={{ minHeight: 36 }} />
                              ))}
                            </div>
                            <button onClick={() => addBullet(ei)} style={{ marginTop: 8, background: "transparent", border: "none", color: "var(--text-muted)", fontSize: 12, cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }}>
                              <Icon name="plus" size={12}/> Add bullet
                            </button>
                          </div>
                          <div>
                            <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 4 }}>Tech <span style={{ color: "var(--text-faint)" }}>(comma-separated)</span></div>
                            <Input value={e.tech || ""} onChange={(ev) => updExp(ei, "tech", ev.target.value)}/>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </Card>

              {/* Projects */}
              <Card id="sec-projects" style={{ marginBottom: 16 }} padding={20}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>Projects</div>
                </div>
                {r.projects.map(p => (
                  <div key={p.id} style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "10px 12px", border: "1px solid var(--border)", borderRadius: "var(--radius-md)",
                  }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <Icon name="grip" size={14} style={{ color: "var(--text-faint)" }}/>
                      <Icon name="chevron-right" size={14} style={{ color: "var(--text-muted)" }}/>
                      <span style={{ fontSize: 13, fontWeight: 500 }}>{p.name}</span>
                      <span style={{ fontSize: 12, color: "var(--text-muted)" }} className="mono">· {p.url}</span>
                    </span>
                    <Icon name="trash" size={13} style={{ color: "var(--text-faint)" }}/>
                  </div>
                ))}
              </Card>

              {/* Skills */}
              <Card id="sec-skills" style={{ marginBottom: 16 }} padding={20}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>Skills</div>
                {Object.entries(r.skills).map(([group, items]) => (
                  <div key={group} style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>{group}</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: 8, border: "1px solid var(--border)", borderRadius: "var(--radius-md)", minHeight: 38 }}>
                      {items.map(s => (
                        <span key={s} style={{
                          display: "inline-flex", alignItems: "center", gap: 5,
                          padding: "3px 8px", background: "var(--surface-2)", border: "1px solid var(--border)",
                          borderRadius: 99, fontSize: 12,
                        }}>{s} <Icon name="x" size={10} style={{ color: "var(--text-faint)" }}/></span>
                      ))}
                      <input placeholder="Type to add…" style={{ background: "transparent", border: "none", outline: "none", fontSize: 12.5, padding: "3px 8px", flex: 1, minWidth: 100 }}/>
                    </div>
                  </div>
                ))}
              </Card>

              {/* Education */}
              <Card id="sec-education" style={{ marginBottom: 16 }} padding={20}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>Education</div>
                  <Button size="sm" variant="ghost" icon="plus" onClick={() => edit(rr => ({ ...rr, education: [...(rr.education || []), { institution: "", degree: "", graduation: "", gpa: "" }] }))}>Add</Button>
                </div>
                {(r.education || []).length === 0 && (
                  <EmptyState icon="file-text" title="No education entries" sub="Add a degree or certification."/>
                )}
                {(r.education || []).map((ed, i) => (
                  <div key={ed.id || i} style={{
                    display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10,
                    padding: "12px 14px", border: "1px solid var(--border)", borderRadius: "var(--radius-md)",
                    marginBottom: 8, background: "var(--surface)",
                  }}>
                    <div style={{ gridColumn: "1 / -1" }}><div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 4 }}>School</div><Input value={ed.institution || ed.school || ""} onChange={(e) => updEdu(i, "institution", e.target.value)}/></div>
                    <div><div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 4 }}>Degree</div><Input value={ed.degree || ""} onChange={(e) => updEdu(i, "degree", e.target.value)}/></div>
                    <div><div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 4 }}>Graduation year</div><Input value={ed.graduation || ed.end || ""} onChange={(e) => updEdu(i, "graduation", e.target.value)}/></div>
                    <div><div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 4 }}>GPA / Honours</div><Input value={ed.gpa || ed.extra || ""} onChange={(e) => updEdu(i, "gpa", e.target.value)}/></div>
                  </div>
                ))}
              </Card>

              {/* Links */}
              <Card id="sec-links" style={{ marginBottom: 16 }} padding={20}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>Links</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <div><div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>LinkedIn</div><Input icon="link" value={r.profile.linkedin || ""} onChange={(e) => updProfile("linkedin", e.target.value)} placeholder="linkedin.com/in/yourname"/></div>
                  <div><div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>GitHub</div><Input icon="link" value={r.profile.github || ""} onChange={(e) => updProfile("github", e.target.value)} placeholder="github.com/yourname"/></div>
                  <div><div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>Website</div><Input icon="link" value={r.profile.website || ""} onChange={(e) => updProfile("website", e.target.value)} placeholder="yoursite.com"/></div>
                  <div><div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>Portfolio</div><Input icon="link" value={r.profile.portfolio || ""} onChange={(e) => updProfile("portfolio", e.target.value)} placeholder="portfolio.yourname.com"/></div>
                </div>
              </Card>
            </>
          ) : (
            <Card padding={0}>
              <pre className="mono" style={{
                margin: 0, padding: 20, fontSize: 12.5, lineHeight: 1.65, color: "var(--text)",
                whiteSpace: "pre", overflow: "auto",
              }}>{rawYaml === null ? "Loading…" : rawYaml}</pre>
            </Card>
          )}
          </div>
        </div>
      </div>
    </div>
  );
};

// ============== NEW RUN ==============
const NewRun = ({ goto, openRun, locked, onRunStarted }) => {
  const [tab, setTab] = React.useState("text");
  const [text, setText] = React.useState("");
  const [url, setUrl] = React.useState("");
  const [jdFileId, setJdFileId] = React.useState(null);
  const [jdFileName, setJdFileName] = React.useState(null);
  const [uploadingFile, setUploadingFile] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState(null);
  const switchTab = (v) => { setTab(v); setError(null); };
  const handleJdFile = async (file) => {
    if (!file) return;
    if (/\.txt$/i.test(file.name)) {
      const reader = new FileReader();
      reader.onload = () => { setText(String(reader.result || "")); setJdFileId(null); setJdFileName(null); setTab("text"); setError(null); };
      reader.onerror = () => setError("Could not read that file.");
      reader.readAsText(file);
      return;
    }
    if (/\.pdf$/i.test(file.name)) {
      setUploadingFile(true);
      setError(null);
      try {
        const { file_id } = await uploadJdFile(file);
        setJdFileId(file_id);
        setJdFileName(file.name);
      } catch (err) {
        setError(err.message || "Could not extract text from that PDF.");
      } finally {
        setUploadingFile(false);
      }
      return;
    }
    setError("Only .txt and .pdf files are supported.");
  };
  const charCount = text.length;
  const tone = charCount > 8000 ? "danger" : charCount > 7000 ? "warning" : "neutral";
  const startRun = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const result = await createRun({
        jdText: tab === "text" ? text : undefined,
        jdUrl: tab === "url" ? url : undefined,
        jdFileId: tab === "file" ? jdFileId : undefined,
      });
      onRunStarted?.(result.thread_id);
    } catch (err) {
      setError(err.message || "Could not start run.");
    } finally {
      setSubmitting(false);
    }
  };

  if (locked) {
    return (
      <div style={{ padding: "32px 40px", maxWidth: 720, margin: "0 auto" }}>
        <div style={{ marginBottom: 18 }}>
          <div className="mono" style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5 }}>New run</div>
          <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: -0.4, marginTop: 4 }}>Paused</div>
        </div>
        <Card padding={28}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 14, padding: "20px 12px" }}>
            <div style={{
              width: 56, height: 56, borderRadius: 99, background: "var(--accent-soft)", color: "var(--accent)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <Icon name="loader" size={24} style={{ animation: "spin 1.4s linear infinite" }}/>
            </div>
            <div>
              <div style={{ fontSize: 17, fontWeight: 600, letterSpacing: -0.2 }}>Your base resume is being re-parsed</div>
              <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 6, maxWidth: 440 }}>
                New runs are paused while parsing finishes, so the LangGraph pipeline doesn't mid-flight against a stale resume. This usually takes 10–12s.
              </div>
            </div>
            <Button variant="secondary" icon="file-text" onClick={() => goto("resume")}>View parsing progress</Button>
          </div>
        </Card>
      </div>
    );
  }

  const detected = tab === "text" && text.trim().length > 200;
  const step = (n, title, sub, you) => (
    <div style={{ display: "flex", gap: 11, padding: "9px 0" }}>
      <span style={{ width: 24, height: 24, borderRadius: 99, flexShrink: 0, display: "grid", placeItems: "center", fontSize: 12, fontWeight: 700, background: you ? "var(--accent)" : "var(--surface-2)", color: you ? "var(--accent-contrast)" : "var(--text)" }}>{n}</span>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13.5, fontWeight: 600 }}>{title}{you && <span style={{ fontSize: 10, fontWeight: 700, color: "var(--accent)", background: "var(--accent-soft)", borderRadius: 99, padding: "0 7px" }}>you</span>}</div>
        <div style={{ fontSize: 12, color: "var(--text-faint)", marginTop: 1 }}>{sub}</div>
      </div>
    </div>
  );
  const optRow = (title, sub, last) => (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 0", borderBottom: last ? "none" : "1px dashed var(--border)" }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600 }}>{title}</div>
        <div style={{ fontSize: 12, color: "var(--text-faint)" }}>{sub}</div>
      </div>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11.5, fontWeight: 600, color: "var(--success)", background: "var(--success-soft)", borderRadius: 99, padding: "3px 9px", flexShrink: 0 }}><Icon name="check" size={11} stroke={3}/>On</span>
    </div>
  );

  return (
    <div className="page-pad" style={{ padding: "24px 32px 48px", maxWidth: 1280, margin: "0 auto" }}>
      <div className="mono" style={{ fontSize: 11, letterSpacing: 0.6, color: "var(--text-faint)", textTransform: "uppercase", marginBottom: 8 }}>Workspace / Create</div>
      <div className="serif" style={{ fontSize: 32, fontWeight: 800, letterSpacing: -1.1, lineHeight: 1.05 }}>Tailor a resume to a job</div>
      <div style={{ fontSize: 13.5, color: "var(--text-muted)", marginTop: 8, maxWidth: 620 }}>Paste the posting or drop a URL — the agents read it against your base résumé, ask only what they can't infer, and file the finished PDF under the company.</div>

      <div className="two-col-grid" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.6fr) minmax(280px, 1fr)", gap: 24, alignItems: "start", marginTop: 24 }}>
        {/* input card */}
        <Card padding={22}>
          <div style={{ display: "inline-flex", background: "var(--surface-2)", borderRadius: "var(--radius-md)", padding: 3, gap: 2 }}>
            {[["text", "Paste text", "file-text"], ["url", "From URL", "link"], ["file", "Upload file", "upload"]].map(([id, label, ic]) => (
              <button key={id} onClick={() => switchTab(id)} style={{
                display: "inline-flex", alignItems: "center", gap: 7, padding: "8px 14px",
                background: tab === id ? "var(--surface)" : "transparent",
                color: tab === id ? "var(--text)" : "var(--text-muted)",
                border: "none", borderRadius: 7, fontSize: 13, fontWeight: 600, cursor: "pointer",
                boxShadow: tab === id ? "var(--shadow-sm)" : "none",
              }}><Icon name={ic} size={14}/>{label}</button>
            ))}
          </div>

          <div style={{ marginTop: 16 }}>
            {tab === "text" ? (
              <>
                <Textarea value={text} onChange={(e) => setText(e.target.value)}
                  placeholder="Paste the full job description here…"
                  style={{ minHeight: 300, fontFamily: "var(--font-mono)", fontSize: 12.5, lineHeight: 1.7 }}/>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, color: detected ? "var(--success)" : "var(--text-faint)" }}>
                    <Icon name={detected ? "check-circle" : "info"} size={14}/>{detected ? "Looks like a full posting — company & role detected" : "Paste the full job description above"}
                  </span>
                  <span className="mono" style={{ fontSize: 11.5, color: tone === "danger" ? "var(--danger)" : tone === "warning" ? "var(--warning)" : "var(--text-faint)" }}>{charCount.toLocaleString()} / 8,000</span>
                </div>
              </>
            ) : tab === "url" ? (
              <>
                <Input icon="link" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://jobs.example.com/staff-engineer" style={{ height: 44 }}/>
                <div style={{ marginTop: 10, fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
                  The posting is fetched and parsed when the run starts (the <span className="mono">scrape_url</span> → <span className="mono">extract_jd</span> steps). Some sites block automated fetches — if scraping fails, paste the text instead.
                </div>
              </>
            ) : (
              <>
                {jdFileId ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", background: "var(--success-soft)" }}>
                    <Icon name="check-circle" size={18} style={{ color: "var(--success)", flexShrink: 0 }}/>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="mono truncate" style={{ fontSize: 13, fontWeight: 600 }}>{jdFileName}</div>
                      <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Extracted on the server — ready to generate</div>
                    </div>
                    <Button size="sm" variant="ghost" onClick={() => { setJdFileId(null); setJdFileName(null); }}>Change</Button>
                  </div>
                ) : (
                  <UploadDropzone onUpload={handleJdFile} accept=".txt,.pdf"
                    label={uploadingFile ? "Extracting…" : "Drop a .txt or .pdf file, or click to browse"}
                    hint="Job descriptions — .txt loads instantly, .pdf is extracted on the server"/>
                )}
              </>
            )}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 18, paddingTop: 18, borderTop: "1px solid var(--border)", flexWrap: "wrap" }}>
            <span style={{ flex: 1, minWidth: 180, display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12, color: "var(--text-faint)" }}>
              {error ? <span style={{ color: "var(--danger)" }}>{error}</span> : <><Icon name="loader" size={13} style={{ animation: "none" }}/>Runs take ~45s — you can leave and come back</>}
            </span>
            <Button variant="primary" iconRight="zap" onClick={startRun} disabled={tone === "danger" || submitting || (tab === "text" ? !text.trim() : tab === "url" ? !url.trim() : !jdFileId)} style={{ height: 44 }}>
              {submitting ? "Starting…" : "Generate tailored resume"}
            </Button>
          </div>
        </Card>

        {/* right column */}
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <Card padding={18}>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>What happens next</div>
            {step(1, "Understand the role", "Company, seniority & must-haves extracted")}
            {step(2, "Gap analysis", "Your resume compared against the posting")}
            {step(3, "Your review", "Answer gap questions, approve bullet rewrites", true)}
            {step(4, "Generate & validate", "LaTeX written, linted, compiled, layout-checked")}
            {step(5, "Filed to library", "PDF saved under the company folder")}
          </Card>
          <Card padding={18}>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>Run options</div>
            {optRow("Ask me about gaps", "Pause to add missing experience")}
            {optRow("Review rewrites", "Approve each bullet before compiling")}
            {optRow("Vision layout check", "opus reviews the final PDF", true)}
          </Card>
          <Card padding={18}>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>Base resume</div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ width: 34, height: 34, borderRadius: 9, flexShrink: 0, display: "grid", placeItems: "center", background: "var(--success-soft)", color: "var(--success)" }}><Icon name="file-text" size={16}/></span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>Ready</div>
                <div className="mono" style={{ fontSize: 11, color: "var(--text-faint)" }}>base_resume.yaml</div>
              </div>
              <Button size="sm" variant="secondary" onClick={() => goto("resume")}>Change</Button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};

// ============== HISTORY ==============
const HistoryView = ({ goto, openRun }) => {
  const runs = useRuns();
  const [query, setQuery] = React.useState("");
  const [range, setRange] = React.useState("all");

  const rangeMs = range === "7d" ? 7 * 86400000 : range === "30d" ? 30 * 86400000 : null;
  const now = Date.now();
  const q = query.trim().toLowerCase();
  const filtered = runs.filter(r => {
    if (rangeMs && r.ts && (now - r.ts * 1000) > rangeMs) return false;
    if (q && !`${r.company} ${r.role}`.toLowerCase().includes(q)) return false;
    return true;
  });

  const grouped = {};
  filtered.forEach(r => { (grouped[r.company] ||= []).push(r); });
  const groups = Object.entries(grouped);

  return (
    <div className="page-pad" style={{ padding: "32px 40px", maxWidth: 1180, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 18 }}>
        <div>
          <div className="mono" style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5 }}>History</div>
          <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: -0.4, marginTop: 4 }}>All runs</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Input icon="search" placeholder="Filter…" value={query} onChange={(e) => setQuery(e.target.value)} style={{ width: 220 }}/>
          <Tabs value={range} onChange={setRange} options={[
            { value: "all", label: "All" },
            { value: "7d", label: "7d" },
            { value: "30d", label: "30d" },
          ]}/>
        </div>
      </div>

      {groups.length === 0 ? (
        <Card padding={0}><EmptyState icon="history" title="No matching runs" sub={runs.length ? "Try a different filter or time range." : "Start a run to see it here."}/></Card>
      ) : (
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {groups.map(([company, companyRuns]) => (
          <Card key={company} padding={0}>
            <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <Icon name="chevron-down" size={14} style={{ color: "var(--text-muted)" }}/>
                <div style={{ fontSize: 14, fontWeight: 600 }}>{company}</div>
                <Badge>{companyRuns.length} {companyRuns.length === 1 ? "run" : "runs"}</Badge>
              </div>
              <span className="mono" style={{ fontSize: 11.5, color: "var(--text-faint)" }}>most recent · {companyRuns[0].date}</span>
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <tbody>
                {companyRuns.map(r => (
                  <tr key={r.id} style={{ borderTop: "1px solid var(--border)", cursor: "pointer" }}
                    onMouseEnter={(e) => e.currentTarget.style.background = "var(--surface-2)"}
                    onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                    onClick={() => openRun(r.id, r.status, r)}
                  >
                    <td style={{ padding: "10px 18px", width: "30%" }}>
                      <div style={{ fontSize: 12.5 }}>{r.role}</div>
                    </td>
                    <td style={{ padding: "10px 14px" }}><StatusPill status={r.status} size="sm"/></td>
                    <td style={{ padding: "10px 14px" }} className="mono"><span style={{ color: "var(--text-muted)", fontSize: 11.5 }}>{r.duration}</span></td>
                    <td style={{ padding: "10px 14px" }} className="mono"><span style={{ color: "var(--text-faint)", fontSize: 11.5 }}>{r.retries ? `×${r.retries} retries` : "—"}</span></td>
                    <td style={{ padding: "10px 14px", color: "var(--text-muted)", fontSize: 11.5 }}>{r.date}</td>
                    <td style={{ padding: "10px 18px", textAlign: "right" }}>
                      <div style={{ display: "inline-flex", gap: 2 }} onClick={(e) => e.stopPropagation()}>
                        {r.pdf_url && <IconButton name="download" label="Download PDF" onClick={() => window.open(r.pdf_url, "_blank")} />}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ))}
      </div>
      )}
    </div>
  );
};

// ============== SETTINGS ==============
const SettingsView = ({ tweaks, setTweak }) => {
  const { providers, models, visionModels } = useProviders();
  const [showKey, setShowKey] = React.useState(false);
  const [apiKey, setApiKey] = React.useState("");
  const [providerId, setProviderId] = React.useState(ACTIVE_LLM.providerId);
  const [defaultModel, setDefaultModel] = React.useState(ACTIVE_LLM.defaultModel);
  const [visionEnabled, setVisionEnabled] = React.useState(ACTIVE_LLM.visionEnabled);
  const [visionModel, setVisionModel] = React.useState(ACTIVE_LLM.visionModel);
  const [baseUrl, setBaseUrl] = React.useState("");
  const [generatorMax, setGeneratorMax] = React.useState("5");
  const [compileTimeout, setCompileTimeout] = React.useState("180");
  const [scrapeTimeout, setScrapeTimeout] = React.useState("30");
  const [outputDir, setOutputDir] = React.useState("./output");
  const [hrReview, setHrReview] = React.useState(true);
  const [retesting, setRetesting] = React.useState(false);
  const [connection, setConnection] = React.useState(ACTIVE_LLM);
  const [dirty, setDirty] = React.useState(false);
  const [saveState, setSaveState] = React.useState("idle"); // idle | saving | saved | error
  const [doctor, setDoctor] = React.useState(null);
  const [doctorRunning, setDoctorRunning] = React.useState(false);

  const applySettings = (s) => {
    setConnection(s);
    setProviderId(s.providerId || s.provider);
    setDefaultModel(s.defaultModel);
    setVisionEnabled(s.visionEnabled);
    setVisionModel(s.visionModel || "");
    setBaseUrl(s.baseUrl || "");
    if (s.generatorMax != null) setGeneratorMax(String(s.generatorMax));
    if (s.compileTimeoutSeconds != null) setCompileTimeout(String(s.compileTimeoutSeconds));
    if (s.scrapeTimeoutSeconds != null) setScrapeTimeout(String(s.scrapeTimeoutSeconds));
    if (s.outputDir) setOutputDir(s.outputDir);
    if (s.enableHrReview != null) setHrReview(s.enableHrReview);
  };

  React.useEffect(() => { getSettings().then(applySettings).catch(() => {}); }, []);
  const runDoctorCheck = React.useCallback(() => {
    setDoctorRunning(true);
    runDoctor().then(setDoctor).catch(() => setDoctor(null)).finally(() => setDoctorRunning(false));
  }, []);
  React.useEffect(() => { runDoctorCheck(); }, [runDoctorCheck]);

  const provider = providers.find(p => p.id === providerId) || providers.find(p => p.id === "anthropic") || providers[0] || {};
  const isOllama = providerId === "ollama_local" || providerId === "ollama_remote";
  const mark = () => { setDirty(true); setSaveState("idle"); };

  const selectProvider = (pid) => {
    setProviderId(pid);
    setDefaultModel((models[pid] || [""])[0] || "");
    setVisionModel((visionModels[pid] || [""])[0] || "");
    setApiKey("");
    mark();
  };

  const save = async () => {
    setSaveState("saving");
    try {
      const updated = await updateSettings({
        provider: providerId,
        default_model: defaultModel,
        vision_model: visionModel,
        vision_enabled: visionEnabled,
        base_url: baseUrl || undefined,
        api_key: apiKey || undefined,
        generator_max: Number(generatorMax) || undefined,
        compile_timeout_seconds: Number(compileTimeout) || undefined,
        scrape_timeout_seconds: Number(scrapeTimeout) || undefined,
        output_dir: outputDir || undefined,
        enable_hr_review: hrReview,
      });
      applySettings(updated);
      setApiKey("");
      setDirty(false);
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  };

  const sectionStyle = { marginBottom: 22 };
  const labelStyle = { fontSize: 11.5, color: "var(--text-muted)", marginBottom: 6 };
  const accentSwatches = [["graphite", "#0A0A0B"], ["indigo", "#2563EB"], ["pine", "#16A34A"], ["oxblood", "#DC2626"]];

  return (
    <div className="page-pad" style={{ padding: "32px 40px", maxWidth: 820, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 22 }}>
        <div>
          <div className="mono" style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5 }}>Settings</div>
          <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: -0.4, marginTop: 4 }}>Configuration</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 12, color: saveState === "error" ? "var(--danger)" : "var(--text-muted)" }}>
            {saveState === "saving" ? "Saving…" : saveState === "saved" ? "Saved" : saveState === "error" ? "Save failed" : dirty ? "Unsaved changes" : ""}
          </span>
          <Button variant="primary" icon="check" onClick={save} disabled={!dirty || saveState === "saving"}>Save changes</Button>
        </div>
      </div>

      {/* Active connection summary */}
      <Card style={sectionStyle} padding={0}>
        <div style={{ padding: "16px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, borderBottom: "1px solid var(--border)", flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0, flex: 1 }}>
            <span style={{
              width: 36, height: 36, borderRadius: 8,
              background: "var(--accent)", color: "var(--accent-contrast)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: 17,
              flexShrink: 0,
            }}>{provider.logo}</span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 14, fontWeight: 600, whiteSpace: "nowrap" }}>{provider.name}</span>
                <span style={{ fontSize: 11, color: "var(--text-muted)", whiteSpace: "nowrap" }}>· {provider.sub}</span>
                <StatusPill status={connection.status === "error" ? "failed" : "complete"} size="sm" label={connection.status === "error" ? "Error" : "Connected"}/>
              </div>
              <div className="mono" style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={`default: ${defaultModel}${visionEnabled ? ` · vision: ${visionModel}` : ""}`}>
                default: {defaultModel}{visionEnabled && visionModel && <> · vision: {visionModel}</>}
              </div>
            </div>
          </div>
          <Button size="sm" variant="secondary" icon="refresh"
            onClick={async () => {
              setRetesting(true);
              try {
                const result = await testConnection({ provider: providerId, default_model: defaultModel, vision_model: visionModel, base_url: baseUrl || undefined, api_key: apiKey || undefined });
                setConnection(c => ({ ...c, latencyMs: result.latency_ms, testReply: result.reply || result.error || "", status: result.ok ? "connected" : "error", lastTested: "just now" }));
              } catch {
                setConnection(c => ({ ...c, status: "error", testReply: "request failed", lastTested: "just now" }));
              }
              setRetesting(false);
            }}>
            {retesting ? "Testing…" : "Re-test"}
          </Button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", borderBottom: "1px solid var(--border)" }}>
          {[
            { l: "Latency", v: connection.latencyMs ? `${connection.latencyMs} ms` : "-" },
            { l: "Last test", v: connection.lastTested || "-" },
            { l: "Reply", v: connection.testReply ? `"${connection.testReply}"` : "-" },
          ].map((s, i, arr) => (
            <div key={s.l} style={{ padding: "10px 20px", borderRight: i < arr.length - 1 ? "1px solid var(--border)" : "none", display: "flex", flexDirection: "column", gap: 2 }}>
              <span style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5 }} className="mono">{s.l}</span>
              <span className="mono" style={{ fontSize: 12.5, color: "var(--text)" }}>{s.v}</span>
            </div>
          ))}
        </div>
        <div style={{ padding: "10px 20px", fontSize: 11.5, color: "var(--text-faint)" }} className="mono">
          config: ~/.resume_generator/config.yaml · key: ~/.resume_generator/.env (chmod 600)
        </div>
      </Card>

      {/* Provider picker */}
      <Card style={sectionStyle} padding={22}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>Provider</div>
        <div className="provider-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 8 }}>
          {providers.map(p => (
            <button key={p.id} onClick={() => selectProvider(p.id)} style={{
              display: "flex", alignItems: "center", gap: 9, padding: "10px 12px",
              background: providerId === p.id ? "var(--accent-soft)" : "var(--surface)",
              border: "1px solid " + (providerId === p.id ? "var(--accent)" : "var(--border)"),
              borderRadius: "var(--radius-md)", cursor: "pointer",
              textAlign: "left",
            }}>
              <ProviderLogo p={p} size={24}/>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 500 }} className="truncate">{p.name}</div>
                <div style={{ fontSize: 10.5, color: "var(--text-muted)" }} className="truncate">{p.sub}</div>
              </div>
            </button>
          ))}
        </div>
      </Card>

      {/* Credentials */}
      {provider.needsKey && (
        <Card style={sectionStyle} padding={22}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>API key</div>
          <Input
            type={showKey ? "text" : "password"}
            value={apiKey}
            onChange={(e) => { setApiKey(e.target.value); mark(); }}
            placeholder="Leave blank to keep the current key"
            suffix={<IconButton name={showKey ? "eye-off" : "eye"} label="Toggle visibility" onClick={() => setShowKey(s => !s)} />}
          />
          {provider.url && (
            <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 8 }}>
              Get a key at <span className="mono" style={{ color: "var(--text)" }}>{provider.url}</span> · saved to <span className="mono">~/.resume_generator/.env</span>
            </div>
          )}
        </Card>
      )}

      {isOllama && (
        <Card style={sectionStyle} padding={22}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>Ollama server</div>
          <div style={labelStyle}>Base URL</div>
          <Input icon="link" value={baseUrl} onChange={(e) => { setBaseUrl(e.target.value); mark(); }} placeholder="http://localhost:11434"/>
        </Card>
      )}

      {/* Models */}
      <Card style={sectionStyle} padding={22}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Text / reasoning model</div>
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>Used for JD extraction, gap analysis, and LaTeX generation.</div>
        <ModelGrid value={defaultModel} onChange={(m) => { setDefaultModel(m); mark(); }}
          options={withCurrent(models[providerId], defaultModel)}
          recommended={(models[providerId] || [])[0]}/>
      </Card>

      <Card style={sectionStyle} padding={22}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 4 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Vision validation</div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>Multimodal inspection of the compiled PDF (overlapping text, cut-offs). Used in the <span className="mono" style={{ color: "var(--text)" }}>validate_alignment</span> node.</div>
          </div>
          <Toggle checked={visionEnabled} onChange={(v) => { setVisionEnabled(v); mark(); }} label="" />
        </div>
        {visionEnabled && (
          <div style={{ marginTop: 12 }}>
            <ModelGrid value={visionModel} onChange={(m) => { setVisionModel(m); mark(); }}
              options={withCurrent(visionModels[providerId], visionModel)}
              recommended={(visionModels[providerId] || [])[0]}/>
          </div>
        )}
      </Card>

      <Card style={sectionStyle} padding={22}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Pipeline features</div>
        <Toggle checked={hrReview} onChange={(v) => { setHrReview(v); mark(); }} label="Enable HR review" sub="Adds an HR-style pass over the generated resume (extra retry triggers)."/>
      </Card>

      <Card style={sectionStyle} padding={22}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>Retries &amp; budget</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 }}>
          <div><div style={labelStyle}>Generator (1–10)</div><Input value={generatorMax} onChange={(e) => { setGeneratorMax(e.target.value); mark(); }}/></div>
          <div><div style={labelStyle}>Compile timeout (s)</div><Input value={compileTimeout} onChange={(e) => { setCompileTimeout(e.target.value); mark(); }}/></div>
          <div><div style={labelStyle}>Scrape timeout (s)</div><Input value={scrapeTimeout} onChange={(e) => { setScrapeTimeout(e.target.value); mark(); }}/></div>
        </div>
      </Card>

      <Card style={sectionStyle} padding={22}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>Output directory</div>
        <Input value={outputDir} onChange={(e) => { setOutputDir(e.target.value); mark(); }} icon="folder"/>
      </Card>

      {/* Doctor */}
      <Card style={sectionStyle} padding={22}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Doctor</div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>Environment checks for the LaTeX engine, PDF tooling, and the provider.</div>
          </div>
          <Button size="sm" variant="secondary" icon="refresh" onClick={runDoctorCheck} disabled={doctorRunning}>{doctorRunning ? "Checking…" : "Re-run"}</Button>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {(doctor?.checks || []).map(c => (
            <div key={c.label} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "8px 12px", border: "1px solid var(--border)", borderRadius: "var(--radius-md)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                <span style={{ width: 20, height: 20, borderRadius: 99, flexShrink: 0, background: c.ok ? "var(--success-soft)" : "var(--danger-soft)", color: c.ok ? "var(--success)" : "var(--danger)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <Icon name={c.ok ? "check" : "x"} size={11} stroke={3}/>
                </span>
                <span style={{ fontSize: 13 }}>{c.label}</span>
              </div>
              {!c.ok && c.hint && <span className="truncate" style={{ fontSize: 11.5, color: "var(--text-muted)" }} title={c.hint}>{c.hint}</span>}
            </div>
          ))}
          {!doctor && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Running checks…</div>}
        </div>
      </Card>

      {/* Appearance */}
      <Card style={sectionStyle} padding={22}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Appearance</div>
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 14 }}>Theme, accent, and density for the app interface.</div>
        <div style={{ display: "flex", gap: 28, flexWrap: "wrap", alignItems: "flex-start" }}>
          <div>
            <div style={labelStyle}>Theme</div>
            <Tabs value={tweaks?.theme || "light"} onChange={(v) => setTweak?.("theme", v)} options={[{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }]}/>
          </div>
          <div>
            <div style={labelStyle}>Density</div>
            <Tabs value={tweaks?.density || "comfortable"} onChange={(v) => setTweak?.("density", v)} options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]}/>
          </div>
          <div>
            <div style={labelStyle}>Accent</div>
            <div style={{ display: "flex", gap: 8 }}>
              {accentSwatches.map(([name, hex]) => (
                <button key={name} onClick={() => setTweak?.("accent", name)} title={name} style={{
                  width: 26, height: 26, borderRadius: 6, background: hex, cursor: "pointer",
                  border: (tweaks?.accent === name) ? "2px solid var(--text)" : "2px solid var(--border)",
                }}/>
              ))}
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
};

// ============== RÉSUMÉ LIBRARY (the front door) ==============
// Status → stamp treatment. The persisted DB record and any live run session are
// merged, so drafting/awaiting rows show alongside filed PDFs.
const LIB_STATUS = {
  complete:         { key: "final",  label: "Final",      color: "var(--success)", soft: "var(--success-soft)", icon: "check" },
  "awaiting-input": { key: "needs",  label: "Needs you",  color: "var(--warning)", soft: "var(--warning-soft)", icon: "alert" },
  running:          { key: "active", label: "Active",     color: "var(--accent)",  soft: "var(--accent-soft)",  icon: "loader" },
  queued:           { key: "active", label: "Queued",     color: "var(--accent)",  soft: "var(--accent-soft)",  icon: "loader" },
  retrying:         { key: "active", label: "Retrying",   color: "var(--accent)",  soft: "var(--accent-soft)",  icon: "refresh" },
  failed:           { key: "failed", label: "Failed",     color: "var(--danger)",  soft: "var(--danger-soft)",  icon: "x" },
  cancelled:        { key: "failed", label: "Cancelled",  color: "var(--danger)",  soft: "var(--danger-soft)",  icon: "x" },
};
const libMeta = (status) => LIB_STATUS[status] || LIB_STATUS.queued;

const Masthead = ({ crumb, title, sub, action }) => (
  <div style={{ marginBottom: 22 }}>
    {crumb && <div className="mono" style={{ fontSize: 11, letterSpacing: 0.6, color: "var(--text-faint)", textTransform: "uppercase", marginBottom: 8 }}>{crumb}</div>}
    <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 18, flexWrap: "wrap" }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: "clamp(24px, 3vw, 34px)", fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 1.1 }}>{title}</div>
        {sub && <div style={{ fontSize: 13.5, color: "var(--text-muted)", marginTop: 8, maxWidth: "70ch" }}>{sub}</div>}
      </div>
      {action}
    </div>
  </div>
);

const Stamp = ({ status, size = 34 }) => {
  const m = libMeta(status);
  return (
    <span style={{
      width: size, height: size, borderRadius: "var(--radius-md)", flexShrink: 0,
      display: "grid", placeItems: "center",
      color: m.color, background: m.soft,
      border: `1px solid color-mix(in oklab, ${m.color} 38%, transparent)`,
    }}>
      <Icon name={m.icon} size={size * 0.47} stroke={2.4} style={m.icon === "loader" ? { animation: "spin 1.2s linear infinite" } : {}}/>
    </span>
  );
};

const LibPill = ({ status }) => {
  const m = libMeta(status);
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6, padding: "3px 10px 3px 8px",
      borderRadius: 99, fontSize: 11.5, fontWeight: 600, whiteSpace: "nowrap",
      color: m.color, background: m.soft, border: `1px solid color-mix(in oklab, ${m.color} 32%, transparent)`,
    }}>
      <span style={{ width: 6, height: 6, borderRadius: 99, background: "currentColor" }}/>{m.label}
    </span>
  );
};

// Merge the live run sessions (fresh status) with the persisted library records.
const useLibrary = () => {
  const [rows, setRows] = React.useState(null);
  React.useEffect(() => {
    let alive = true;
    const fetchAll = () => Promise.all([
      listRuns().catch(() => []),
      listLibraryResumes().catch(() => []),
    ]).then(([live, filed]) => {
      if (!alive) return;
      const byId = new Map();
      (Array.isArray(filed) ? filed : []).forEach(r => byId.set(r.id || r.thread_id, normalizeRun(r)));
      (Array.isArray(live) ? live : []).forEach(r => byId.set(r.id || r.thread_id, normalizeRun(r))); // live wins
      setRows(Array.from(byId.values()).sort((a, b) => (b.ts || 0) - (a.ts || 0)));
    });
    fetchAll();
    const id = setInterval(fetchAll, 5000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  return rows;
};

const groupByCompany = (rows) => {
  const map = new Map();
  rows.forEach(r => { const c = r.company || "Unknown"; if (!map.has(c)) map.set(c, []); map.get(c).push(r); });
  return Array.from(map.entries());
};

const fmtFiled = (ts) => {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
};

const RowActions = ({ r, openRun }) => {
  const m = libMeta(r.status);
  const download = (e) => { e.stopPropagation(); if (r.pdf_url) window.open(pdfUrl(r.id), "_blank"); };
  if (m.key === "needs") {
    return <IconButton name="arrow-right" label="Answer & continue" onClick={(e) => { e.stopPropagation(); openRun(r.id, "awaiting-input", r); }} />;
  }
  if (m.key === "failed") {
    return <IconButton name="refresh" label="View & retry" onClick={(e) => { e.stopPropagation(); openRun(r.id, "failed", r); }} />;
  }
  if (m.key === "final" && r.pdf_url) {
    return (
      <div style={{ display: "inline-flex", gap: 2 }}>
        <IconButton name="eye" label="Preview" onClick={download} />
        <IconButton name="download" label="Download PDF" onClick={download} />
      </div>
    );
  }
  return <IconButton name="arrow-right" label="Open" onClick={(e) => { e.stopPropagation(); openRun(r.id, r.status, r); }} />;
};

const LedgerTable = ({ groups, openRun }) => (
  <Card padding={0} style={{ overflow: "hidden" }}>
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 660 }}>
        <thead>
          <tr>
            {["Document", "Status", "Filed", ""].map((h, i) => (
              <th key={i} className="mono" style={{
                textAlign: i === 3 ? "right" : "left", fontSize: 10, textTransform: "uppercase", letterSpacing: 1,
                color: "var(--text-muted)", fontWeight: 600, padding: "12px 16px",
                borderBottom: "2px solid var(--text)", background: "var(--surface)",
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map(([company, rows]) => (
            <React.Fragment key={company}>
              <tr>
                <td colSpan={4} style={{ padding: "10px 16px", background: "var(--bg)", borderBottom: "1px solid var(--border)", borderTop: "1px solid var(--border)" }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 9 }}>
                    <Icon name="folder" size={14} style={{ color: "var(--accent)" }}/>
                    <span className="serif" style={{ fontWeight: 600, fontSize: 15 }}>{company}</span>
                    <span className="mono" style={{ fontSize: 10.5, color: "var(--text-faint)", marginLeft: 6 }}>{rows.length} {rows.length === 1 ? "document" : "documents"}</span>
                  </span>
                </td>
              </tr>
              {rows.map(r => (
                <tr key={r.id} style={{ borderBottom: "1px solid var(--border)", cursor: "pointer" }}
                  onMouseEnter={(e) => e.currentTarget.style.background = "var(--surface-2)"}
                  onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                  onClick={() => openRun(r.id, r.status, r)}
                >
                  <td style={{ padding: "12px 16px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                      <Stamp status={r.status}/>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 13.5, fontWeight: 600, letterSpacing: -0.1 }} className="truncate">{r.role}</div>
                        <div className="mono truncate" style={{ fontSize: 11, color: "var(--text-faint)" }}>
                          {r.pdf || (r.status === "awaiting-input" ? (r.hitlDetail || "waiting on your answers") : r.status === "failed" ? "generation failed" : "in progress")} · #{String(r.id).slice(0, 8)}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td style={{ padding: "12px 16px" }}><LibPill status={r.status}/></td>
                  <td className="mono" style={{ padding: "12px 16px", color: "var(--text-muted)", whiteSpace: "nowrap" }}>{fmtFiled(r.ts)}</td>
                  <td style={{ padding: "12px 16px", textAlign: "right" }} onClick={(e) => e.stopPropagation()}><RowActions r={r} openRun={openRun}/></td>
                </tr>
              ))}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  </Card>
);

const ShelvesBoard = ({ groups, openRun }) => (
  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(258px, 1fr))", gap: 16 }}>
    {groups.map(([company, rows]) => (
      <Card key={company} padding={0} style={{ overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "12px 15px", borderBottom: "2px solid var(--text)" }}>
          <Icon name="folder" size={15} style={{ color: "var(--accent)" }}/>
          <span className="serif" style={{ fontWeight: 600, fontSize: 15 }}>{company}</span>
          <span className="mono" style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-faint)" }}>{rows.length}</span>
        </div>
        {rows.map(r => (
          <button key={r.id} onClick={() => openRun(r.id, r.status, r)} style={{
            width: "100%", textAlign: "left", display: "flex", alignItems: "center", gap: 11,
            padding: "12px 15px", borderBottom: "1px solid var(--border)", background: "transparent", border: "none", cursor: "pointer",
          }}
            onMouseEnter={(e) => e.currentTarget.style.background = "var(--surface-2)"}
            onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
          >
            <Stamp status={r.status} size={28}/>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600 }} className="truncate">{r.role}</div>
              <div className="mono" style={{ fontSize: 10.5, color: "var(--text-faint)" }}>{libMeta(r.status).label} · {fmtFiled(r.ts)}</div>
            </div>
          </button>
        ))}
      </Card>
    ))}
  </div>
);

// Small mock document preview for the grid card's thumbnail.
const PageMock = () => (
  <div style={{ width: 96, height: 124, background: "var(--surface)", borderRadius: 4, boxShadow: "var(--shadow-md)", padding: 10, display: "flex", flexDirection: "column", gap: 4 }}>
    <div style={{ height: 5, width: "58%", borderRadius: 2, background: "var(--text)" }}/>
    <div style={{ height: 3, width: "80%", borderRadius: 2, background: "var(--surface-3)", marginTop: 3 }}/>
    <div style={{ height: 3, width: "68%", borderRadius: 2, background: "var(--surface-3)" }}/>
    <div style={{ height: 3, width: "42%", borderRadius: 2, background: "var(--text)", opacity: 0.5, marginTop: 7 }}/>
    <div style={{ height: 3, width: "86%", borderRadius: 2, background: "var(--surface-3)" }}/>
    <div style={{ height: 3, width: "64%", borderRadius: 2, background: "var(--surface-3)" }}/>
  </div>
);

const GridCard = ({ r, openRun }) => {
  const m = libMeta(r.status);
  return (
    <Card padding={0} hover onClick={() => openRun(r.id, r.status, r)} style={{ overflow: "hidden" }}>
      <div style={{ height: 150, background: m.key === "failed" ? "var(--danger-soft)" : "var(--surface-2)", display: "grid", placeItems: "center", borderBottom: "1px solid var(--border)" }}>
        {m.key === "failed" ? <Icon name="x" size={32} style={{ color: "var(--danger)" }}/> : <PageMock/>}
      </div>
      <div style={{ padding: "12px 14px" }}>
        <div className="mono truncate" style={{ fontSize: 12.5, fontWeight: 600 }}>{r.pdf || `${r.company} — ${r.role}`}</div>
        <div className="truncate" style={{ fontSize: 12, color: "var(--text-faint)", marginTop: 3 }}>{r.company} · {r.role}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
          <LibPill status={r.status}/>
          {r.retries > 0 && <Badge>{r.retries} retr{r.retries === 1 ? "y" : "ies"}</Badge>}
        </div>
      </div>
    </Card>
  );
};

const GridBoard = ({ rows, openRun }) => (
  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))", gap: 16 }}>
    {rows.map(r => <GridCard key={r.id} r={r} openRun={openRun}/>)}
  </div>
);

const LibraryView = ({ goto, openRun, locked, initialFilter }) => {
  const rows = useLibrary();
  const [company, setCompany] = React.useState(null);
  const [status, setStatus] = React.useState(initialFilter || "all");
  const [layout, setLayout] = React.useState("grid");

  const all = rows || [];
  const counts = {
    all: all.length,
    final: all.filter(r => libMeta(r.status).key === "final").length,
    needs: all.filter(r => libMeta(r.status).key === "needs").length,
    active: all.filter(r => libMeta(r.status).key === "active").length,
    failed: all.filter(r => libMeta(r.status).key === "failed").length,
  };
  const companyList = groupByCompany(all).map(([name, rs]) => ({ name, count: rs.length }));
  const visible = all.filter(r =>
    (!company || r.company === company) &&
    (status === "all" || libMeta(r.status).key === status)
  );
  const groups = groupByCompany(visible);

  const chip = (id, label) => (
    <button key={id} onClick={() => setStatus(id)} style={{
      border: "1px solid transparent", background: status === id ? "var(--text)" : "transparent",
      color: status === id ? "var(--bg)" : "var(--text-muted)", fontSize: 12.5, padding: "6px 12px",
      borderRadius: "var(--radius-md)", display: "inline-flex", alignItems: "center", gap: 7, cursor: "pointer", fontWeight: status === id ? 600 : 400,
    }}>
      {label} <span className="mono" style={{ fontSize: 11, opacity: 0.7 }}>{counts[id]}</span>
    </button>
  );

  return (
    <div className="page-pad" style={{ padding: "28px 32px 64px", maxWidth: 1240, margin: "0 auto" }}>
      <Masthead crumb="Workspace / Library" title="Résumé library"
        sub={`${counts.all} résumé${counts.all === 1 ? "" : "s"} across ${companyList.length} compan${companyList.length === 1 ? "y" : "ies"}`}
        action={<Button variant="primary" iconRight="arrow-right" disabled={locked} onClick={() => goto("new")}>New résumé</Button>}
      />

      {/* Summary strip */}
      <Card className="lib-summary" padding={0} style={{ display: "flex", flexWrap: "wrap", overflow: "hidden", marginBottom: 18 }}>
        {[
          { k: "Filed", v: counts.all, tone: "var(--text)" },
          { k: "Final & ready", v: counts.final, tone: "var(--success)" },
          { k: "Needs you", v: counts.needs, tone: "var(--warning)" },
          { k: "Active", v: counts.active, tone: "var(--accent)" },
          { k: "Failed", v: counts.failed, tone: "var(--danger)" },
        ].map((c, i) => (
          <div key={c.k} style={{ flex: 1, padding: "13px 20px", borderRight: i < 4 ? "1px solid var(--border)" : "none", display: "flex", flexDirection: "column", gap: 3 }}>
            <span className="mono" style={{ fontSize: 9.5, textTransform: "uppercase", letterSpacing: 1, color: "var(--text-faint)" }}>{c.k}</span>
            <span className="serif" style={{ fontSize: 25, lineHeight: 1, letterSpacing: -0.4, color: c.tone, fontVariantNumeric: "tabular-nums" }}>{c.v}</span>
          </div>
        ))}
      </Card>

      {/* Toolbar */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
        <div style={{ display: "inline-flex", gap: 2 }}>
          {chip("all", "All")}{chip("final", "Final")}{chip("needs", "Needs you")}{chip("active", "Active")}{chip("failed", "Failed")}
        </div>
        <div style={{ marginLeft: "auto", display: "inline-flex", border: "1px solid var(--border-strong)", borderRadius: "var(--radius-md)", overflow: "hidden" }}>
          {[["grid", "grid", "Grid"], ["table", "list", "Ledger"], ["board", "columns", "Shelves"]].map(([id, icon, label], i) => (
            <button key={id} onClick={() => setLayout(id)} style={{
              border: "none", borderLeft: i ? "1px solid var(--border)" : "none",
              background: layout === id ? "var(--accent)" : "var(--surface)", color: layout === id ? "var(--accent-contrast)" : "var(--text-muted)",
              padding: "7px 12px", display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: layout === id ? 600 : 400, cursor: "pointer",
            }}><Icon name={icon} size={14}/> {label}</button>
          ))}
        </div>
      </div>

      <div className="org-grid" style={{ display: "grid", gridTemplateColumns: "212px 1fr", gap: 20, alignItems: "start" }}>
        {/* company tree */}
        <Card padding={8} style={{ position: "sticky", top: 12 }}>
          <div className="mono" style={{ fontSize: 9.5, textTransform: "uppercase", letterSpacing: 1.2, color: "var(--text-faint)", padding: "8px 9px 6px" }}>Companies</div>
          <TreeItem label="All companies" icon="folder" count={all.length} active={!company} onClick={() => setCompany(null)}/>
          <div style={{ height: 1, background: "var(--border)", margin: "6px 4px" }}/>
          {companyList.map(c => (
            <TreeItem key={c.name} label={c.name} icon="folder" count={c.count} active={company === c.name} onClick={() => setCompany(c.name)}/>
          ))}
        </Card>

        {/* ledger / shelves */}
        <div style={{ minWidth: 0 }}>
          {rows === null ? (
            <Card padding={0}><EmptyState icon="loader" title="Opening the library…" sub="Reading your filed resumes."/></Card>
          ) : visible.length === 0 ? (
            <Card padding={0}><EmptyState icon="folder" title={all.length ? "Nothing matches this filter" : "No resumes filed yet"}
              sub={all.length ? "Try a different company or status." : "Create your first tailored résumé and it will be filed here by company."}
              action={all.length ? null : <Button variant="primary" iconRight="arrow-right" onClick={() => goto("new")}>Create a résumé</Button>}/></Card>
          ) : layout === "grid" ? (
            <GridBoard rows={visible} openRun={openRun}/>
          ) : layout === "table" ? (
            <LedgerTable groups={groups} openRun={openRun}/>
          ) : (
            <ShelvesBoard groups={groups} openRun={openRun}/>
          )}
        </div>
      </div>
    </div>
  );
};

const TreeItem = ({ label, icon, count, active, onClick }) => (
  <button onClick={onClick} style={{
    width: "100%", display: "flex", alignItems: "center", gap: 9, padding: "8px 9px",
    border: "none", borderLeft: "2px solid " + (active ? "var(--accent)" : "transparent"),
    background: active ? "var(--surface-2)" : "transparent", color: active ? "var(--accent)" : "var(--text)",
    borderRadius: "var(--radius-md)", textAlign: "left", cursor: "pointer", fontSize: 13, fontWeight: active ? 600 : 400,
  }}
    onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = "var(--surface-2)"; }}
    onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}
  >
    <Icon name={icon} size={15} style={{ color: active ? "var(--accent)" : "var(--text-faint)" }}/>
    <span className="truncate" style={{ flex: 1 }}>{label}</span>
    <span className="mono" style={{ fontSize: 11, color: "var(--text-faint)" }}>{count}</span>
  </button>
);

// ============== COMPANIES (the cabinet) ==============
const CompaniesView = ({ goto, openRun }) => {
  const rows = useLibrary();
  const all = rows || [];
  const groups = groupByCompany(all);

  return (
    <div className="page-pad" style={{ padding: "28px 32px 64px", maxWidth: 1240, margin: "0 auto" }}>
      <Masthead crumb="Workspace / Companies" title="Companies"
        sub={`${groups.length} compan${groups.length === 1 ? "y" : "ies"} you've applied to`}
        action={<Button variant="primary" iconRight="arrow-right" onClick={() => goto("new")}>New résumé</Button>}
      />
      {rows === null ? (
        <Card padding={0}><EmptyState icon="loader" title="Opening the cabinet…"/></Card>
      ) : groups.length === 0 ? (
        <Card padding={0}><EmptyState icon="building" title="No companies yet" sub="Start a résumé for a company and a folder appears here."
          action={<Button variant="primary" iconRight="arrow-right" onClick={() => goto("new")}>Create a résumé</Button>}/></Card>
      ) : (
        <div className="provider-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(244px, 1fr))", gap: 16 }}>
          {groups.map(([name, rs]) => {
            const final = rs.filter(r => libMeta(r.status).key === "final").length;
            const needs = rs.filter(r => libMeta(r.status).key === "needs").length;
            const failed = rs.filter(r => libMeta(r.status).key === "failed").length;
            const roles = Array.from(new Set(rs.map(r => r.role))).slice(0, 2).join(" · ");
            return (
              <Card key={name} padding={20} hover onClick={() => openRun(rs[0].id, rs[0].status, rs[0])}>
                <div style={{ width: 42, height: 42, borderRadius: "var(--radius-md)", background: "var(--accent-soft)", color: "var(--accent)", display: "grid", placeItems: "center", marginBottom: 14 }}>
                  <Icon name="folder" size={20}/>
                </div>
                <div className="serif" style={{ fontSize: 17, fontWeight: 600, letterSpacing: -0.1 }}>{name}</div>
                <div className="mono" style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }} title={roles}>{roles || "—"}</div>
                <div style={{ display: "flex", gap: 6, marginTop: 15, flexWrap: "wrap" }}>
                  {final > 0 && <span style={tagStyle("var(--success)")}>{final} final</span>}
                  {needs > 0 && <span style={tagStyle("var(--warning)")}>{needs} needs you</span>}
                  {failed > 0 && <span style={tagStyle("var(--danger)")}>{failed} failed</span>}
                  <span style={tagStyle("var(--text-muted)")}>{rs.length} total</span>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
};

const tagStyle = (color) => ({
  fontFamily: "var(--font-mono)", fontSize: 10, padding: "3px 9px", borderRadius: 99,
  background: "var(--bg)", border: "1px solid var(--border)", color, letterSpacing: 0.2,
});

export { Dashboard, SetupWizard, ResumeEditor, NewRun, HistoryView, SettingsView, LibraryView, CompaniesView };

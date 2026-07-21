import React, { useEffect, useRef, useState } from "react";
import { Icon } from "./icons.jsx";
import { Button, IconButton, StatusPill, Badge, EmptyState, Kbd, Logo, MonoTicker, UploadDropzone } from "./components.jsx";
import { Dashboard, SetupWizard, ResumeEditor, NewRun, HistoryView, SettingsView, LibraryView, CompaniesView } from "./screens.jsx";
import { LiveRunView } from "./live-run.jsx";
import { TweaksPanel, TweakColor, TweakRadio, TweakSection, TweakSelect, TweakToggle, useTweaks } from "./tweaks-panel.jsx";
import { ACTIVE_LLM, PARSE_STAGES, PROVIDERS } from "./data.jsx";
import { getSettings, listRuns, uploadResume, runDoctor } from "./api/client.js";
import { subscribeResumeParse } from "./api/ws.js";

// Root app: sidebar + top bar + routing + tweaks.

// Relative time from a unix timestamp (seconds).
const relTime = (ts) => {
  if (!ts) return "recently";
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
};

// Derive the notification inbox from real run summaries (listRuns). We can't tell
// ask-missing from suggestions in a summary, so awaiting-input maps to hitl_ask.
const RUN_STATUS_TO_NOTIF = { "awaiting-input": "hitl_ask", complete: "complete", failed: "failed" };
const runsToNotifications = (runs) =>
  (runs || [])
    .filter(r => RUN_STATUS_TO_NOTIF[r.status])
    .slice(0, 12)
    .map(r => ({
      id: `notif_${r.id || r.thread_id}`,
      kind: RUN_STATUS_TO_NOTIF[r.status],
      runId: r.id || r.thread_id,
      company: r.company || "Unknown",
      role: r.role || "Unknown",
      ts: relTime(r.created_at),
      detail: r.status === "complete" ? `PDF ready${r.duration && r.duration !== "-" ? ` · ${r.duration}` : ""}`
            : r.status === "failed" ? (r.error || "Run failed")
            : "Input needed to continue",
    }));

const NOTIF_META = {
  hitl_ask:     { icon: "alert",       color: "var(--warning)", bg: "var(--warning-soft)", verb: "needs your input",     action: "Answer" },
  hitl_suggest: { icon: "sparkles",    color: "var(--accent)",  bg: "var(--accent-soft)",  verb: "suggestions ready",    action: "Review" },
  complete:     { icon: "check-circle",color: "var(--success)", bg: "var(--success-soft)", verb: "complete",             action: "Open" },
  failed:       { icon: "x-circle",    color: "var(--danger)",  bg: "var(--danger-soft)",  verb: "failed",               action: "Retry" },
};

// Notification dropdown
const NotificationCenter = ({ open, items, onClose, onOpenRun, onMarkAllRead }) => {
  if (!open) return null;
  const unread = items.filter(n => n.unread).length;

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 90 }} />
      <div role="dialog" aria-label="Notifications" style={{
        position: "absolute", top: 10, right: 24, zIndex: 91,
        width: 380, maxWidth: "calc(100vw - 48px)",
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "var(--shadow-lg)",
        overflow: "hidden",
        animation: "panel-slide 200ms",
      }}>
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "12px 14px", borderBottom: "1px solid var(--border)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Icon name="inbox" size={14} style={{ color: "var(--text-muted)" }}/>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Inbox</span>
            {unread > 0 && <Badge tone="accent">{unread} new</Badge>}
          </div>
          <button onClick={onMarkAllRead} style={{ background: "transparent", border: "none", color: "var(--text-muted)", fontSize: 11.5, cursor: "pointer" }}>Mark all read</button>
        </div>

        <div style={{ maxHeight: 460, overflow: "auto" }}>
          {items.length === 0 && (
            <EmptyState icon="inbox" title="No notifications" sub="Background runs and HITL prompts will show up here."/>
          )}
          {items.map(n => {
            const m = NOTIF_META[n.kind];
            return (
              <button key={n.id} onClick={() => onOpenRun(n)}
                style={{
                  display: "grid", gridTemplateColumns: "26px 1fr auto", gap: 12,
                  width: "100%", padding: "12px 14px", textAlign: "left",
                  background: n.unread ? "var(--accent-soft)" : "transparent",
                  border: "none", borderBottom: "1px solid var(--border)",
                  cursor: "pointer", transition: "background var(--t-fast)",
                  alignItems: "flex-start",
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = n.unread ? "var(--accent-soft)" : "var(--surface-2)"}
                onMouseLeave={(e) => e.currentTarget.style.background = n.unread ? "var(--accent-soft)" : "transparent"}
              >
                <span style={{
                  width: 26, height: 26, borderRadius: 99,
                  background: m.bg, color: m.color,
                  display: "flex", alignItems: "center", justifyContent: "center", marginTop: 2,
                  flexShrink: 0,
                }}>
                  <Icon name={m.icon} size={13} stroke={2.4}/>
                </span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontSize: 13, fontWeight: n.unread ? 600 : 500 }} className="truncate">{n.company}</span>
                    {n.unread && <span style={{ width: 6, height: 6, borderRadius: 99, background: "var(--accent)", flexShrink: 0 }}/>}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }} className="truncate">
                    <span style={{ color: m.color, fontWeight: 500 }}>{m.verb}</span>
                    <span style={{ margin: "0 6px", color: "var(--text-faint)" }}>·</span>
                    {n.detail}
                  </div>
                  <div className="mono" style={{ fontSize: 10.5, color: "var(--text-faint)", marginTop: 4, letterSpacing: 0.2 }}>
                    {n.role} · {n.runId} · {n.ts}
                  </div>
                </div>
                <span style={{ flexShrink: 0 }}>
                  <span style={{
                    display: "inline-flex", alignItems: "center", gap: 4,
                    padding: "3px 8px", background: "var(--surface)",
                    border: "1px solid var(--border-strong)",
                    borderRadius: 99, fontSize: 11, color: "var(--text)", fontWeight: 500,
                  }}>{m.action}<Icon name="arrow-right" size={10}/></span>
                </span>
              </button>
            );
          })}
        </div>

        <div style={{
          padding: "8px 14px", borderTop: "1px solid var(--border)", background: "var(--surface-2)",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          fontSize: 11.5, color: "var(--text-muted)",
        }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 6, height: 6, borderRadius: 99, background: unread > 0 ? "var(--accent)" : "var(--text-faint)" }}/>
            {unread > 0 ? `${unread} unread` : "All caught up"}
          </span>
          <span className="mono">{items.length} total</span>
        </div>
      </div>
    </>
  );
};

// Slide-in toast for new HITL events
const HitlToast = ({ toast, onClose, onOpenRun }) => {
  if (!toast) return null;
  const m = NOTIF_META[toast.kind];
  return (
    <div style={{
      position: "fixed", bottom: 24, right: 24, zIndex: 95,
      width: 380, maxWidth: "calc(100vw - 48px)",
      background: "var(--surface)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-lg)",
      boxShadow: "var(--shadow-lg)",
      padding: 14,
      display: "grid", gridTemplateColumns: "28px 1fr auto", gap: 12,
      animation: "toast-in 320ms cubic-bezier(.2,.7,.3,1)",
    }}>
      <span style={{
        width: 28, height: 28, borderRadius: 99,
        background: m.bg, color: m.color,
        display: "flex", alignItems: "center", justifyContent: "center",
        animation: "pulse-ring 1.6s ease-out 1",
      }}>
        <Icon name={m.icon} size={14} stroke={2.4}/>
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{toast.company} {m.verb}</div>
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 3 }}>{toast.detail}</div>
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <Button size="sm" variant="primary" onClick={() => onOpenRun(toast)}>{m.action}</Button>
          <Button size="sm" variant="ghost" onClick={onClose}>Dismiss</Button>
        </div>
      </div>
      <IconButton name="x" label="Close" onClick={onClose}/>
    </div>
  );
};

// ===== Base resume parsing — modal, banner, and global lock =====
// `parsing.statuses` is a { [stageId]: "running"|"done"|"failed" } map fed by the
// real /ws/resume-parse WebSocket. Progress is done-count / known-stage-count.
const parseDoneCount = (parsing) => PARSE_STAGES.filter(s => parsing.statuses?.[s.id] === "done").length;

const BaseResumeParseModal = ({ parsing, onClose, onMinimize, onCancel }) => {
  if (!parsing) return null;
  const stages = PARSE_STAGES;
  const completed = parsing.completed;
  const failed = parsing.failed;
  const [elapsed, setElapsed] = React.useState(0);

  React.useEffect(() => {
    if (completed || failed) return;
    const id = setInterval(() => setElapsed(Date.now() - parsing.startedAt), 100);
    return () => clearInterval(id);
  }, [completed, failed, parsing.startedAt]);

  const doneCount = parseDoneCount(parsing);
  const pct = completed ? 100 : Math.min(100, (doneCount / stages.length) * 100);

  const fmt = (ms) => {
    const s = ms / 1000;
    return s < 10 ? s.toFixed(1) + "s" : Math.round(s) + "s";
  };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(15, 12, 8, 0.45)",
      zIndex: 110, display: "flex", alignItems: "center", justifyContent: "center",
      padding: 20, animation: "fade-in 200ms",
    }}>
      <div role="dialog" aria-modal="true" style={{
        width: "100%", maxWidth: 540,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "var(--shadow-lg)",
        overflow: "hidden",
        animation: "panel-slide 240ms",
      }}>
        {/* Header */}
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
            <span style={{
              width: 28, height: 28, borderRadius: 6,
              background: failed ? "var(--danger-soft)" : completed ? "var(--success-soft)" : "var(--accent-soft)",
              color: failed ? "var(--danger)" : completed ? "var(--success)" : "var(--accent)",
              display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
            }}
              className={completed ? "pop-in" : ""}
            >
              <Icon name={failed ? "x" : completed ? "check" : "file-text"} size={14} stroke={2.4}/>
            </span>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>
                {failed ? "Resume parsing failed" : completed ? "Base resume parsed" : "Parsing your base resume"}
              </div>
              <div className="mono truncate" style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>{parsing.file}</div>
            </div>
          </div>
          {!completed && !failed && <IconButton name="x" label="Minimize" onClick={onMinimize}/>}
          {(completed || failed) && <IconButton name="x" label="Close" onClick={onClose}/>}
        </div>

        {/* Progress bar */}
        <div style={{ padding: "14px 20px 0" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
            <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>
              {failed ? "failed" : completed ? "complete" : `${doneCount} of ${stages.length} done`}
            </span>
            <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>
              {fmt(elapsed)} elapsed
            </span>
          </div>
          <div style={{
            height: 4, background: "var(--surface-2)", borderRadius: 99,
            overflow: "hidden", position: "relative",
          }}>
            <div style={{
              height: "100%",
              width: `${pct}%`,
              background: failed ? "var(--danger)" : completed ? "var(--success)" : "var(--accent)",
              borderRadius: 99,
              transition: "width 300ms cubic-bezier(.4,0,.2,1), background 200ms",
            }}/>
          </div>
        </div>

        {/* Stage list */}
        <div style={{ padding: "16px 20px 4px", display: "flex", flexDirection: "column", gap: 4 }}>
          {stages.map((s) => {
            const status = completed ? "done" : (parsing.statuses?.[s.id] || "pending");
            return (
              <div key={s.id} style={{
                display: "grid", gridTemplateColumns: "22px 1fr auto", gap: 10,
                alignItems: "flex-start", padding: "8px 0",
              }}>
                <span style={{
                  width: 18, height: 18, borderRadius: 99, marginTop: 1,
                  background: status === "done" ? "var(--success)" : status === "failed" ? "var(--danger)" : status === "running" ? "var(--accent-soft)" : "var(--surface-2)",
                  border: "1px solid " + (status === "done" ? "var(--success)" : status === "failed" ? "var(--danger)" : status === "running" ? "var(--accent)" : "var(--border-strong)"),
                  color: "white",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  position: "relative", flexShrink: 0,
                }}>
                  {status === "done" && <Icon name="check" size={10} stroke={3}/>}
                  {status === "failed" && <Icon name="x" size={10} stroke={3}/>}
                  {status === "running" && <Icon name="loader" size={10} style={{ color: "var(--accent)", animation: "spin 1s linear infinite" }}/>}
                </span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: status === "running" ? 600 : 500, color: status === "pending" ? "var(--text-muted)" : "var(--text)" }}>
                    {s.label}
                  </div>
                  {s.sub && <div className="mono" style={{ fontSize: 11, color: "var(--text-faint)", marginTop: 2 }}>{s.sub}</div>}
                </div>
                <span className="mono" style={{ fontSize: 10.5, color: "var(--text-faint)", paddingTop: 3 }}>
                  {status === "done" ? "✓" : status === "running" ? "…" : ""}
                </span>
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div style={{ padding: "14px 20px", borderTop: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, background: "var(--surface-2)" }}>
          {failed ? (
            <>
              <div style={{ fontSize: 12, color: "var(--danger)", minWidth: 0 }} className="truncate">
                {parsing.error || "Parsing failed. Check the file and try again."}
              </div>
              <Button size="sm" variant="secondary" onClick={onClose}>Close</Button>
            </>
          ) : !completed ? (
            <>
              <div style={{ fontSize: 11.5, color: "var(--text-muted)", display: "flex", alignItems: "center", gap: 6 }}>
                <Icon name="alert" size={11} style={{ color: "var(--warning)" }}/>
                <span>New runs are paused while parsing</span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
                <Button size="sm" variant="secondary" iconRight="chevron-down" onClick={onMinimize}>Minimize</Button>
              </div>
            </>
          ) : (
            <>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                Resume parsed and saved to <span className="mono" style={{ color: "var(--text)" }}>base_resume.yaml</span>
              </div>
              <Button size="sm" variant="primary" onClick={onClose}>Done</Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

// Thin banner at top of every screen while parsing is in-flight (modal minimized)
const ParsingBanner = ({ parsing, onOpen }) => {
  if (!parsing || parsing.completed || parsing.failed || parsing.modalOpen) return null;
  const [elapsed, setElapsed] = React.useState(0);
  React.useEffect(() => {
    const id = setInterval(() => setElapsed(Date.now() - parsing.startedAt), 200);
    return () => clearInterval(id);
  }, [parsing.startedAt]);
  const doneCount = parseDoneCount(parsing);
  const stage = PARSE_STAGES.find(s => parsing.statuses?.[s.id] === "running")
             || PARSE_STAGES[Math.min(doneCount, PARSE_STAGES.length - 1)];
  const pct = Math.min(100, (doneCount / PARSE_STAGES.length) * 100);

  return (
    <button onClick={onOpen} style={{
      width: "100%", padding: "8px 24px",
      background: "var(--accent-soft)",
      border: "none",
      borderBottom: "1px solid color-mix(in oklab, var(--accent) 30%, transparent)",
      display: "flex", alignItems: "center", gap: 12,
      cursor: "pointer", textAlign: "left",
      position: "relative", overflow: "hidden",
    }}>
      <span style={{ position: "absolute", top: 0, left: 0, bottom: 0, width: `${pct}%`, background: "color-mix(in oklab, var(--accent) 14%, transparent)", transition: "width 300ms" }}/>
      <Icon name="loader" size={14} style={{ animation: "spin 1.2s linear infinite", color: "var(--accent)", position: "relative" }}/>
      <span style={{ fontSize: 12.5, fontWeight: 500, position: "relative" }}>
        Parsing your base resume — <span style={{ color: "var(--accent)" }}>{stage.label}</span>
      </span>
      <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: "auto", position: "relative" }}>
        {doneCount}/{PARSE_STAGES.length} · {(elapsed / 1000).toFixed(1)}s
      </span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11.5, color: "var(--accent)", fontWeight: 500, position: "relative" }}>
        View details <Icon name="arrow-right" size={11}/>
      </span>
    </button>
  );
};

// Replace base resume modal (initial drop zone before parsing kicks off)
const ReplaceBaseResumeModal = ({ open, onClose, onUpload }) => {
  if (!open) return null;
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(15, 12, 8, 0.45)",
      zIndex: 105, display: "flex", alignItems: "center", justifyContent: "center",
      padding: 20, animation: "fade-in 200ms",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width: "100%", maxWidth: 540,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "var(--shadow-lg)",
        overflow: "hidden",
        animation: "panel-slide 240ms",
      }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ width: 26, height: 26, borderRadius: 6, background: "var(--surface-2)", color: "var(--text)", display: "flex", alignItems: "center", justifyContent: "center", border: "1px solid var(--border)" }}>
              <Icon name="upload" size={13}/>
            </span>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>Replace base resume</div>
              <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 1 }}>This overwrites your current <span className="mono">base_resume.yaml</span>.</div>
            </div>
          </div>
          <IconButton name="x" label="Close" onClick={onClose}/>
        </div>

        <div style={{ padding: 20 }}>
          <div style={{
            padding: "14px 14px",
            background: "var(--warning-soft)",
            border: "1px solid color-mix(in oklab, var(--warning) 25%, transparent)",
            borderRadius: "var(--radius-md)",
            display: "flex", gap: 10, marginBottom: 16,
          }}>
            <Icon name="alert" size={14} style={{ color: "var(--warning)", flexShrink: 0, marginTop: 2 }}/>
            <div style={{ fontSize: 12.5, color: "var(--text)", lineHeight: 1.55 }}>
              Parsing will use the LLM and takes <span className="mono">~10–12s</span>. <b>New runs are paused</b> during parsing to avoid mid-flight schema mismatches. Existing runs continue.
            </div>
          </div>

          <UploadDropzone onUpload={onUpload}/>
        </div>
      </div>
    </div>
  );
};

// Sidebar
const Sidebar = ({ route, goto, collapsed, setCollapsed, locked, settings = ACTIVE_LLM }) => {
  const items = [
    { id: "new", icon: "play", label: "Create" },
    { id: "library", icon: "folder", label: "Résumé library" },
    { id: "companies", icon: "building", label: "Companies" },
    { id: "resume", icon: "file-text", label: "Base resume" },
  ];
  const secondary = [
    { id: "settings", icon: "settings", label: "Settings" },
    { id: "setup", icon: "stethoscope", label: "Setup" },
  ];

  const provider = PROVIDERS.find(p => p.id === settings.providerId) || PROVIDERS[0];
  const w = collapsed ? "var(--sidebar-w-collapsed)" : "var(--sidebar-w)";

  return (
    <div style={{
      width: w, transition: `width var(--t-mid)`,
      borderRight: "1px solid var(--border)",
      background: "var(--surface)",
      display: "flex", flexDirection: "column",
      flexShrink: 0,
      overflow: "hidden",
    }}>
      {/* Logo + product */}
      <div style={{
        height: "var(--topbar-h)",
        display: "flex", alignItems: "center", padding: collapsed ? 0 : "0 16px", justifyContent: collapsed ? "center" : "flex-start",
        borderBottom: "1px solid var(--border)",
        gap: 10, flexShrink: 0,
      }}>
        <Logo size={24}/>
        {!collapsed && (
          <div style={{ minWidth: 0 }}>
            <div className="serif" style={{ fontSize: 15, fontWeight: 600, letterSpacing: 0, lineHeight: 1.15 }}>Resume Generator</div>
            <div className="mono" style={{ fontSize: 9.5, color: "var(--text-faint)", letterSpacing: 1, textTransform: "uppercase" }}>Filing room</div>
          </div>
        )}
      </div>

      {/* Main nav */}
      <div style={{ flex: 1, overflow: "auto", padding: collapsed ? "10px 6px" : "12px 10px" }}>
        {!collapsed && <div className="mono" style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.6, padding: "4px 6px 8px" }}>Workroom</div>}
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {items.map(it => (
            <NavItem key={it.id} {...it}
              active={route === it.id}
              collapsed={collapsed}
              locked={locked && it.id === "new"}
              onClick={() => { if (!(locked && it.id === "new")) goto(it.id); }} />
          ))}
        </div>

        {!collapsed && <div className="mono" style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.6, padding: "18px 6px 8px" }}>System</div>}
        {collapsed && <div style={{ height: 14 }}/>}
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {secondary.map(it => (
            <NavItem key={it.id} {...it} active={route === it.id} collapsed={collapsed} onClick={() => goto(it.id)} />
          ))}
        </div>
      </div>

      {/* Footer: provider pill */}
      <div style={{
        padding: collapsed ? 8 : 10,
        borderTop: "1px solid var(--border)",
        flexShrink: 0,
      }}>
        {collapsed ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
            <button onClick={() => goto("settings")} title={`${provider.name} · ${settings.defaultModel}\nvision: ${settings.visionEnabled ? settings.visionModel : "off"}\n${ACTIVE_LLM.status} · ${settings.latencyMs} ms`}
              style={{
                position: "relative", width: 32, height: 32, borderRadius: 7,
                background: "var(--accent)", color: "var(--accent-contrast)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: 14,
                border: "none", cursor: "pointer",
              }}>
              {provider.logo}
              <span style={{
                position: "absolute", bottom: -2, right: -2,
                width: 10, height: 10, borderRadius: 99,
                background: "var(--success)",
                border: "2px solid var(--surface)",
              }}/>
            </button>
            <IconButton name="sidebar" label="Expand sidebar" onClick={() => setCollapsed(false)} />
          </div>
        ) : (
          <div role="button" tabIndex={0} onClick={() => goto("settings")}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") goto("settings"); }}
            style={{
            width: "100%", display: "block", textAlign: "left",
            padding: "10px 11px",
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-md)",
            cursor: "pointer",
            transition: `border-color var(--t-fast), background var(--t-fast)`,
          }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--border-strong)"; e.currentTarget.style.background = "var(--surface-3)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.background = "var(--surface-2)"; }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                <span style={{ position: "relative", flexShrink: 0 }}>
                  <span style={{
                    width: 22, height: 22, borderRadius: 5,
                    background: "var(--accent)", color: "var(--accent-contrast)",
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: 12,
                  }}>{provider.logo}</span>
                  <span style={{
                    position: "absolute", bottom: -2, right: -2,
                    width: 8, height: 8, borderRadius: 99,
                    background: "var(--success)",
                    border: "2px solid var(--surface-2)",
                  }}/>
                </span>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span className="truncate" style={{ fontSize: 11.5, fontWeight: 500, color: "var(--text)" }}>{provider.name}</span>
                    <span style={{ fontSize: 10, color: "var(--success)", fontWeight: 500 }}>● live</span>
                  </div>
                  <div className="mono truncate" style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 2 }} title={settings.defaultModel}>
                    {settings.defaultModel}
                  </div>
                </div>
              </div>
              <IconButton name="sidebar" label="Collapse" onClick={(e) => { e.stopPropagation(); setCollapsed(true); }} />
            </div>
            {settings.visionEnabled && (
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--border)" }}>
                <Icon name="eye" size={11} style={{ color: "var(--text-faint)" }}/>
                <span style={{ fontSize: 10, color: "var(--text-muted)" }}>vision</span>
                <span className="mono truncate" style={{ fontSize: 10, color: "var(--text-faint)", flex: 1 }} title={settings.visionModel}>
                  {settings.visionModel}
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const NavItem = ({ icon, label, active, collapsed, onClick, locked }) => (
  <button onClick={onClick} title={collapsed ? (locked ? `${label} — paused while parsing` : label) : (locked ? "Paused while base resume is parsing" : null)}
    disabled={locked}
    style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: collapsed ? "9px 0" : "8px 10px",
      justifyContent: collapsed ? "center" : "flex-start",
      background: active ? "var(--accent-soft)" : "transparent",
      color: locked ? "var(--text-faint)" : active ? "var(--accent)" : "var(--text-muted)",
      border: "1px solid " + (active ? "var(--accent-ring)" : "transparent"),
      borderRadius: "var(--radius-md)",
      cursor: locked ? "not-allowed" : "pointer", textAlign: "left",
      transition: `all var(--t-fast)`,
      fontWeight: active ? 500 : 400, fontSize: 13.5,
      opacity: locked ? 0.6 : 1,
      position: "relative",
    }}
    onMouseEnter={(e) => { if (!active && !locked) { e.currentTarget.style.background = "var(--surface-2)"; e.currentTarget.style.color = "var(--text)"; } }}
    onMouseLeave={(e) => { if (!active && !locked) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-muted)"; } }}
  >
    <Icon name={icon} size={15} stroke={2}/>
    {!collapsed && <span style={{ flex: 1 }}>{label}</span>}
    {!collapsed && locked && (
      <Icon name="loader" size={11} style={{ animation: "spin 1.2s linear infinite", color: "var(--accent)" }}/>
    )}
  </button>
);

// Top bar
const TopBar = ({ route, runTitle, doctorBanner, openCmdK, openNotifs, unreadCount, bellRef, settings }) => {
  const titles = {
    dashboard: "Overview", new: "Create", library: "Résumé library", companies: "Companies",
    resume: "Base resume", history: "History", settings: "Settings", setup: "Setup",
    run: runTitle || "Run",
  };
  const sections = {
    new: "Workroom", library: "Library", companies: "Cabinet", resume: "Workroom",
    settings: "System", setup: "System", run: "Library", dashboard: "Overview", history: "Library",
  };
  return (
    <div style={{
      height: "var(--topbar-h)", flexShrink: 0,
      borderBottom: "1px solid var(--border)",
      background: "var(--surface)",
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "0 24px", gap: 12,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--text-faint)", letterSpacing: 0.8, textTransform: "uppercase" }}>{sections[route] || "Workroom"}</span>
        <span style={{ color: "var(--text-faint)" }}>/</span>
        <span className="serif" style={{ fontSize: 16, fontWeight: 600 }}>{titles[route] || route}</span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        {/* Active LLM pill */}
        <button onClick={() => { /* could open command palette/settings */ }} title={`provider: ${ACTIVE_LLM.providerName} · default: ${settings.defaultModel}${settings.visionEnabled ? ` · vision: ${settings.visionModel}` : ""} · ${settings.latencyMs}ms`}
          style={{
            display: "inline-flex", alignItems: "center", gap: 8,
            height: 30, padding: "0 10px",
            background: "var(--surface)",
            border: "1px solid var(--border-strong)",
            borderRadius: "var(--radius-md)",
            cursor: "pointer", transition: `background var(--t-fast)`,
          }}
          onMouseEnter={(e) => e.currentTarget.style.background = "var(--surface-2)"}
          onMouseLeave={(e) => e.currentTarget.style.background = "var(--surface)"}
        >
          <span style={{ position: "relative", display: "inline-flex" }}>
            <span style={{ width: 6, height: 6, borderRadius: 99, background: "var(--success)" }}/>
            <span style={{ position: "absolute", inset: -2, borderRadius: 99, background: "var(--success)", opacity: 0.35, animation: "pulse-ring 2s ease-out infinite" }}/>
          </span>
          <span className="mono" style={{ fontSize: 11.5, color: "var(--text)", fontWeight: 500, whiteSpace: "nowrap" }}>{settings.defaultModel}</span>
          {settings.visionEnabled && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 3, color: "var(--text-faint)" }} title={`vision: ${settings.visionModel}`}>
              <Icon name="eye" size={11}/>
            </span>
          )}
        </button>

        {/* Doctor pill */}
        <span style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          padding: "4px 10px",
          background: doctorBanner ? "var(--danger-soft)" : "var(--success-soft)",
          color: doctorBanner ? "var(--danger)" : "var(--success)",
          borderRadius: 99, fontSize: 11.5, fontWeight: 500,
          border: `1px solid ${doctorBanner ? "var(--danger)" : "var(--success)"}1f`,
        }}>
          <span style={{ width: 6, height: 6, borderRadius: 99, background: "currentColor", animation: doctorBanner ? "none" : "blink 2s infinite" }}/>
          Doctor {doctorBanner ? "issue" : "ok"}
        </span>

        {/* Notification bell */}
        <button ref={bellRef} onClick={openNotifs} aria-label="Notifications" style={{
          position: "relative", width: 30, height: 30,
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          background: "var(--surface)",
          border: "1px solid var(--border-strong)",
          borderRadius: "var(--radius-md)",
          color: "var(--text-muted)",
          cursor: "pointer",
          transition: `color var(--t-fast), background var(--t-fast)`,
        }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "var(--surface-2)"; e.currentTarget.style.color = "var(--text)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "var(--surface)"; e.currentTarget.style.color = "var(--text-muted)"; }}
        >
          <Icon name="bell" size={14}/>
          {unreadCount > 0 && (
            <span style={{
              position: "absolute", top: -4, right: -4,
              minWidth: 16, height: 16, padding: "0 4px",
              background: "var(--accent)", color: "var(--accent-contrast)",
              borderRadius: 99, fontSize: 10, fontWeight: 600,
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              border: "2px solid var(--surface)",
              boxShadow: "0 0 0 2px var(--accent-ring)",
            }} className="mono">{unreadCount}</span>
          )}
          {unreadCount > 0 && (
            <span style={{
              position: "absolute", inset: -1, borderRadius: "var(--radius-md)",
              border: "1px solid var(--accent-ring)",
              animation: "pulse-ring 2s ease-out infinite",
              pointerEvents: "none",
            }}/>
          )}
        </button>

        {/* Cmd-K button */}
        <button onClick={openCmdK} style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          height: 30, padding: "0 8px 0 10px",
          background: "var(--surface)",
          border: "1px solid var(--border-strong)",
          borderRadius: "var(--radius-md)",
          color: "var(--text-muted)", fontSize: 12.5, cursor: "pointer",
        }}>
          <Icon name="search" size={13}/>
          <span>Search…</span>
          <Kbd>⌘</Kbd><Kbd>K</Kbd>
        </button>
      </div>
    </div>
  );
};

// Doctor banner — surfaces the first failing doctor check.
const DoctorBanner = ({ doctor, goto, onDismiss }) => {
  const failing = (doctor?.checks || []).filter(c => !c.ok);
  const first = failing[0];
  return (
    <div style={{
      padding: "10px 24px",
      background: "var(--danger-soft)",
      borderBottom: "1px solid color-mix(in oklab, var(--danger) 25%, transparent)",
      display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
      color: "var(--text)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
        <Icon name="alert" size={14} style={{ color: "var(--danger)", flexShrink: 0 }}/>
        <span style={{ fontSize: 12.5 }} className="truncate">
          {first
            ? <><b>{first.label} check failed.</b> {first.hint}</>
            : <><b>Environment issue detected.</b> Open Settings to run the doctor.</>}
          {failing.length > 1 && <span style={{ color: "var(--text-muted)" }}> (+{failing.length - 1} more)</span>}
        </span>
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <Button size="sm" variant="danger-outline" onClick={() => goto?.("settings")}>Fix it</Button>
        <IconButton name="x" label="Dismiss" onClick={onDismiss} />
      </div>
    </div>
  );
};

// Cmd-K palette
const CommandPalette = ({ open, onClose, goto, openRun, lastRun }) => {
  const [query, setQuery] = React.useState("");
  const ref = React.useRef(null);
  React.useEffect(() => { if (open) setTimeout(() => ref.current?.focus(), 50); }, [open]);

  const lastRunId = lastRun?.id || lastRun?.thread_id || null;
  const select = (id) => {
    if (id === "run") { if (lastRunId) openRun?.(lastRunId); else { onClose(); return; } }
    else goto(id);
    onClose();
  };

  const actions = [
    { id: "new", label: "Create résumé", sub: "Tailor to a company", icon: "play", kbd: ["⌘", "N"] },
    { id: "library", label: "Open library", sub: "All filed resumes by company", icon: "folder" },
    { id: "companies", label: "Companies", sub: "Browse company folders", icon: "building" },
    { id: "resume", label: "Open base resume", sub: "Edit your master CV", icon: "file-text", kbd: ["⌘", "B"] },
    { id: "run", label: "Open last run", sub: lastRun ? `${lastRun.company || "Run"} · ${relTime(lastRun.created_at)}` : "No recent runs", icon: "arrow-right" },
    { id: "settings", label: "Settings", sub: "Provider, retries, output…", icon: "settings", kbd: ["⌘", ","] },
    { id: "setup", label: "Re-run setup wizard", sub: "Recheck doctor", icon: "stethoscope" },
  ].filter(a => !query || a.label.toLowerCase().includes(query.toLowerCase()) || a.sub.toLowerCase().includes(query.toLowerCase()));

  if (!open) return null;

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(15, 12, 8, 0.4)",
      zIndex: 100, display: "flex", alignItems: "flex-start", justifyContent: "center",
      paddingTop: 120, animation: "fade-in 160ms",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width: "100%", maxWidth: 540,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "var(--shadow-lg)",
        overflow: "hidden",
        animation: "panel-slide 200ms",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 16px", borderBottom: "1px solid var(--border)" }}>
          <Icon name="search" size={15} style={{ color: "var(--text-muted)" }}/>
          <input ref={ref} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Type a command or search…" style={{
            flex: 1, height: 48, background: "transparent", border: "none", outline: "none",
            fontSize: 14, color: "var(--text)",
          }}/>
          <Kbd>ESC</Kbd>
        </div>
        <div style={{ maxHeight: 380, overflow: "auto", padding: 6 }}>
          {actions.length === 0 && (
            <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>No matches</div>
          )}
          {actions.map((a, i) => (
            <button key={a.id}
              onClick={() => select(a.id)}
              style={{
                display: "flex", alignItems: "center", gap: 12,
                width: "100%", padding: "10px 12px",
                background: i === 0 ? "var(--surface-2)" : "transparent",
                border: "none", borderRadius: "var(--radius-md)",
                textAlign: "left", cursor: "pointer",
              }}
              onMouseEnter={(e) => e.currentTarget.style.background = "var(--surface-2)"}
              onMouseLeave={(e) => e.currentTarget.style.background = i === 0 ? "var(--surface-2)" : "transparent"}
            >
              <span style={{ width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text-muted)" }}>
                <Icon name={a.icon} size={14}/>
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{a.label}</div>
                <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{a.sub}</div>
              </div>
              {a.kbd && <div style={{ display: "flex", gap: 3 }}>{a.kbd.map(k => <Kbd key={k}>{k}</Kbd>)}</div>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

// Map hex <-> accent key (so the existing TweakColor swatch UI can drive our data-attribute)
const ACCENT_HEX = { indigo: "#31507E", pine: "#1F6F5C", oxblood: "#8A2F2A", graphite: "#33312B" };
const HEX_TO_ACCENT = Object.fromEntries(Object.entries(ACCENT_HEX).map(([k, v]) => [v.toLowerCase(), k]));
const TWEAK_DEFAULTS = {
  theme: "light",
  accent: "indigo",
  sidebar: "expanded",
  density: "comfortable",
  runState: "running",
  doctorBanner: false,
};

// Tweaks panel content
const TweaksContent = ({ t, setTweak }) => (
  <>
    <TweakSection label="Theme">
      <TweakRadio label="Mode" value={t.theme} onChange={(v) => setTweak("theme", v)}
        options={[{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} />
    </TweakSection>

    <TweakSection label="Accent">
      <TweakColor label="Color" value={ACCENT_HEX[t.accent] || ACCENT_HEX.indigo}
        onChange={(hex) => setTweak("accent", HEX_TO_ACCENT[String(hex).toLowerCase()] || "indigo")}
        options={[ACCENT_HEX.indigo, ACCENT_HEX.pine, ACCENT_HEX.oxblood, ACCENT_HEX.graphite]} />
    </TweakSection>

    <TweakSection label="Layout">
      <TweakRadio label="Sidebar" value={t.sidebar} onChange={(v) => setTweak("sidebar", v)}
        options={[{ value: "expanded", label: "Expanded" }, { value: "collapsed", label: "Collapsed" }]} />
      <TweakRadio label="Density" value={t.density} onChange={(v) => setTweak("density", v)}
        options={[{ value: "compact", label: "Compact" }, { value: "comfortable", label: "Comfy" }]} />
    </TweakSection>

    <TweakSection label="Run state">
      <TweakSelect label="Snapshot" value={t.runState} onChange={(v) => setTweak("runState", v)}
        options={[
          { value: "running", label: "Running (gap analysis)" },
          { value: "awaiting-input", label: "Awaiting input (ask missing)" },
          { value: "suggestions", label: "Awaiting input (suggestions)" },
          { value: "complete", label: "Complete (PDF ready)" },
          { value: "failed", label: "Failed (compile error)" },
        ]} />
    </TweakSection>

    <TweakSection label="System">
      <TweakToggle label="Doctor red banner" value={t.doctorBanner} onChange={(v) => setTweak("doctorBanner", v)} />
    </TweakSection>
  </>
);

// Root app
export const App = () => {
  const [route, setRoute] = useState("library"); // library | new | companies | resume | history | settings | setup | run | dashboard
  const [cmdK, setCmdK] = useState(false);
  const [notifsOpen, setNotifsOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const [parsing, setParsing] = useState(null);
  const [replaceOpen, setReplaceOpen] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [selectedRunTitle, setSelectedRunTitle] = useState(null);
  const [lastRun, setLastRun] = useState(null);
  const [appSettings, setAppSettings] = useState(ACTIVE_LLM);
  const [runs, setRuns] = useState([]);
  const [readNotifIds, setReadNotifIds] = useState(() => new Set());
  const [doctor, setDoctor] = useState(null);
  const [doctorDismissed, setDoctorDismissed] = useState(false);
  const bellRef = useRef(null);
  const parseUnsubRef = useRef(null);
  const toastedRef = useRef(new Set());

  useEffect(() => { getSettings().then(setAppSettings).catch(() => {}); }, []);
  useEffect(() => { runDoctor().then(setDoctor).catch(() => setDoctor(null)); }, []);

  // ----- Poll runs: drives lastRun (cmd palette) + the notification inbox -----
  useEffect(() => {
    let alive = true;
    const fetchRuns = () => listRuns()
      .then(items => {
        if (!alive || !Array.isArray(items)) return;
        setRuns(items);
        setLastRun(items[0] || null); // list_runs is sorted newest-first
      })
      .catch(() => {});
    fetchRuns();
    const id = setInterval(fetchRuns, 5000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const notifications = runsToNotifications(runs).map(n => ({ ...n, unread: !readNotifIds.has(n.id) }));

  // ----- Real base-resume upload + parse (POST /api/resume/upload → WS) -----
  const startParse = async (file) => {
    if (!(file instanceof File)) return;
    setReplaceOpen(false);
    setParsing({ file: file.name, startedAt: Date.now(), statuses: {}, completed: false, failed: false, error: null, modalOpen: true });
    let job;
    try {
      job = await uploadResume(file);
    } catch (err) {
      setParsing(p => p ? { ...p, failed: true, error: err.message || "Upload failed." } : null);
      return;
    }
    parseUnsubRef.current = subscribeResumeParse(job.job_id, (ev) => {
      setParsing(p => {
        if (!p) return null;
        const statuses = { ...p.statuses, [ev.stage_id]: ev.status };
        const failed = ev.status === "failed";
        const completed = ev.stage_id === "write_yaml" && ev.status === "done";
        return {
          ...p,
          statuses,
          failed: failed || p.failed,
          error: failed ? (ev.detail || "Parsing failed.") : p.error,
          completed: completed || p.completed,
        };
      });
    });
  };

  const endParse = () => {
    parseUnsubRef.current?.();
    parseUnsubRef.current = null;
    setParsing(null);
  };

  const isLocked = !!parsing && !parsing.completed && !parsing.failed;

  // Tweaks
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);

  // Apply theme + accent to <html>
  useEffect(() => {
    document.documentElement.dataset.theme = tweaks.theme;
    document.documentElement.dataset.accent = tweaks.accent;
  }, [tweaks.theme, tweaks.accent]);

  // Sidebar mirror from tweak
  const [sidebarCollapsed, setSidebarCollapsed] = useState(tweaks.sidebar === "collapsed");
  useEffect(() => { setSidebarCollapsed(tweaks.sidebar === "collapsed"); }, [tweaks.sidebar]);
  useEffect(() => { setTweak("sidebar", sidebarCollapsed ? "collapsed" : "expanded"); }, [sidebarCollapsed]);

  // Cmd-K shortcut
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); setCmdK(true); }
      if (e.key === "Escape") setCmdK(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Splash hide
  useEffect(() => {
    const sp = document.getElementById("splash");
    if (sp) sp.style.display = "none";
  }, []);

  // Surface a toast once per new run that needs your attention.
  useEffect(() => {
    const candidate = notifications.find(n => n.unread && (n.kind === "hitl_ask" || n.kind === "hitl_suggest") && !toastedRef.current.has(n.id));
    if (candidate) { toastedRef.current.add(candidate.id); setToast(candidate); }
  }, [notifications]);

  const unreadCount = notifications.filter(n => n.unread).length;
  const doctorHasIssue = doctor ? !doctor.ok : false;

  const markNotifRead = (id) => setReadNotifIds(s => { const next = new Set(s); next.add(id); return next; });

  const goto = (id) => setRoute(id);

  const openRun = (threadId, state = "running", run = null) => {
    if (!threadId) { setRoute("run"); return; }
    setSelectedRunId(threadId);
    setSelectedRunTitle(run ? `Run · ${run.company}` : null);
    if (run) setLastRun(run);
    setTweak("runState", state);
    setRoute("run");
  };

  const openRunFromNotif = (n) => {
    setNotifsOpen(false);
    setToast(null);
    markNotifRead(n.id);
    if (n.runId) openRun(n.runId);
    else setRoute("run");
  };

  const renderRoute = () => {
    switch (route) {
      case "library":   return <LibraryView goto={goto} openRun={openRun} locked={isLocked}/>;
      case "companies": return <CompaniesView goto={goto} openRun={openRun}/>;
      case "dashboard": return <Dashboard goto={goto} openRun={openRun} locked={isLocked} doctor={doctor}/>;
      case "new":       return <NewRun goto={goto} openRun={openRun} locked={isLocked} onRunStarted={(id) => openRun(id, "running")}/>;
      case "resume":    return <ResumeEditor onReplace={() => setReplaceOpen(true)} parsing={parsing}/>;
      case "history":   return <HistoryView goto={goto} openRun={openRun}/>;
      case "settings":  return <SettingsView tweaks={tweaks} setTweak={setTweak}/>;
      case "setup":     return <SetupWizard goto={goto} startParse={startParse} parsing={parsing}/>;
      case "run":       return <LiveRunView key={selectedRunId} threadId={selectedRunId} density={tweaks.density} runState={tweaks.runState} setRunState={(v) => setTweak("runState", v)} settings={appSettings}/>;
      default:          return <LibraryView goto={goto} openRun={openRun} locked={isLocked}/>;
    }
  };

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      <Sidebar route={route} goto={goto} collapsed={sidebarCollapsed} setCollapsed={setSidebarCollapsed} locked={isLocked} settings={appSettings}/>

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, background: "var(--bg)" }}>
        <TopBar route={route} runTitle={selectedRunTitle} doctorBanner={doctorHasIssue || tweaks.doctorBanner}
          openCmdK={() => setCmdK(true)}
          openNotifs={() => setNotifsOpen(o => !o)}
          unreadCount={unreadCount}
          bellRef={bellRef}
          settings={appSettings}/>
        <ParsingBanner parsing={parsing} onOpen={() => setParsing(p => p ? { ...p, modalOpen: true } : null)}/>
        {(doctorHasIssue || tweaks.doctorBanner) && !doctorDismissed && <DoctorBanner doctor={doctor} goto={goto} onDismiss={() => setDoctorDismissed(true)}/>}
        <div style={{ flex: 1, overflow: "auto", minHeight: 0, position: "relative" }}>
          <div key={route} className="route-in" style={{ minHeight: "100%" }}>
            {renderRoute()}
          </div>
          <NotificationCenter
            open={notifsOpen}
            items={notifications}
            onClose={() => setNotifsOpen(false)}
            onOpenRun={openRunFromNotif}
            onMarkAllRead={() => setReadNotifIds(new Set(notifications.map(n => n.id)))}
          />
        </div>
      </div>

      <CommandPalette open={cmdK} onClose={() => setCmdK(false)} goto={goto} openRun={openRun} lastRun={lastRun}/>
      <HitlToast toast={toast} onClose={() => setToast(null)} onOpenRun={openRunFromNotif}/>
      <ReplaceBaseResumeModal open={replaceOpen} onClose={() => setReplaceOpen(false)} onUpload={startParse}/>
      <BaseResumeParseModal
        parsing={parsing && parsing.modalOpen ? parsing : null}
        onClose={endParse}
        onMinimize={() => setParsing(p => p ? { ...p, modalOpen: false } : null)}
        onCancel={endParse}
      />

      <TweaksPanel title="Tweaks">
        <TweaksContent t={tweaks} setTweak={setTweak}/>
      </TweaksPanel>
    </div>
  );
};

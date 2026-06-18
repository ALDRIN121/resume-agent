import { Icon } from "./icons.jsx";
import { Badge } from "./components.jsx";
import { PIPELINE_NODES } from "./data.jsx";
// A vertical rail; nodes light up as they complete; running node has a pulsing aura;
// HITL pauses show a dashed connector; durations in mono on completion.

export const formatDur = (ms) => {
  if (ms == null) return null;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 10000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 1000)}s`;
};

const NodeDot = ({ status, density }) => {
  // status: pending | running | done | retrying | failed | paused
  const dotSize = density === "compact" ? 8 : 10;
  const ringSize = density === "compact" ? 18 : 22;

  const colorMap = {
    pending:  { fill: "var(--surface)",   ring: "var(--border-strong)", icon: null },
    running:  { fill: "var(--info)",      ring: "var(--info)",          icon: null, pulse: true },
    done:     { fill: "var(--success)",   ring: "var(--success)",       icon: "check" },
    retrying: { fill: "var(--warning)",   ring: "var(--warning)",       icon: "refresh" },
    failed:   { fill: "var(--danger)",    ring: "var(--danger)",        icon: "x" },
    paused:   { fill: "var(--warning)",   ring: "var(--warning)",       icon: "pause" },
  };
  const c = colorMap[status];

  return (
    <span style={{
      position: "relative",
      width: ringSize, height: ringSize,
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      flexShrink: 0,
    }}>
      {/* Outer pulse ring (running) */}
      {c.pulse && (
        <span style={{
          position: "absolute", inset: 0, borderRadius: 99,
          border: `1px solid ${c.ring}`,
          animation: "pulse-ring 1.4s ease-out infinite",
        }} />
      )}
      <span style={{
        width: dotSize, height: dotSize, borderRadius: 99,
        background: status === "pending" ? "var(--surface)" : c.fill,
        border: status === "pending" ? `1.5px solid ${c.ring}` : `1.5px solid ${c.fill}`,
        boxShadow: status === "running" ? `0 0 0 3px ${c.ring}33` : "none",
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "white",
        transition: `background var(--t-mid), border-color var(--t-mid)`,
      }}>
        {c.icon && status === "done" && (
          <Icon name="check" size={dotSize - 3} stroke={3} style={{ color: "white" }}/>
        )}
      </span>
    </span>
  );
};

export const PipelineTimeline = ({ events, currentNodeIdx, density = "comfortable", onNodeClick, selectedIdx, isPaused, retryFor, retryCount = 2 }) => {
  // events: array of { status, durationMs } per PIPELINE_NODES
  const rowGap = density === "compact" ? 6 : 12;
  const rowPad = density === "compact" ? "5px 8px" : "8px 10px";
  const dotW = density === "compact" ? 18 : 22;

  return (
    <div style={{ position: "relative", padding: "4px 0" }}>
      {/* Vertical rail (background) */}
      <div style={{
        position: "absolute",
        left: dotW / 2 + 10,
        top: 14, bottom: 14,
        width: 1,
        background: "var(--border)",
      }} />
      {/* Filled rail — proportional to completed events */}
      <div style={{
        position: "absolute",
        left: dotW / 2 + 10,
        top: 14,
        width: 1.5,
        height: `calc(${Math.max(0, Math.min(events.length, currentNodeIdx)) / Math.max(1, events.length - 1) * 100}% - 16px)`,
        background: "var(--accent)",
        opacity: 0.7,
        transition: "height 400ms cubic-bezier(.4,.0,.2,1)",
      }} />

      {PIPELINE_NODES.map((node, i) => {
        const ev = events[i] || { status: "pending" };
        const isCurrent = i === currentNodeIdx;
        const isSelected = i === selectedIdx;
        const isPausedNode = isCurrent && isPaused;
        const dotStatus = isPausedNode ? "paused" : ev.status;

        return (
          <button
            key={node.id}
            onClick={() => onNodeClick?.(i)}
            style={{
              display: "grid",
              gridTemplateColumns: `${dotW + 20}px 1fr auto`,
              alignItems: "center",
              width: "100%", textAlign: "left",
              gap: 8, padding: rowPad,
              marginBottom: rowGap,
              background: isSelected ? "var(--accent-soft)" : "transparent",
              border: isSelected ? "1px solid var(--accent-ring)" : "1px solid transparent",
              borderRadius: "var(--radius-md)",
              cursor: "pointer",
              transition: `background var(--t-fast), border-color var(--t-fast)`,
              position: "relative",
            }}
            onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = "var(--surface-2)"; }}
            onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.background = "transparent"; }}
          >
            <span style={{ display: "flex", justifyContent: "flex-start", paddingLeft: 10, position: "relative", zIndex: 1, background: "transparent" }}>
              <NodeDot status={dotStatus} density={density} />
            </span>

            <span style={{ minWidth: 0 }}>
              <span style={{
                display: "block",
                fontSize: density === "compact" ? 12.5 : 13.5,
                fontWeight: isCurrent ? 600 : 500,
                color: ev.status === "pending" ? "var(--text-muted)" : "var(--text)",
                lineHeight: 1.3,
              }} className="truncate">{node.label}</span>
              {density === "comfortable" && ev.status === "running" && (
                <span className="mono" style={{ fontSize: 11, color: "var(--info)", display: "block", marginTop: 2 }}>
                  in progress…
                </span>
              )}
              {density === "comfortable" && isPausedNode && (
                <span className="mono" style={{ fontSize: 11, color: "var(--warning)", display: "block", marginTop: 2 }}>
                  waiting for you
                </span>
              )}
              {density === "comfortable" && ev.status === "failed" && retryFor === i && (
                <span className="mono" style={{ fontSize: 11, color: "var(--danger)", display: "block", marginTop: 2 }}>
                  5 of 5 attempts · budget exhausted
                </span>
              )}
            </span>

            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {(retryFor === i) && <Badge tone="warning" style={{ fontSize: 10 }}>×{retryCount}</Badge>}
              {ev.durationMs != null && ev.status === "done" && (
                <span className="mono" style={{ fontSize: 11, color: "var(--text-faint)", fontVariantNumeric: "tabular-nums" }}>
                  {formatDur(ev.durationMs)}
                </span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
};

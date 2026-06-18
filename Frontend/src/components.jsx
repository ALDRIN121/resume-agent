import React from "react";
import { Icon } from "./icons.jsx";

const Button = ({ children, variant = "primary", size = "md", icon, iconRight, className = "", ...rest }) => {
  const sizeStyles = {
    sm: { height: 28, padding: "0 10px", fontSize: 13, gap: 6 },
    md: { height: 34, padding: "0 14px", fontSize: 13.5, gap: 8 },
    lg: { height: 40, padding: "0 18px", fontSize: 14, gap: 8 },
  }[size];
  const variantStyles = {
    primary: { background: "var(--accent)", color: "var(--accent-contrast)", border: "1px solid var(--accent)" },
    secondary: { background: "var(--surface)", color: "var(--text)", border: "1px solid var(--border-strong)" },
    ghost: { background: "transparent", color: "var(--text)", border: "1px solid transparent" },
    danger: { background: "var(--danger)", color: "white", border: "1px solid var(--danger)" },
    "danger-outline": { background: "transparent", color: "var(--danger)", border: "1px solid var(--danger)" },
  }[variant];
  return (
    <button
      {...rest}
      className={`btn ${className}`}
      style={{
        ...sizeStyles, ...variantStyles,
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        borderRadius: "var(--radius-md)", fontWeight: 500, cursor: "pointer",
        transition: `background var(--t-fast), border-color var(--t-fast), opacity var(--t-fast), transform 220ms var(--ease-bounce)`,
        ...(rest.style || {})
      }}
      onMouseDown={(e) => { e.currentTarget.style.transform = "scale(0.95)"; rest.onMouseDown?.(e); }}
      onMouseUp={(e) => { e.currentTarget.style.transform = "scale(1)"; rest.onMouseUp?.(e); }}
      onMouseLeave={(e) => { e.currentTarget.style.transform = "scale(1)"; rest.onMouseLeave?.(e); }}
    >
      {icon && <Icon name={icon} size={size === "sm" ? 13 : 15} />}
      {children}
      {iconRight && <Icon name={iconRight} size={size === "sm" ? 13 : 15} />}
    </button>
  );
};

const IconButton = ({ name, label, size = 14, padding = 6, onClick, active = false, style = {} }) => (
  <button
    aria-label={label} title={label} onClick={onClick}
    style={{
      width: size + padding * 2, height: size + padding * 2,
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      background: active ? "var(--accent-soft)" : "transparent",
      color: active ? "var(--accent)" : "var(--text-muted)",
      border: "1px solid " + (active ? "var(--accent-ring)" : "transparent"),
      borderRadius: "var(--radius-md)", cursor: "pointer",
      transition: `background var(--t-fast), color var(--t-fast)`,
      ...style,
    }}
    onMouseEnter={(e) => { if (!active) { e.currentTarget.style.background = "var(--surface-2)"; e.currentTarget.style.color = "var(--text)"; } }}
    onMouseLeave={(e) => { if (!active) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-muted)"; } }}
  >
    <Icon name={name} size={size} />
  </button>
);

// Status pill — color + icon + word (a11y: never color-only)
const STATUS_META = {
  running:        { color: "var(--info)",     bg: "var(--info-soft)",     icon: "loader",      label: "Running" },
  "awaiting-input":{ color: "var(--warning)",  bg: "var(--warning-soft)",  icon: "alert",       label: "Awaiting input" },
  complete:       { color: "var(--success)",  bg: "var(--success-soft)",  icon: "check-circle",label: "Complete" },
  failed:         { color: "var(--danger)",   bg: "var(--danger-soft)",   icon: "x-circle",    label: "Failed" },
  queued:         { color: "var(--text-muted)", bg: "var(--surface-2)",   icon: "circle",      label: "Queued" },
  retrying:       { color: "var(--warning)",  bg: "var(--warning-soft)",  icon: "refresh",     label: "Retrying" },
};

const StatusPill = ({ status, size = "md", label }) => {
  const meta = STATUS_META[status] || STATUS_META.queued;
  const small = size === "sm";
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: small ? 5 : 6,
      padding: small ? "2px 8px" : "3px 10px",
      borderRadius: 99,
      background: meta.bg,
      color: meta.color,
      fontSize: small ? 11 : 12,
      fontWeight: 500,
      lineHeight: 1.4,
      border: `1px solid ${meta.color}1f`,
    }}>
      <Icon name={meta.icon} size={small ? 10 : 12} stroke={2.4}
        style={meta.icon === "loader" ? { animation: "spin 1.2s linear infinite" } : {}} />
      <span>{label || meta.label}</span>
    </span>
  );
};

const Card = ({ children, className = "", padding = 20, style = {}, hover = false, onClick, id }) => (
  <div
    id={id}
    onClick={onClick}
    className={className}
    style={{
      background: "var(--surface)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-lg)",
      padding,
      transition: `border-color var(--t-fast), background var(--t-fast), transform 260ms var(--ease-spring), box-shadow 260ms var(--ease-spring)`,
      cursor: onClick || hover ? "pointer" : "default",
      ...style
    }}
    onMouseEnter={(e) => { if (hover || onClick) { e.currentTarget.style.borderColor = "var(--border-strong)"; e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "var(--shadow-md)"; } }}
    onMouseLeave={(e) => { if (hover || onClick) { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "none"; } }}
  >
    {children}
  </div>
);

const Input = React.forwardRef(({ icon, suffix, style = {}, ...rest }, ref) => (
  <div style={{
    position: "relative", display: "flex", alignItems: "center",
    background: "var(--surface)",
    border: "1px solid var(--border-strong)",
    borderRadius: "var(--radius-md)",
    transition: `border-color var(--t-fast), box-shadow var(--t-fast)`,
    ...style
  }}>
    {icon && <span style={{ display: "flex", paddingLeft: 10, color: "var(--text-muted)" }}><Icon name={icon} size={14} /></span>}
    <input
      ref={ref}
      {...rest}
      style={{
        flex: 1, height: 34, padding: icon ? "0 10px 0 8px" : "0 12px",
        background: "transparent", border: "none", outline: "none",
        color: "var(--text)", fontSize: 13.5, minWidth: 0,
      }}
      onFocus={(e) => { e.currentTarget.parentElement.style.borderColor = "var(--accent)"; e.currentTarget.parentElement.style.boxShadow = "0 0 0 3px var(--accent-ring)"; rest.onFocus?.(e); }}
      onBlur={(e) => { e.currentTarget.parentElement.style.borderColor = "var(--border-strong)"; e.currentTarget.parentElement.style.boxShadow = "none"; rest.onBlur?.(e); }}
    />
    {suffix && <span style={{ display: "flex", paddingRight: 10, color: "var(--text-muted)" }}>{suffix}</span>}
  </div>
));

const Textarea = ({ style = {}, ...rest }) => (
  <textarea
    {...rest}
    style={{
      width: "100%", minHeight: 80, padding: "10px 12px",
      background: "var(--surface)",
      border: "1px solid var(--border-strong)",
      borderRadius: "var(--radius-md)",
      color: "var(--text)", fontSize: 13.5, lineHeight: 1.55,
      outline: "none", resize: "vertical",
      fontFamily: "var(--font-sans)",
      transition: `border-color var(--t-fast), box-shadow var(--t-fast)`,
      ...style
    }}
    onFocus={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.boxShadow = "0 0 0 3px var(--accent-ring)"; rest.onFocus?.(e); }}
    onBlur={(e) => { e.currentTarget.style.borderColor = "var(--border-strong)"; e.currentTarget.style.boxShadow = "none"; rest.onBlur?.(e); }}
  />
);

const Kbd = ({ children, style = {} }) => (
  <span className="mono" style={{
    display: "inline-flex", alignItems: "center", justifyContent: "center",
    minWidth: 18, height: 18, padding: "0 5px",
    border: "1px solid var(--border-strong)",
    borderRadius: 4,
    fontSize: 11, color: "var(--text-muted)",
    background: "var(--surface)",
    ...style
  }}>{children}</span>
);

const Tabs = ({ value, onChange, options, style = {} }) => (
  <div style={{
    display: "inline-flex", padding: 3, gap: 2,
    background: "var(--surface-2)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-md)", ...style
  }}>
    {options.map(opt => (
      <button key={opt.value} onClick={() => onChange(opt.value)}
        style={{
          height: 26, padding: "0 11px",
          background: value === opt.value ? "var(--surface)" : "transparent",
          color: value === opt.value ? "var(--text)" : "var(--text-muted)",
          border: value === opt.value ? "1px solid var(--border)" : "1px solid transparent",
          borderRadius: 5, fontSize: 12.5, fontWeight: 500,
          cursor: "pointer", whiteSpace: "nowrap",
          boxShadow: value === opt.value ? "var(--shadow-sm)" : "none",
          transition: `all var(--t-fast)`,
        }}
      >{opt.label}</button>
    ))}
  </div>
);

const Badge = ({ children, tone = "neutral", style = {} }) => {
  const tones = {
    neutral: { bg: "var(--surface-2)", color: "var(--text-muted)" },
    success: { bg: "var(--success-soft)", color: "var(--success)" },
    warning: { bg: "var(--warning-soft)", color: "var(--warning)" },
    danger:  { bg: "var(--danger-soft)", color: "var(--danger)" },
    info:    { bg: "var(--info-soft)", color: "var(--info)" },
    accent:  { bg: "var(--accent-soft)", color: "var(--accent)" },
  }[tone];
  return (
    <span className="mono" style={{
      display: "inline-flex", alignItems: "center",
      padding: "1px 7px", borderRadius: 4,
      fontSize: 11, fontWeight: 500,
      background: tones.bg, color: tones.color,
      ...style
    }}>{children}</span>
  );
};

// Toggle
const Toggle = ({ checked, onChange, label, sub }) => (
  <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, padding: "10px 0", cursor: "pointer" }}>
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: 13.5, color: "var(--text)" }}>{label}</div>
      {sub && <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>{sub}</div>}
    </div>
    <button
      role="switch" aria-checked={checked}
      onClick={() => onChange(!checked)}
      style={{
        width: 32, height: 18, position: "relative", flexShrink: 0,
        border: "1px solid " + (checked ? "var(--accent)" : "var(--border-strong)"),
        background: checked ? "var(--accent)" : "var(--surface)",
        borderRadius: 99, cursor: "pointer",
        transition: `background var(--t-fast), border-color var(--t-fast)`,
      }}
    >
      <span style={{
        position: "absolute", top: 1, left: checked ? 14 : 1,
        width: 14, height: 14, background: checked ? "var(--accent-contrast)" : "var(--text-muted)",
        borderRadius: 99,
        transition: `left var(--t-fast), background var(--t-fast)`,
      }} />
    </button>
  </label>
);

// Section header (used in setup, settings, etc.)
const SectionHeader = ({ eyebrow, title, sub }) => (
  <div style={{ marginBottom: 16 }}>
    {eyebrow && <div className="mono" style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>{eyebrow}</div>}
    <div style={{ fontSize: 20, fontWeight: 600, letterSpacing: -0.2 }}>{title}</div>
    {sub && <div style={{ fontSize: 13.5, color: "var(--text-muted)", marginTop: 4 }}>{sub}</div>}
  </div>
);

// Empty state
const EmptyState = ({ icon = "sparkles", title, sub, action }) => (
  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, padding: "40px 20px", textAlign: "center", color: "var(--text-muted)" }}>
    <div style={{
      width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center",
      border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", background: "var(--surface-2)", color: "var(--text-muted)"
    }}>
      <Icon name={icon} size={18} />
    </div>
    <div>
      <div style={{ color: "var(--text)", fontSize: 14, fontWeight: 500 }}>{title}</div>
      {sub && <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 4, maxWidth: 360 }}>{sub}</div>}
    </div>
    {action}
  </div>
);

const Logo = ({ size = 22 }) => (
  <div style={{
    width: size, height: size, flexShrink: 0,
    background: "var(--accent)", color: "var(--accent-contrast)",
    borderRadius: 6,
    display: "flex", alignItems: "center", justifyContent: "center",
    fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: size * 0.55,
  }}>
    <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 16 16" fill="none">
      <path d="M3 3h7l3 3v7H3z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"/>
      <path d="M10 3v3h3" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"/>
      <line x1="5.5" y1="9" x2="10.5" y2="9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
      <line x1="5.5" y1="11" x2="9" y2="11" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    </svg>
  </div>
);

// File dropzone — real <input type=file> + drag-and-drop. Calls onUpload(File).
const UploadDropzone = ({ onUpload, accept = ".pdf,.tex", padding = "32px 20px", hint = "parsed into a structured base_resume.yaml" }) => {
  const inputRef = React.useRef(null);
  const [over, setOver] = React.useState(false);
  const pick = (file) => { if (file) onUpload(file); };
  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files?.[0]); }}
      style={{
        width: "100%", padding, textAlign: "center",
        background: over ? "var(--accent-soft)" : "var(--surface-2)",
        border: "1.5px dashed " + (over ? "var(--accent)" : "var(--border-strong)"),
        borderRadius: "var(--radius-lg)", cursor: "pointer",
        color: "var(--text-muted)", transition: "all var(--t-fast)",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.background = "var(--accent-soft)"; }}
      onMouseLeave={(e) => { if (!over) { e.currentTarget.style.borderColor = "var(--border-strong)"; e.currentTarget.style.background = "var(--surface-2)"; } }}
    >
      <input ref={inputRef} type="file" accept={accept} style={{ display: "none" }}
        onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }}/>
      <Icon name="upload" size={22} stroke={1.6}/>
      <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text)", marginTop: 8 }}>Drop a .tex or .pdf, or click to browse</div>
      <div style={{ fontSize: 12, marginTop: 4 }}>{hint}</div>
    </div>
  );
};

// Mono ticker — for elapsed timers etc
const MonoTicker = ({ children, style = {} }) => (
  <span className="mono" style={{
    fontVariantNumeric: "tabular-nums", fontSize: 12.5,
    color: "var(--text)", letterSpacing: 0.2, ...style
  }}>{children}</span>
);

export { Button, IconButton, StatusPill, Card, Input, Textarea, Kbd, Tabs, Badge, Toggle, SectionHeader, EmptyState, Logo, MonoTicker, UploadDropzone, STATUS_META };

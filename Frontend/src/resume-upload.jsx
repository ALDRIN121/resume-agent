import React from "react";
import { Icon } from "./icons.jsx";
import { Button, IconButton, UploadDropzone } from "./components.jsx";
import { actionForRetry } from "./draft-store.js";
import { decideImport, importSourceUrl } from "./api/client.js";
import { PARSE_STAGES } from "./data.jsx";
import { FieldValue } from "./profile-facts.jsx";

const doneCount = (parsing) => parsing.completed ? PARSE_STAGES.length
  : PARSE_STAGES.filter(stage => parsing.statuses?.[stage.id] === "done").length;
const currentStage = (parsing) => PARSE_STAGES.find(stage =>
  ["running", "failed"].includes(parsing.statuses?.[stage.id]))
  || PARSE_STAGES.find(stage => parsing.statuses?.[stage.id] !== "done")
  || PARSE_STAGES[PARSE_STAGES.length - 1];
const formatElapsed = (ms) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;

function useElapsed(parsing) {
  const [elapsed, setElapsed] = React.useState(0);
  const startedAt = parsing?.startedAt;
  const finished = parsing?.completed || parsing?.failed;
  React.useEffect(() => {
    if (startedAt == null) return;
    setElapsed(Date.now() - startedAt);
    if (finished) return;
    const timer = setInterval(() => setElapsed(Date.now() - startedAt), 1000);
    return () => clearInterval(timer);
  }, [startedAt, finished]);
  return formatElapsed(elapsed);
}

function ResumeDialog({ title, subtitle, icon, tone = "", onDismiss, children }) {
  const titleId = React.useId();
  const subtitleId = React.useId();
  const panelRef = React.useRef(null);
  const dismissRef = React.useRef(onDismiss);
  dismissRef.current = onDismiss;
  React.useEffect(() => {
    const previous = document.activeElement;
    const panel = panelRef.current;
    panel.querySelector("h2")?.focus();
    const onKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        dismissRef.current?.();
      }
      if (event.key !== "Tab") return;
      const controls = [...panel.querySelectorAll('button:not(:disabled), [tabindex="0"], input:not(:disabled)')]
        .filter(element => element.getClientRects().length > 0);
      if (!controls.length) { event.preventDefault(); return; }
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || !controls.includes(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !controls.includes(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    };
    panel.addEventListener("keydown", onKey);
    return () => {
      panel.removeEventListener("keydown", onKey);
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return <div className="resume-dialog-backdrop">
    <section ref={panelRef} className={`resume-dialog ${tone}`} role="dialog" aria-modal="true"
      aria-labelledby={titleId} aria-describedby={subtitleId}>
      <header className="resume-dialog-header">
        <span className="resume-dialog-icon"><Icon name={icon} size={20}/></span>
        <div className="resume-dialog-heading">
          <h2 id={titleId} tabIndex={-1}>{title}</h2>
          <p id={subtitleId}>{subtitle}</p>
        </div>
        <IconButton name="x" label={tone ? "Close" : "Minimize"} onClick={onDismiss}/>
      </header>
      {children}
    </section>
  </div>;
}

export function ResumeImportProgress({ parsing }) {
  const elapsed = useElapsed(parsing);
  if (!parsing) return null;
  const { completed, failed } = parsing;
  const active = currentStage(parsing);
  const done = doneCount(parsing);
  return <div className={`resume-dialog-body resume-import-progress ${completed ? "is-success" : failed ? "is-error" : ""}`}>
      <div className="resume-import-file">
        <Icon name="file-text" size={20}/>
        <div><strong>{parsing.file}</strong><span>{completed ? "Imported successfully" : failed ? "Import needs attention" : "Base resume document"}</span></div>
        <span className="resume-elapsed" aria-label={`${elapsed} elapsed`}>{elapsed}</span>
      </div>
      <div className="resume-progress-caption" aria-live="polite">
        <span>{completed ? "All steps complete" : failed ? `Stopped at: ${active.label}` : active.label}</span>
        <span>{done} of {PARSE_STAGES.length} done</span>
      </div>
      <div className="resume-progress-track" role="progressbar" aria-label="Resume import"
        aria-valuemin={0} aria-valuemax={PARSE_STAGES.length} aria-valuenow={done}
        aria-valuetext={`${done} of ${PARSE_STAGES.length} steps complete`}>
        <span style={{ width: `${done / PARSE_STAGES.length * 100}%` }}/>
      </div>
      <ol className="resume-steps" aria-label="Resume import progress">
        {PARSE_STAGES.map((stage, index) => {
          const done = completed || parsing.statuses?.[stage.id] === "done";
          const current = !completed && active.id === stage.id;
          const problem = current && failed;
          return <li key={stage.id} aria-current={current ? "step" : undefined}
            className={`resume-step ${done ? "is-complete" : current ? "is-current" : ""} ${problem ? "is-failed" : ""}`}>
            <span className="resume-step-number">{done ? <Icon name="check" size={14}/> : problem ? <Icon name="x" size={14}/> : index + 1}</span>
            <div className="resume-step-content">
              <strong>{stage.label}</strong>
              <span className="resume-step-status">{done ? "Complete" : problem ? "Needs attention" : current ? "In progress" : "Up next"}</span>
              {current && !failed && <p className="resume-step-detail">{stage.sub}</p>}
            </div>
            {current && !failed && <Icon className="resume-step-spinner" name="loader" size={15}/>}
          </li>;
        })}
      </ol>
      {failed && <div className="resume-import-error" role="alert">
        <Icon name="alert" size={17}/>
        <div><strong>We couldn’t finish importing this file.</strong><p>{parsing.error || "Check the file and try again."}</p></div>
      </div>}
    </div>;
}

export function BaseResumeParseModal({ parsing, onClose, onMinimize, onRetry, onDecision }) {
  if (!parsing) return null;
  const { completed, failed } = parsing;
  if (parsing.operation?.pending?.kind === "import_review") return <ImportReviewModal key={parsing.operation.pending.review_id} operation={parsing.operation} onMinimize={onMinimize} onDecision={onDecision}/>;
  if (parsing.operation?.status === "cancelled") return <ResumeDialog title="Import rejected" subtitle="Your previous base resume is unchanged." icon="file-text" tone="is-success" onDismiss={onClose}><div className="resume-dialog-body"><p>The source and review remain in your import history.</p><Button onClick={onClose}>Close</Button></div></ResumeDialog>;
  const title = failed ? "Resume parsing failed" : completed ? "Base resume parsed" : "Parsing your base resume";
  return <ResumeDialog title={title}
    subtitle={completed ? "Your new base resume is ready to review." : failed ? "Review the issue below, then try again." : "We’ll turn your document into an editable base resume."}
    icon={completed ? "check-circle" : failed ? "alert" : "file-text"}
    tone={completed ? "is-success" : failed ? "is-error" : ""}
    onDismiss={completed || failed ? onClose : onMinimize}>
    <ResumeImportProgress parsing={parsing}/>
    <footer className="resume-dialog-footer">
      <p>{completed ? "You can edit your resume before creating a tailored version."
        : failed ? "You can choose another PDF or LaTeX file."
        : "You can minimize this window. New runs will be available when parsing finishes."}</p>
      <div className="resume-dialog-actions">
        {failed ? <><Button variant="secondary" onClick={onClose}>Close</Button><Button variant="primary" icon="upload" onClick={onRetry}>Choose another file</Button></>
          : completed ? <Button variant="primary" icon="check" onClick={onClose}>Done</Button>
          : <Button variant="secondary" icon="chevron-down" onClick={onMinimize}>Minimize</Button>}
      </div>
    </footer>
  </ResumeDialog>;
}

export function ParsingBanner({ parsing, onOpen }) {
  const elapsed = useElapsed(parsing);
  if (!parsing || parsing.completed || parsing.failed || parsing.modalOpen) return null;
  const stage = currentStage(parsing);
  return <button className="resume-parsing-banner" onClick={onOpen}>
    <Icon className="resume-step-spinner" name="loader" size={16}/>
    <span className="resume-banner-copy"><strong>Parsing your base resume</strong><span>{stage.label}</span></span>
    <span className="resume-banner-time">{elapsed}</span>
    <span className="resume-banner-action">View progress <Icon name="arrow-right" size={14}/></span>
  </button>;
}

export function ReplaceBaseResumeModal({ open, onClose, onUpload }) {
  if (!open) return null;
  return <ResumeDialog title="Replace base resume" subtitle="Upload the resume you want to use for future applications."
    icon="upload" tone="is-upload" onDismiss={onClose}>
    <div className="resume-dialog-body resume-upload-body">
      <UploadDropzone onUpload={onUpload} label="Choose a resume file" hint="Drop a PDF or LaTeX file here, or click to browse." padding="32px 20px"/>
      <div className="resume-import-note"><Icon name="file-text" size={16}/><p>Your current base resume is replaced only after you review and accept the parsed draft.</p></div>
    </div>
    <footer className="resume-dialog-footer">
      <p>AI parsing can take a minute or two. You can review and edit the result.</p>
      <div className="resume-dialog-actions"><Button variant="secondary" onClick={onClose}>Cancel</Button></div>
    </footer>
  </ResumeDialog>;
}

function ImportReviewModal({operation,onMinimize,onDecision}) {
  const pending = operation.pending;
  const [blank,setBlank] = React.useState([]);
  const [busy,setBusy] = React.useState(false);
  const [error,setError] = React.useState(null);
  const [conflict,setConflict] = React.useState(false);
  const action = React.useRef(actionForRetry());
  const source = operation.source || pending.payload?.source;
  const draft = operation.draft || pending.payload?.draft;
  const unreadable = pending.unreadable_pages || [];
  const decide = async decision => {
    setBusy(true);setError(null);
    const body = decision === "accept" ? {kind:"accept_import",review_id:pending.review_id,draft_hash:pending.draft_hash,expected_profile_revision:pending.expected_profile_revision,intentionally_blank_pages:blank} : {kind:"reject_import",review_id:pending.review_id};
    try { onDecision(await decideImport(operation.id,decision,action.current(body))); }
    catch(e) { setError(e.status === 409 ? "The profile or import changed. Refresh the import and review it against the current profile before accepting." : e.message); if(e.status === 409) setConflict(true); }
    finally {setBusy(false);}
  };
  return <ResumeDialog title="Review imported resume" subtitle="Compare the original document with the parsed draft before replacing your base resume." icon="file-text" onDismiss={onMinimize}>
    <div className="resume-dialog-body review-flow">
      {error && <p role="alert">{error}</p>}
      <a href={importSourceUrl(operation.id)} target="_blank" rel="noreferrer">Open original source</a>
      <h3>Original source: {source?.filename}</h3><pre>{source?.text}</pre>
      <h3>Parsed profile draft</h3><FieldValue value={draft}/>
      <p>{operation.coverage_note || "Parsing can omit information. Compare every section and every source page before accepting."}</p>
      {unreadable.map(page => <label className="review-question" key={page}><span><input type="checkbox" checked={blank.includes(page)} disabled={busy || conflict} onChange={e => setBlank(e.target.checked ? [...blank,page] : blank.filter(n => n !== page))}/> I checked page {page}; it is intentionally blank.</span></label>)}
      {source?.pages?.map(page => <details key={page.page_number}><summary>Page {page.page_number} · {page.readable ? "Readable" : "Unreadable"}</summary><p>{page.warning}</p><pre>{page.text}</pre></details>)}
    </div>
    <footer className="resume-dialog-footer"><p>Accepting replaces the current profile. Rejection keeps it unchanged.</p><div className="resume-dialog-actions">
      <Button disabled={busy} onClick={() => decide("reject")}>Reject import</Button>
      <Button variant="primary" disabled={busy || conflict || unreadable.some(page => !blank.includes(page))} onClick={() => decide("accept")}>Accept reviewed import</Button>
    </div></footer>
  </ResumeDialog>;
}

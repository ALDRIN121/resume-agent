import React from "react";
import { Icon } from "./icons.jsx";
import { PIPELINE_NODES } from "./data.jsx";

export const formatDur = (ms) => {
  if (ms == null) return null;
  if (ms < 1000) return `${ms}ms`;
  return ms < 10000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms / 1000)}s`;
};

const PHASES = [
  { title: "Read the job & resume", steps: [0, 1, 2, 3] },
  { title: "Compare experience", steps: [4] },
  { title: "Review together", steps: [5, 6] },
  { title: "Create the PDF", steps: [7, 8, 9, 10] },
  { title: "Check & save", steps: [11, 12, 13, 14] },
];

export const PipelineTimeline = ({ events, currentNodeIdx, isPaused, completed, failed, onNodeClick, selectedIdx }) => {
  const activePhase = completed ? -1 : PHASES.findIndex(phase => phase.steps.includes(currentNodeIdx));
  const [expanded, setExpanded] = React.useState(activePhase);
  React.useEffect(() => setExpanded(activePhase), [activePhase]);
  const recorded = events.some(event => event.status !== "pending" && event.status !== "unrecorded");

  if (completed && !recorded) {
    return <div className="pipeline-saved-summary">
      <Icon name="check-circle" size={28}/>
      <strong>Resume generated and saved</strong>
      <p>This saved run has no detailed step history. Its PDF is ready to download.</p>
    </div>;
  }

  return <ol className="pipeline-phases" aria-label="Generation phases">
    {PHASES.map((phase, index) => {
      const active = index === activePhase;
      const done = completed || (activePhase >= 0 && index < activePhase);
      const problem = active && failed;
      const status = done ? "Complete" : problem ? "Failed" : active ? isPaused ? "Your input needed" : "In progress" : "Up next";
      const open = expanded === index;
      const currentStep = phase.steps.find(step => events[step]?.status === "running");
      return <li key={phase.title} className={`pipeline-phase ${done ? "is-complete" : active ? "is-current" : "is-pending"}`}>
        <button className="phase-header" aria-expanded={open} aria-controls={`phase-${index}`} onClick={() => setExpanded(open ? null : index)}>
          <span className={`phase-number ${problem ? "is-failed" : ""}`}>
            {done ? <Icon name="check" size={14}/> : problem ? <Icon name="x" size={14}/> : index + 1}
          </span>
          <span className="phase-description">
            <strong>{phase.title}</strong>
            <span>{status}{active && currentStep != null && !isPaused ? ` · ${PIPELINE_NODES[currentStep].label}` : ""}</span>
          </span>
          <Icon name={open ? "chevron-up" : "chevron-down"} size={14}/>
        </button>
        {open && <div id={`phase-${index}`} className="phase-steps">
          {phase.steps.map(step => {
            const event = events[step] || { status: "pending" };
            const skipped = event.status === "unrecorded" || (event.status === "pending" && step < currentNodeIdx);
            const running = event.status === "running";
            const label = skipped ? "Not recorded" : event.status === "done" ? "Done" : running ? isPaused ? "Waiting for you" : "Running" : "Pending";
            return <button key={step} className={`phase-step ${running ? "is-running" : ""}`} aria-current={running ? "step" : undefined}
              aria-pressed={selectedIdx === step} onClick={() => onNodeClick?.(step)}>
              <Icon name={event.status === "done" ? "check" : running ? "loader" : "circle"} size={12}
                style={running && !isPaused ? { animation: "spin 1.2s linear infinite" } : {}}/>
              <span>{PIPELINE_NODES[step].label}</span>
              <span className="phase-step-meta">{event.durationMs != null && event.status === "done" ? formatDur(event.durationMs) : label}</span>
            </button>;
          })}
        </div>}
      </li>;
    })}
  </ol>;
};

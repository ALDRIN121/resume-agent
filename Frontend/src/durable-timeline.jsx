import React from 'react';
import { Icon } from './icons.jsx';

const PHASES = ['Read source and job', 'Collect evidence', 'Review content', 'Review PDF', 'Export approved PDF'];
const STAGES = {fetch_jd:0,extract_jd:0,questions:1,ask_missing:1,proposals:2,present_suggestions:2,
  render:3,pdf_check:3,hr_advisory:3,review_pdf:3,release:4,complete:4};

export function DurableTimeline({ run }) {
  const current = STAGES[run.pending?.kind || run.stage] ?? 0;
  return <ol className="pipeline-phases" aria-label="Reviewed generation progress">{PHASES.map((label,index) => {
    const done = run.status === 'complete' || index < current;
    const active = !done && index === current;
    const status = done ? 'Done' : !active ? 'Pending' : run.status === 'cancelled' ? 'Cancelled'
      : run.status === 'failed' ? 'Needs attention' : run.status === 'interrupted' ? 'Interrupted'
      : run.pending ? 'Waiting for you' : 'In progress';
    return <li key={label} className={`pipeline-phase ${active ? 'is-active' : ''}`}>
      <div className="phase-header" aria-current={active ? 'step' : undefined}>
        <span className="phase-number">{done ? <Icon name="check" size={14}/> : index+1}</span>
        <span className="phase-description"><strong>{label}</strong><span>{status}</span></span>
      </div>
    </li>;
  })}</ol>;
}

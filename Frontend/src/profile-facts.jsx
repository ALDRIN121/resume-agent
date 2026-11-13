import React from 'react';

const LABELS = { personal:'Contact information', full_name:'Full name', work_preferences:'Work preferences',
  preferred_locations:'Preferred locations', work_modes:'Work modes', tech:'Technologies',
  start:'Start date', end:'End date', graduation:'Graduation', linkedin:'LinkedIn', github:'GitHub',
  source_path:'Field', provenance:'Source notes', answers:'Saved answers', selected:'Selected changes' };
export const factLabel = key => LABELS[key] || String(key).replaceAll('_',' ').replace(/^./, c => c.toUpperCase());

export function FieldValue({ value }) {
  if (value == null || value === '') return <span className="fact-empty">Not provided</span>;
  if (Array.isArray(value)) return value.length ? <ul>{value.map((item,index) => <li key={index}><FieldValue value={item}/></li>)}</ul> : <span className="fact-empty">No entries</span>;
  if (typeof value === 'object') return <dl className="profile-facts">{Object.entries(value).map(([key,item]) => <div key={key}><dt>{factLabel(key)}</dt><dd><FieldValue value={item}/></dd></div>)}</dl>;
  return <span style={{whiteSpace:'pre-wrap'}}>{String(value)}</span>;
}

export function targetLabel(path, profile) {
  const parts = String(path || '').split('/').slice(1).map(p => p.replaceAll('~1','/').replaceAll('~0','~'));
  if (['experience','projects','education','certifications'].includes(parts[0]) && /^\d+$/.test(parts[1] || '')) {
    const item = profile?.[parts[0]]?.[Number(parts[1])];
    return [factLabel(parts[0]), item?.company || item?.name || item?.institution || `Entry ${Number(parts[1])+1}`,
      ...parts.slice(2).map(p => /^\d+$/.test(p) ? `Item ${Number(p)+1}` : factLabel(p))].join(' · ');
  }
  return parts.map(p => /^\d+$/.test(p) ? `Item ${Number(p)+1}` : factLabel(p)).join(' · ') || 'Profile';
}

export function AdvisoryList({ records=[] }) {
  const names = {hr:'Writing review',vision:'Visual review',lint:'Content checks'};
  const states = {pass:'Passed',warning:'Advice to review',disabled:'Not enabled',unavailable:'Unavailable'};
  return records.length ? <ul>{records.map((record,index) => <li key={index}>
    <strong>{names[record.source] || factLabel(record.source || 'Review')}:</strong> {states[record.status] || record.status}
    {record.diagnostics?.length > 0 && <ul>{record.diagnostics.map((text,i) => <li key={i}>{text}</li>)}</ul>}
  </li>)}</ul> : <p>No additional advice.</p>;
}

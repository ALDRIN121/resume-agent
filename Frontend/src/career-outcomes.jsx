import React from 'react';
import { Button } from './components.jsx';
import { getOutcomes,outcomesExportUrl } from './api/client.js';
import { FieldValue } from './profile-facts.jsx';

export function CareerOutcomes() {
  const [report,setReport]=React.useState(null),[error,setError]=React.useState(null);
  const refresh=async()=>{setError(null);try{const data=await getOutcomes();if(!Array.isArray(data.bands))throw new Error('Outcome report is unavailable.');setReport(data);}catch(e){setError(e.message);setReport(null);}};
  React.useEffect(()=>{refresh();},[]);
  return <main className="page-pad review-flow" style={{padding:32,maxWidth:1150}}><h1>Outcome evidence</h1>
    <p>Local descriptive counts from explicit application events and the score saved at submission. Later profile or evaluation changes do not rescore history.</p>
    <Button variant="ghost" onClick={refresh}>Refresh outcome evidence</Button>{' '}<a href={outcomesExportUrl()} download>Export local report</a>
    {error&&<p role="alert">{error}</p>}{!report&&!error&&<p>Loading outcome evidence…</p>}
    {report&&<>
      <p>{report.description}</p>
      <dl>{[['Submitted','submitted'],['Positive evidence','positive'],['Negative outcome','negative'],['Pending','pending'],['Withdrawn without outcome','withdrawn'],['Closed without classified outcome','closed_unclassified']].map(([label,key])=><div key={key}><dt>{label}</dt><dd>{report.counts[key]}</dd></div>)}</dl>
      {report.counts.submitted===0&&<p>No explicit submissions recorded. Completed PDFs do not create submissions.</p>}
      <p>Positive evidence means a favorable reply or explicitly recorded screening, interview or offer. Acknowledgments and generic replies do not count as positive.</p>
      <h2>Frozen submission-score bands</h2><p>Rates appear only with at least ten resolved applications in a band. Resolved means positive or negative; pending and withdrawn applications stay outside that denominator.</p>
      <div style={{overflowX:'auto'}}><table className="ledger-table" style={{width:'100%',textAlign:'left',borderCollapse:'collapse'}}><thead><tr>{['Band','Positive','Negative','Pending','Withdrawn','Closed, unclassified','Resolved','Positive rate'].map(label=><th key={label} style={{padding:10}}>{label}</th>)}</tr></thead><tbody>{report.bands.map(band=><tr key={band.band}>
        {[band.band,band.positive,band.negative,band.pending,band.withdrawn,band.closed_unclassified,band.resolved,
          band.positive_rate==null?'Below 10 resolved':`${band.positive_rate}%`].map((value,index)=><td key={index} style={{padding:10,borderTop:'1px solid var(--border)'}}>{value}</td>)}
      </tr>)}</tbody></table></div>
      <h2>Excluded records</h2><p>Unknown submission score: {report.counts.unknown_score}</p>
      <p>Unsupported rubric: {report.counts.unsupported_rubric}</p><p>No explicit submission: {report.counts.without_submission}</p>
      <p>Unique records outside band rate denominators: {report.unique_excluded}</p>
      <p>Outcome totals include submitted applications without a usable score. Band rates use only resolved applications with fit-v1 scores. Exact cutoffs are 40 and 70, before display rounding.</p>
      <details><summary>All exclusions and report metadata</summary><FieldValue value={report.exclusions}/><FieldValue value={{generated_at:report.generated_at,rubric_version:report.rubric_version,rate_rounding:report.rate_rounding}}/></details>
    </>}
  </main>;
}

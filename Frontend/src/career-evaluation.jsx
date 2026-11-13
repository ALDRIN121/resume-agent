import React from 'react';
import { Button } from './components.jsx';
import { FieldValue, factLabel, targetLabel } from './profile-facts.jsx';

export function CareerEvaluation({ evaluation,onGenerate,onRefresh,busy,generationReady=true }) {
  const [override,setOverride]=React.useState(false);
  React.useEffect(()=>setOverride(false),[evaluation.id,evaluation.stale,JSON.stringify(evaluation.stale_reasons)]);
  const result=evaluation.result;
  if(!result) return <section><h2>Saved evaluation</h2><p>{evaluation.status}</p>{evaluation.diagnostics?.map((d,i)=><p role="alert" key={i}>{d.code}</p>)}<Button disabled={busy} onClick={onRefresh}>Refresh evaluation</Button></section>;
  const fit=result.fit;
  const needsOverride=evaluation.stale||fit.recommendation!=='prioritize';
  return <section className="review-notice" aria-label="Role evaluation">
    <h2>Advisory evidence fit</h2><p>Product-default rubric {result.rubric_version}. This measures supplied evidence; hiring outcomes depend on many other factors.</p>
    {evaluation.stale&&<p role="status">Inputs changed: {evaluation.stale_reasons.join(', ')}</p>}
    <dl><div><dt>Evidence interval</dt><dd>{fit.lower==null?'Insufficient evidence to score':`${fit.lower}–${fit.upper}`}</dd></div>
      <div><dt>Evidence coverage</dt><dd>{fit.coverage==null?'Not available':`${fit.coverage}%`}</dd></div>
      <div><dt>Eligibility</dt><dd>{result.eligibility_status}</dd></div>
      <div><dt>Recommendation</dt><dd data-testid="recommendation">{fit.recommendation}</dd></div></dl>
    <p>Unknown evidence widens the interval. Transferable evidence receives half credit. Missing information does not prove a lack of skill.</p>
    <section aria-label="Requirement evidence"><h3>Requirement evidence</h3>
      {result.analysis.requirements.length===0&&<p>No usable criteria were identified.</p>}
      {result.analysis.requirements.map(requirement=><article className="review-proposal" key={requirement.id}>
        <h4>{factLabel(requirement.dimension)} · {({single:'Single requirement',all:'All of these',any:'Any of these'})[requirement.operator]}</h4>
        {requirement.needs_review&&<p>The requirement operator needs review.</p>}
        {requirement.members.map(member=>{
          const finding=result.analysis.findings.find(f=>f.member_id===member.id);
          return <div key={member.id}><strong>{member.text}</strong><p>{finding?.status||'unknown'} · {finding?.rationale}</p>
            <h5>Job source</h5>{member.citations.map((citation,i)=><blockquote key={i} style={{whiteSpace:'pre-wrap'}}>{citation.quote}</blockquote>)}
            <h5>Candidate evidence</h5>{finding?.sources?.length?finding.sources.map((source,i)=><p key={i} style={{whiteSpace:'pre-wrap'}}>{source.kind==='profile'?targetLabel(source.target_path):factLabel(source.kind)}: {source.quote}</p>):<p>No supporting evidence supplied.</p>}
          </div>;
        })}
      </article>)}
    </section>
    <h3>Eligibility evidence</h3>{result.analysis.eligibility.length?result.analysis.eligibility.map((item,i)=><article key={i}><h4>{factLabel(item.category)} · {item.status}</h4><p>{item.rationale}</p><blockquote>{item.citation.quote}</blockquote>{item.sources.map((source,n)=><p key={n}>{source.quote}</p>)}</article>):<p>No explicit restriction was identified. Check the full posting for any omitted restrictions.</p>}
    <details><summary>Scoring groups and fixed input identities</summary><FieldValue value={fit.groups.map(g=>({dimension:g.dimension,status:g.status,operator:g.operator,weight:g.weight}))}/><FieldValue value={evaluation.fixed_identities}/></details>
    <Button variant="ghost" disabled={busy} onClick={onRefresh}>Refresh evaluation</Button>
    {needsOverride&&<label className="review-question"><span><input type="checkbox" checked={override} onChange={e=>setOverride(e.target.checked)}/> I reviewed this advice and want to generate anyway.</span></label>}
    <Button disabled={busy||!generationReady||(needsOverride&&!override)} onClick={()=>onGenerate(needsOverride&&override)}>Generate from this role</Button>
  </section>;
}

import React from 'react';
import { Button,Input,Textarea } from './components.jsx';
import { ReadinessPanel,useFormDraft,DraftNotice } from './review-flow.jsx';
import { listJobs,captureJob,getJob,jobEvaluations,createEvaluation,continueEvaluation,getEvaluation,cancelEvaluation,createRun,getProfile } from './api/client.js';
import { actionForRetry } from './draft-store.js';
import { CareerEvaluation } from './career-evaluation.jsx';

const EMPTY={text:'',company:'',role:'',source_url:'',source_key:''};
const FACT_LABELS={authorization:'Work authorization statement',clearance:'Clearance statement',presence:'Required presence statement',user_hard_constraint:'Other explicit hard constraint'};

function EligibilityInputs({job,revision,onChange}) {
  const draft=useFormDraft({form:'eligibility',run:job.id,review:'confirmed-facts',revision},{});
  React.useEffect(()=>{onChange(draft.loaded?draft.value:null);},[draft.loaded,JSON.stringify(draft.value)]);
  return <section><h3>Explicit restriction facts (optional)</h3><p>Supply facts you know. Leave fields blank when uncertain. Personal identity and general location preferences do not establish eligibility.</p>
    <DraftNotice draft={draft} reconcile={value=>draft.edit(value)}/>
    <fieldset disabled={!draft.loaded} style={{border:0,padding:0}}>{Object.entries(FACT_LABELS).map(([key,label])=><label className="review-question" key={key}>{label}<Textarea aria-label={label} value={draft.value[key]||''} onChange={e=>draft.edit(v=>({...v,[key]:e.target.value}))}/></label>)}</fieldset>
  </section>;
}

export function CareerJobs({initialJobId,onRunStarted,goto}) {
  const [jobs,setJobs]=React.useState([]),[job,setJob]=React.useState(null),[evaluations,setEvaluations]=React.useState([]),[evaluation,setEvaluation]=React.useState(null);
  const [profileRevision,setProfileRevision]=React.useState(''),[facts,setFacts]=React.useState(null),[busy,setBusy]=React.useState(false),[error,setError]=React.useState(null),[generationReady,setGenerationReady]=React.useState(false);
  const nextAction=React.useRef(actionForRetry());
  const draft=useFormDraft({form:'job-capture',run:'new',review:'full-source',revision:'capture-v1'},EMPTY);
  const field=(key,value)=>draft.edit(v=>({...v,[key]:value}));
  const perform=async work=>{setBusy(true);setError(null);try{await work();}catch(e){setError(e.message);}finally{setBusy(false);}};
  const select=async selected=>{
    if(job?.id!==selected.id)setFacts(null);
    setJob(selected);setEvaluation(null);setEvaluations([]);
    localStorage.setItem('rg.selectedCareerJob',selected.id);
    const rows=await jobEvaluations(selected.id);setEvaluations(rows);setEvaluation(rows[0]||null);
  };
  const refreshProfile=async()=>{try{setProfileRevision((await getProfile()).revision);}catch{setProfileRevision('');}};
  React.useEffect(()=>{
    perform(async()=>{
      const rows=await listJobs();setJobs(rows);await refreshProfile();
      const id=initialJobId||localStorage.getItem('rg.selectedCareerJob');
      if(id) {try{await select(rows.find(r=>r.id===id)||await getJob(id));}catch(e){if(e.status!==404)throw e;}}
    });
  },[initialJobId]);
  const save=()=>perform(async()=>{
    const body={text:draft.value.text};for(const key of ['company','role','source_key','source_url'])if(draft.value[key]?.trim())body[key]=draft.value[key];
    const created=await captureJob(body);setJobs(await listJobs());await select(created);await draft.clear();draft.edit(EMPTY);
  });
  const update=async result=>{setEvaluation(result);setEvaluations(await jobEvaluations(job.id));};
  const evaluate=()=>perform(async()=>{
    const eligibility_facts=Object.fromEntries(Object.entries(facts||{}).filter(([,v])=>v.trim()));
    const created=await createEvaluation(job.id,{eligibility_facts});await update(created);
    await update(await continueEvaluation(created.id));
  });
  const refreshEvaluation=()=>perform(async()=>{await refreshProfile();await update(await getEvaluation(evaluation.id));});
  const continueSaved=()=>perform(async()=>await update(await continueEvaluation(evaluation.id,evaluation.status==='interrupted'?nextAction.current({kind:'continue'}):null)));
  const generate=(override,withEvaluation=true)=>perform(async()=>{
    const result=await createRun({jdText:job.text,jobId:job.id,evaluationId:withEvaluation?evaluation?.id:undefined,evaluationOverride:override});
    onRunStarted(result);
  });
  return <main className="page-pad review-flow" style={{padding:32,maxWidth:1150}}>
    <h1>Jobs and role decisions</h1><p>Save the complete posting, inspect its evidence fit, then choose whether to tailor a resume. Saving a role does not call a model.</p>
    {error&&<p role="alert">{error}</p>}
    <ReadinessPanel onReady={setGenerationReady} goto={goto}/>
    <section><h2>Save a role</h2><DraftNotice draft={draft} reconcile={value=>draft.edit(value)}/>
      <fieldset disabled={busy||!draft.loaded} style={{border:0,padding:0}}>
        <label className="review-question">Full job description<Textarea aria-label="Full job description" value={draft.value.text} onChange={e=>field('text',e.target.value)} rows={8}/></label><p>{draft.value.text.length} of 48,000 characters</p>
        {['company','role','source_url','source_key'].map(key=><label className="review-question" key={key}>{({company:'Company',role:'Role',source_url:'Original posting URL (optional)',source_key:'Stable source key (optional)'})[key]}<Input aria-label={({company:'Company',role:'Role',source_url:'Original posting URL (optional)',source_key:'Stable source key (optional)'})[key]} value={draft.value[key]} onChange={e=>field(key,e.target.value)}/></label>)}
        <Button disabled={!draft.value.text.trim()||draft.value.text.length>48000||busy} onClick={save}>Save role</Button>
      </fieldset>
    </section>
    <section><h2>Saved jobs</h2>{jobs.map(item=><Button key={item.id} variant={job?.id===item.id?'primary':'ghost'} disabled={busy} onClick={()=>perform(()=>select(item))}>{item.company||'Company not supplied'} · {item.role||'Role not supplied'}</Button>)}</section>
    {job&&<section><h2>Saved role</h2><h3>{job.company||'Company not supplied'} · {job.role||'Role not supplied'}</h3>
      <details><summary>Full saved job description</summary><p style={{whiteSpace:'pre-wrap'}}>{job.text}</p></details>
      {job.source_url&&<a href={job.source_url} target="_blank" rel="noreferrer">Original posting</a>}
      <EligibilityInputs key={job.id} job={job} revision={profileRevision} onChange={setFacts}/>
      <Button disabled={busy||facts===null} onClick={evaluate}>Evaluate role</Button>
      {evaluations.length>1&&<label className="review-question">Evaluation history<select aria-label="Evaluation history" value={evaluation?.id||''} disabled={busy} onChange={e=>perform(async()=>setEvaluation(await getEvaluation(e.target.value)))}>{evaluations.map(e=><option key={e.id} value={e.id}>{e.id} · {e.status}{e.stale?' · changed inputs':''}</option>)}</select></label>}
      {evaluation&&<CareerEvaluation evaluation={evaluation} busy={busy} generationReady={generationReady} onRefresh={refreshEvaluation} onGenerate={override=>generate(override)}/>}
      {evaluation&&['pending_model','interrupted'].includes(evaluation.status)&&<><Button disabled={busy} onClick={continueSaved}>Continue saved evaluation</Button>{' '}<Button disabled={busy} onClick={()=>perform(async()=>await update(await cancelEvaluation(evaluation.id)))}>Cancel evaluation</Button></>}
      {!evaluation?.result&&<Button disabled={busy||!generationReady} onClick={()=>generate(false,false)}>Generate without evaluation</Button>}
    </section>}
  </main>;
}

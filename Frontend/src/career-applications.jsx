import React from 'react';
import { Button,Input,Textarea } from './components.jsx';
import { DraftNotice,useFormDraft } from './review-flow.jsx';
import { actionForRetry } from './draft-store.js';
import { listJobs,listRuns,jobEvaluations,listApplications,createApplication,getApplication,appendApplicationEvent } from './api/client.js';

const EMPTY={kind:'',date:'',artifact:'',evaluation:'',stage:'',category:'',reason:'',target:'',replacement:'',closure:false};
const STAGES=['screening','interviewing','offer','rejected','withdrawn','closed'];
const KINDS={submit:'Record a submission',stage_change:'Record a stage',response_received:'Record a response',reopen:'Reopen an attempt',correction:'Correct an earlier event'};
function progressEvent(kind,v) {
  const occurred_at=v.date||null;
  if(kind==='submit') {
    if(!v.artifact)throw new Error('Choose the submitted document or explicitly mark it unknown.');
    return {kind,occurred_at,artifact_unknown:v.artifact==='unknown',artifact_run_id:v.artifact==='unknown'?null:v.artifact,evaluation_id:v.evaluation||null};
  }
  if(kind==='stage_change') {if(!v.stage)throw new Error('Choose a stage.');return {kind,occurred_at,stage:v.stage,closure_without_response:v.stage==='closed'&&v.closure};}
  if(kind==='response_received') {if(!v.category)throw new Error('Choose a response category.');return {kind,occurred_at,category:v.category};}
  if(kind==='reopen') {if(!v.stage||!v.reason.trim())throw new Error('Choose a stage and explain why.');return {kind,occurred_at,stage:v.stage,reason:v.reason};}
  throw new Error('Choose an event type.');
}
function eventPayload(v) {
  if(v.kind!=='correction')return progressEvent(v.kind,v);
  if(!v.target||!v.reason.trim()||!v.replacement)throw new Error('Choose an original event, correction action and reason.');
  return {kind:'correction',occurred_at:v.date||null,target_event_id:v.target,reason:v.reason,replacement:v.replacement==='void'?null:progressEvent(v.replacement,v)};
}
function EventEditor({view,runs,evaluations,busy,perform,onUpdate}) {
  const draft=useFormDraft({form:'application-event',run:view.id,review:'event',revision:view.revision},EMPTY);
  const next=React.useRef(actionForRetry()),v=draft.value;
  const edit=(key,value)=>draft.edit(current=>({...current,[key]:value}));
  const effective=v.kind==='correction'?v.replacement:v.kind;
  let payload,problem;try{payload=eventPayload(v);}catch(e){problem=e.message;}
  const record=()=>perform(async()=>{const result=await appendApplicationEvent(view.id,next.current({expected_revision:view.revision,event:payload}));await draft.clear();await onUpdate(result);});
  const eventNames={submit:'Submission',stage_change:'Stage',response_received:'Response',reopen:'Reopen',correction:'Correction'};
  return <section><h2>Record an event</h2><p>Record what happened outside this app. This control does not contact an employer. Dates are optional; leave the date empty if unknown.</p>
    <DraftNotice draft={draft} reconcile={value=>draft.edit(value)}/>
    <fieldset disabled={busy||!draft.loaded} style={{border:0,padding:0}}>
      <label className="review-question">Event type<select aria-label="Event type" value={v.kind} onChange={e=>draft.edit({...EMPTY,kind:e.target.value})}><option value="">Choose an event</option>{Object.entries(KINDS).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
      <label className="review-question">Event date (optional)<Input aria-label="Event date (optional)" type="date" value={v.date} onChange={e=>edit('date',e.target.value)}/></label>
      {v.kind==='correction'&&<><label className="review-question">Original event<select aria-label="Original event" value={v.target} onChange={e=>edit('target',e.target.value)}><option value="">Choose an original event</option>{view.events.filter(e=>e.payload.kind!=='correction').map(e=><option key={e.id} value={e.id}>{e.seq}. {eventNames[e.payload.kind]} · {e.payload.category||e.payload.stage||e.payload.occurred_at||'date unknown'}</option>)}</select></label>
        <label className="review-question">Correction reason<Textarea aria-label="Correction reason" value={v.reason} onChange={e=>edit('reason',e.target.value)}/></label>
        <label className="review-question">Correction action<select aria-label="Correction action" value={v.replacement} onChange={e=>edit('replacement',e.target.value)}><option value="">Choose a correction</option><option value="void">Void the original event</option>{Object.entries(KINDS).filter(([key])=>key!=='correction').map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label></>}
      {effective==='submit'&&<><label className="review-question">Submitted document<select aria-label="Submitted document" value={v.artifact} onChange={e=>edit('artifact',e.target.value)}><option value="">Choose explicitly</option><option value="unknown">Document unknown / not generated here</option>{runs.filter(r=>r.release?.status==='released').map(r=><option key={r.id} value={r.id}>{r.company} · {r.role} · {r.release.pdf_hash.slice(0,12)}{r.job_id!==view.job_id?' · different or unlinked role':''}</option>)}</select></label>
        <label className="review-question">Evaluation to freeze (optional)<select aria-label="Evaluation to freeze (optional)" value={v.evaluation} onChange={e=>edit('evaluation',e.target.value)}><option value="">No known evaluation</option>{evaluations.filter(e=>e.status==='complete').map(e=><option key={e.id} value={e.id}>{e.created_at} · {e.result?.fit?.lower??'Unscored'}{e.stale?' · changed inputs':''}</option>)}</select></label><p>The selected document hashes and evaluation are saved as they stand now. Reopening this attempt does not record another submission.</p></>}
      {['stage_change','reopen'].includes(effective)&&<label className="review-question">New stage<select aria-label="New stage" value={v.stage} onChange={e=>edit('stage',e.target.value)}><option value="">Choose a stage</option>{(effective==='reopen'?['planned','submitted','screening','interviewing','offer']:STAGES).map(s=><option key={s}>{s}</option>)}</select></label>}
      {effective==='stage_change'&&v.stage==='closed'&&<label><input type="checkbox" checked={v.closure} onChange={e=>edit('closure',e.target.checked)}/> I confirmed closure without a response.</label>}
      {effective==='response_received'&&<label className="review-question">Response category<select aria-label="Response category" value={v.category} onChange={e=>edit('category',e.target.value)}><option value="">Choose a category</option>{['acknowledgment','rejection','favorable','other'].map(s=><option key={s}>{s}</option>)}</select></label>}
      {effective==='reopen'&&v.kind!=='correction'&&<label className="review-question">Reopen reason<Textarea aria-label="Reopen reason" value={v.reason} onChange={e=>edit('reason',e.target.value)}/></label>}
      <p>{problem||'Review the event and selected evidence before recording it.'}</p><Button disabled={!payload||busy} onClick={record}>Record event</Button>
    </fieldset>
  </section>;
}

export function CareerApplications({goto}) {
  const [jobs,setJobs]=React.useState([]),[rows,setRows]=React.useState([]),[selected,setSelected]=React.useState(null),[runs,setRuns]=React.useState([]),[evaluations,setEvaluations]=React.useState([]),[jobId,setJobId]=React.useState('');
  const [busy,setBusy]=React.useState(false),[error,setError]=React.useState(null);const createAction=React.useRef(actionForRetry());
  const perform=async work=>{setBusy(true);setError(null);try{await work();}catch(e){setError(e.message);}finally{setBusy(false);}};
  const select=async view=>{setSelected(view);localStorage.setItem('rg.application',view.id);setEvaluations([]);setEvaluations(await jobEvaluations(view.job_id));};
  const refresh=async()=>{const [applications,allJobs,allRuns]=await Promise.all([listApplications(),listJobs(),listRuns()]);setRows(applications);setJobs(allJobs);setRuns(allRuns);const saved=applications.find(r=>r.id===localStorage.getItem('rg.application'))||applications[0];if(saved)await select(saved);};
  React.useEffect(()=>{perform(refresh);},[]);
  const create=()=>perform(async()=>{const view=await createApplication(createAction.current({job_id:jobId}));createAction.current=actionForRetry();await select(view);setRows(await listApplications());});
  const updated=async view=>{setSelected(view);setRows(await listApplications());};
  return <main className="page-pad review-flow career-operations" style={{padding:32,maxWidth:1150}}><h1>Application records</h1><p>Keep one record for each application attempt. Generating a PDF does not mark an application submitted. Replies and outcomes come from events you record.</p>
    {error&&<p role="alert">{error}</p>}<Button disabled={busy} onClick={()=>perform(refresh)}>Refresh application records</Button>
    <section><h2>Start a record</h2><label className="review-question">Application role<select aria-label="Application role" value={jobId} disabled={busy} onChange={e=>setJobId(e.target.value)}><option value="">Choose a saved role</option>{jobs.map(j=><option key={j.id} value={j.id}>{j.company||'Company not supplied'} · {j.role||'Role not supplied'} · {j.created_at}</option>)}</select></label><Button disabled={busy||!jobId} onClick={create}>Create application record</Button>{' '}<Button variant="ghost" onClick={()=>goto('jobs')}>Save or review a role</Button></section>
    <section><h2>Saved attempts</h2>{rows.length===0&&<p>No application records.</p>}{rows.map(a=><Button variant={selected?.id===a.id?'primary':'ghost'} key={a.id} disabled={busy} onClick={()=>perform(async()=>await select(await getApplication(a.id)))}>{a.company||'Company not supplied'} · {a.role||'Role not supplied'} · {a.stage} · {a.created_at}</Button>)}</section>
    {selected&&<><section><h2>{selected.company||'Company not supplied'} · {selected.role||'Role not supplied'}</h2><p>Stage: <strong data-testid="application-stage">{selected.stage}</strong></p><Button onClick={()=>goto('jobs',{jobId:selected.job_id})}>Review linked role</Button>
      {selected.submission?<div data-testid="submission-binding"><h3>Recorded submission</h3><p>Date: {selected.submission.occurred_at||'Unknown'}</p><p>{selected.submission.artifact?`Document hash: ${selected.submission.artifact.pdf_hash}`:'Document unknown'}</p>{selected.submission.artifact&&<p>{selected.submission.artifact.available?'Saved document is available.':'Saved document is missing or changed.'} {selected.submission.artifact.job_match?'Matches this role.':'Different or unlinked role; this choice is retained in the audit.'}</p>}<p>{selected.submission.evaluation?`Frozen evidence fit: ${selected.submission.evaluation.fit.lower??'Unscored'} · ${selected.submission.evaluation.rubric_version}${selected.submission.evaluation.stale_at_recording?' · inputs had changed at recording':''}`:'No evaluation was selected for this submission.'}</p></div>:<p>No submission has been recorded.</p>}
    </section><EventEditor key={selected.id} view={selected} runs={runs} evaluations={evaluations} busy={busy} perform={perform} onUpdate={updated}/>
    <section data-testid="application-audit"><h2>Event audit</h2><p>Corrections preserve the original event. Reports use its latest correction.</p>{selected.events.map(e=><section key={e.id}><h3>{e.seq}. {e.payload.kind.replaceAll('_',' ')}</h3><p>Occurred: {e.payload.occurred_at||'Unknown'} · Recorded: {e.recorded_at}</p>{e.payload.stage&&<p>Stage: {e.payload.stage}</p>}{e.payload.category&&<p>Response: {e.payload.category}</p>}{e.payload.reason&&<p>Reason: {e.payload.reason}</p>}{e.payload.kind==='correction'&&<p>Corrects event {selected.events.find(original=>original.id===e.payload.target_event_id)?.seq}: {e.payload.replacement?`${e.payload.replacement.kind} · ${e.payload.replacement.category||e.payload.replacement.stage||''}`:'Voided'}</p>}</section>)}</section></>}
  </main>;
}

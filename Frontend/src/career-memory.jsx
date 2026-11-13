import React from 'react';
import { Button, Input, Textarea } from './components.jsx';
import { listMemory, proposeMemory, previewMemory, decideMemory, memoryHistory, getProfile } from './api/client.js';
import { FieldValue, targetLabel } from './profile-facts.jsx';
import { factTargets, stringHash } from './memory-draft.js';
import { actionForRetry } from './draft-store.js';

const names={candidate_fact:'Candidate fact',target_preference:'Target preference',writing_rule:'Writing rule'};

export function CareerMemory() {
  const [rows,setRows]=React.useState([]);
  const [profile,setProfile]=React.useState(null);
  const [preview,setPreview]=React.useState(null);
  const [history,setHistory]=React.useState([]);
  const [kind,setKind]=React.useState('writing_rule');
  const [instruction,setInstruction]=React.useState('');
  const [source,setSource]=React.useState('');
  const [locations,setLocations]=React.useState('');
  const [modes,setModes]=React.useState([]);
  const [path,setPath]=React.useState('');
  const [after,setAfter]=React.useState('');
  const [supersedes,setSupersedes]=React.useState(null);
  const [error,setError]=React.useState(null);
  const [busy,setBusy]=React.useState(false);
  const nextAction=React.useRef(actionForRetry());
  const refresh=async()=>{
    const records=await listMemory(); setRows(records);
    try { setProfile(await getProfile()); } catch { setProfile(null); }
  };
  React.useEffect(()=>{ refresh().catch(e=>setError(e.message)); },[]);
  const perform=async work=>{
    setBusy(true);setError(null);
    try { await work(); } catch(e) { setError(e.status===409 ? `This change conflicts with current saved information. Refresh and create a new proposal against the current profile. ${e.message}` : e.message); }
    finally { setBusy(false); }
  };
  const inspect=async record=>{
    const [review,audit]=await Promise.all([previewMemory(record.id),memoryHistory(record.id)]);
    setPreview(review);setHistory(audit);
  };
  const create=()=>perform(async()=>{
    let payload;
    if(kind==='writing_rule') payload={instruction};
    else if(kind==='target_preference') payload={preferred_locations:locations.split(',').map(s=>s.trim()).filter(Boolean),work_modes:modes,hard_constraints:[]};
    else {
      const target=factTargets(profile?.profile).find(t=>t.path===path);
      if(!target) throw new Error('Choose a current profile field.');
      payload={operation:'replace',target_path:path,before_hash:await stringHash(target.value),after};
    }
    const record=await proposeMemory({kind,payload,source_refs:[{kind:'user_text',text:source}],
      ...(kind==='candidate_fact'?{base_profile_revision:profile.revision}:{}),...(supersedes?{supersedes}:{})});
    await refresh();await inspect(record);setSupersedes(null);
    setInstruction('');setSource('');setAfter('');setPath('');setLocations('');setModes([]);
  });
  const decide=(record,decision)=>perform(async()=>{
    const action=nextAction.current({decision,expected_revision:record.revision});
    await decideMemory(record.id,action);setPreview(null);setHistory([]);await refresh();
  });
  const retry=record=>perform(async()=>{
    const audit=await memoryHistory(record.id);
    const saved=audit.find(row=>row.action_id===record.promotion.action_id);
    if(!saved) throw new Error('The saved decision could not be found. Refresh memory.');
    await decideMemory(record.id,JSON.parse(saved.request_json));setPreview(null);await refresh();
  });
  const replace=record=>{
    setKind(record.kind);setSupersedes({id:record.id,revision:record.revision});setPreview(null);
    setInstruction(record.payload.instruction||'');setLocations((record.payload.preferred_locations||[]).join(', '));setModes(record.payload.work_modes||[]);
  };
  const active=rows.filter(r=>r.status==='accepted'&&r.kind!=='candidate_fact');
  return <main className="page-pad review-flow" style={{padding:32,maxWidth:1100}}>
    <h1>Memory</h1><p>Save reviewed facts, targeting preferences and writing rules for future work. Earlier runs keep their original inputs.</p>
    {error&&<p role="alert">{error}</p>}
    <Button variant="ghost" disabled={busy} onClick={()=>perform(refresh)}>Refresh memory</Button>
    <section><h2>Propose a change</h2>
      <fieldset disabled={busy} style={{border:0,padding:0}}>
        <label className="review-question">Change type<select aria-label="Change type" value={kind} onChange={e=>{setKind(e.target.value);setSupersedes(null);}}>{Object.entries(names).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
        {supersedes&&<p>This proposal replaces an active rule only after you accept it.</p>}
        {kind==='writing_rule'&&<label className="review-question">Writing instruction<Textarea aria-label="Writing instruction" value={instruction} onChange={e=>setInstruction(e.target.value)}/></label>}
        {kind==='target_preference'&&<>
          <label className="review-question">Preferred locations<Input aria-label="Preferred locations" value={locations} onChange={e=>setLocations(e.target.value)} placeholder="Separate locations with commas"/></label>
          <p>Preferred work modes</p>{['Remote','Hybrid','On-site'].map(mode=><label key={mode} style={{marginRight:16}}><input type="checkbox" checked={modes.includes(mode)} onChange={e=>setModes(e.target.checked?[...modes,mode]:modes.filter(v=>v!==mode))}/> {mode}</label>)}
          <p>Preferences guide future decisions. They do not establish work authorization.</p>
        </>}
        {kind==='candidate_fact'&&<>
          <p>Accepting a fact correction changes the base resume. Review the exact before and after values.</p>
          <label className="review-question">Profile field<select aria-label="Profile field" value={path} onChange={e=>setPath(e.target.value)}><option value="">Choose a field</option>{factTargets(profile?.profile).map(t=><option key={t.path} value={t.path}>{targetLabel(t.path,profile?.profile)}</option>)}</select></label>
          {path&&<p>Current value: {factTargets(profile?.profile).find(t=>t.path===path)?.value}</p>}
          <label className="review-question">Corrected value<Textarea aria-label="Corrected value" value={after} onChange={e=>setAfter(e.target.value)}/></label>
        </>}
        <label className="review-question">Source or reason<Textarea aria-label="Source or reason" value={source} onChange={e=>setSource(e.target.value)} placeholder="Enter the exact information you supplied or confirmed"/></label>
        <Button disabled={!source.trim()||busy||(kind==='writing_rule'&&!instruction.trim())||(kind==='candidate_fact'&&!path)} onClick={create}>Create proposal</Button>
      </fieldset>
    </section>
    {preview&&<section className="review-notice" aria-label="Memory review"><h2>Review memory proposal</h2>
      <h3>{names[preview.record.kind]}</h3>
      {preview.record.kind==='candidate_fact'&&<p>{targetLabel(preview.record.payload.target_path,preview.profile_before)}</p>}
      <h4>Before</h4><FieldValue value={preview.before}/><h4>After</h4><FieldValue value={preview.after}/>
      <h4>Source</h4>{preview.record.source_refs.map((ref,i)=><p key={i} style={{whiteSpace:'pre-wrap'}}>{ref.text}</p>)}
      {preview.record.kind==='candidate_fact'&&<details><summary>Complete proposed profile</summary><FieldValue value={preview.profile_after}/></details>}
      {preview.stale&&<p>This proposal refers to an older profile. Create a new proposal against the current profile before accepting.</p>}
      {preview.record.status==='pending'&&<><Button disabled={busy||preview.stale} onClick={()=>decide(preview.record,'accept')}>Accept reviewed change</Button>{' '}<Button disabled={busy} onClick={()=>decide(preview.record,'reject')}>Reject proposal</Button></>}
      {preview.record.status==='applying'&&<Button disabled={busy} onClick={()=>retry(preview.record)}>Retry saved correction</Button>}
      {preview.record.status==='conflict'&&<p>The profile changed. Create a new reviewed proposal against the current profile.</p>}
      <details><summary>Decision history</summary>{history.length?history.map(row=><p key={row.action_id}>{row.decision} · {row.recorded_at}</p>):<p>No decision recorded.</p>}</details>
      <Button variant="ghost" onClick={()=>setPreview(null)}>Close review</Button>
    </section>}
    <section><h2>Active memory</h2>{active.length?active.map(record=><article className="review-proposal" key={record.id}><h3>{names[record.kind]}</h3><FieldValue value={record.payload}/>
      <Button disabled={busy} onClick={()=>perform(()=>inspect(record))}>Review source</Button>{' '}<Button disabled={busy} onClick={()=>decide(record,'revoke')}>Revoke</Button>{' '}<Button disabled={busy} onClick={()=>replace(record)}>Replace rule</Button>
    </article>):<p>No active preferences or writing rules.</p>}</section>
    <section><h2>All proposals and corrections</h2>{rows.map(record=><article className="review-proposal" key={record.id}><h3>{names[record.kind]} · {record.status}</h3><FieldValue value={record.payload}/><Button disabled={busy} onClick={()=>perform(()=>inspect(record))}>Review proposal</Button></article>)}</section>
  </main>;
}

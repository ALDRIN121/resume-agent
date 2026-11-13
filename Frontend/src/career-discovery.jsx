import React from 'react';
import { Button,Input } from './components.jsx';
import { DraftNotice,useFormDraft } from './review-flow.jsx';
import { actionForRetry } from './draft-store.js';
import { getDiscoverySources,saveDiscoverySources,listDiscoverySyncs,createDiscoverySync,getDiscoverySync,continueDiscoverySync,cancelDiscoverySync,discoveryPostings } from './api/client.js';

function SourceForm({configuration,busy,onSave}) {
  const draft=useFormDraft({form:'discovery-sources',run:'boards',review:'configuration',revision:configuration.revision},{sources:configuration.sources});
  const rows=draft.value.sources||[];
  const edit=(index,key,value)=>draft.edit(v=>({sources:v.sources.map((s,i)=>i===index?{...s,[key]:value,...(key==='provider'&&value!=='lever'?{region:'global'}:{})}:s)}));
  return <section><h2>Public board sources</h2><p>Add up to 20 public board names. Confirm the company label yourself. Only enabled sources enter a new scan.</p>
    <DraftNotice draft={draft} reconcile={value=>draft.edit(value)}/>
    <fieldset disabled={busy||!draft.loaded} style={{border:0,padding:0}}>
      {rows.map((source,i)=><section key={source.id||i} className="source-row">
        <label>Provider {i+1}<select aria-label={`Provider ${i+1}`} value={source.provider} disabled={!!source.id} onChange={e=>edit(i,'provider',e.target.value)}>{['greenhouse','lever','ashby'].map(p=><option key={p}>{p}</option>)}</select></label>
        <label>Board name {i+1}<Input aria-label={`Board name ${i+1}`} value={source.board} disabled={!!source.id} onChange={e=>edit(i,'board',e.target.value)}/></label>
        {source.provider==='lever'&&<label>Lever region {i+1}<select aria-label={`Lever region ${i+1}`} value={source.region||'global'} disabled={!!source.id} onChange={e=>edit(i,'region',e.target.value)}><option value="global">Global</option><option value="eu">Europe</option></select></label>}
        <label>Confirmed company {i+1}<Input aria-label={`Confirmed company ${i+1}`} value={source.company||''} onChange={e=>edit(i,'company',e.target.value)}/></label>
        <label><input type="checkbox" checked={source.enabled!==false} onChange={e=>edit(i,'enabled',e.target.checked)}/> Enabled source {i+1}</label>
        <Button variant="ghost" onClick={()=>draft.edit(v=>({sources:v.sources.filter((_,j)=>j!==i)}))}>Remove source {i+1}</Button>
      </section>)}
      <Button disabled={rows.length>=20} onClick={()=>draft.edit(v=>({sources:[...v.sources,{provider:'greenhouse',board:'',region:'global',company:'',enabled:true}]}))}>Add source</Button>{' '}
      <Button disabled={rows.some(s=>!s.board.trim())} onClick={()=>onSave(rows.map(s=>({...s,company:s.company?.trim()||null})),draft.clear)}>Save sources</Button>
    </fieldset><p>To change a saved provider, board name or region, remove that row and add another. Saved job history stays available.</p>
  </section>;
}

export function CareerDiscovery({goto}) {
  const [configuration,setConfiguration]=React.useState(null),[scans,setScans]=React.useState([]),[scan,setScan]=React.useState(null),[page,setPage]=React.useState(null);
  const [offset,setOffset]=React.useState(0),[source,setSource]=React.useState(''),[state,setState]=React.useState('');
  const [busy,setBusy]=React.useState(false),[error,setError]=React.useState(null),[notice,setNotice]=React.useState('');
  const saveAction=React.useRef(actionForRetry()),newScan=React.useRef(actionForRetry()),resumeAction=React.useRef(actionForRetry()),cancelAction=React.useRef(actionForRetry());
  const loadPage=()=>discoveryPostings({offset,source_id:source,state}).then(setPage);
  const refresh=async(id)=>{const rows=await listDiscoverySyncs();setScans(rows);setScan(rows.find(r=>r.id===(id||localStorage.getItem('rg.discoveryScan')))||rows[0]||null);await loadPage();};
  const perform=async work=>{setBusy(true);setError(null);try{await work();}catch(e){setError(e.message);}finally{setBusy(false);}};
  React.useEffect(()=>{perform(async()=>{setConfiguration(await getDiscoverySources());await refresh();});},[]);
  React.useEffect(()=>{loadPage().catch(e=>setError(e.message));},[offset,source,state]);
  React.useEffect(()=>{
    if(!scan||!['queued','running'].includes(scan.status)||!busy&&scan.status==='queued')return;
    const timer=setInterval(()=>getDiscoverySync(scan.id).then(setScan).catch(e=>setError(e.message)),1000);
    return ()=>clearInterval(timer);
  },[scan?.id,scan?.status,busy]);
  const selectScan=id=>perform(async()=>{localStorage.setItem('rg.discoveryScan',id);setScan(await getDiscoverySync(id));});
  const drive=id=>perform(async()=>{setScan(await continueDiscoverySync(id,scan?.status==='interrupted'?resumeAction.current({kind:'continue'}):null));await refresh(id);});
  const manualScan=()=>perform(async()=>{
    const created=await createDiscoverySync(newScan.current({expected_sources_revision:configuration.revision}));
    newScan.current=actionForRetry();localStorage.setItem('rg.discoveryScan',created.id);setScan(created);setNotice('');
    setScan(await continueDiscoverySync(created.id));await refresh(created.id);
  });
  const cancel=async()=>{setError(null);try{setScan(await cancelDiscoverySync(scan.id,cancelAction.current({})));await refresh(scan.id);}catch(e){setError(e.message);}};
  return <main className="page-pad review-flow career-operations" style={{padding:32,maxWidth:1150}}>
    <h1>Discover public roles</h1><p>Refresh chosen public boards, review the complete saved role, then choose whether to evaluate it. Discovery does not call a model or submit applications.</p>
    {error&&<p role="alert">{error} <Button onClick={()=>perform(async()=>{setConfiguration(await getDiscoverySources());await refresh();})}>Reload saved state</Button></p>}
    {notice&&<p role="status">{notice}</p>}
    {configuration&&<SourceForm configuration={configuration} busy={busy} onSave={(sources,clear)=>perform(async()=>{const saved=await saveDiscoverySources(saveAction.current({sources,expected_revision:configuration.revision}));await clear();setConfiguration(saved);setNotice('Source configuration saved.');})}/>}
    <section><h2>Manual scans</h2><Button disabled={busy||!configuration} onClick={manualScan}>Refresh enabled sources</Button>
      {scans.length>0&&<label className="review-question">Saved scan<select aria-label="Saved scan" value={scan?.id||''} disabled={busy} onChange={e=>selectScan(e.target.value)}>{scans.map(s=><option key={s.id} value={s.id}>{s.created_at} · {s.status} · {s.source_count} sources</option>)}</select></label>}
      {scan&&<><p>Status: <strong data-testid="scan-status">{scan.status}</strong> · {scan.completed_boards}/{scan.source_count} boards · {scan.request_attempts} request attempts</p>
        {scan.diagnostics?.map(d=><p key={d}>{d==='no_enabled_sources'?'No enabled sources were selected.':d}</p>)}
        {['queued','interrupted'].includes(scan.status)&&<Button disabled={busy} onClick={()=>drive(scan.id)}>Continue saved scan</Button>}{' '}
        {['queued','running','interrupted'].includes(scan.status)&&<Button onClick={cancel}>Cancel scan</Button>}
        <p>Limits: 20 boards; 1,000 records per board; 3 concurrent requests; 20 seconds and 10 MiB per request; at most 3 attempts. Partial and failed scans preserve earlier jobs.</p>
        {scan.boards.map(b=><section key={b.source_id}><h3>{b.source.company||b.source.board} · {b.source.provider}</h3><p>{b.status} · {b.valid_count??0} valid of {b.received_count??0} received · {b.malformed_count??0} malformed · {b.duplicate_count??0} duplicate · {b.filtered_count??0} unlisted · {b.truncated_count??0} beyond limit</p>{b.limit_reached&&<p>Scan limit reached. This board may be incomplete.</p>}{b.diagnostics?.length>0&&<p>Source details: {b.diagnostics.join(', ')}</p>}</section>)}
      </>}
    </section>
    <section><h2>Saved discoveries</h2>
      <label>Filter source<select aria-label="Filter source" value={source} onChange={e=>{setOffset(0);setSource(e.target.value);}}><option value="">All sources, including removed configurations</option>{configuration?.sources.map(s=><option key={s.id} value={s.id}>{s.company||s.board} · {s.provider}</option>)}</select></label>{' '}
      <label>Posting state<select aria-label="Posting state" value={state} onChange={e=>{setOffset(0);setState(e.target.value);}}><option value="">All states</option><option value="active">Active</option><option value="removed">Absent from complete scan</option></select></label>
      {page&&<p>{page.total?`${page.offset+1}–${page.offset+page.items.length} of ${page.total}`:'No saved postings.'}</p>}
      {page?.items.map(p=><section key={`${p.source_id}:${p.external_id}`} data-testid={`posting-${p.external_id}`}><h3>{p.job.company||'Company not confirmed'} · {p.job.role}</h3>
        <p>{p.source.provider} / {p.source.board} · {p.freshness} · {p.state==='removed'?'Absent from a complete scan':p.state}</p><p>Last seen: {p.last_seen_at||'Unknown'} · Last complete scan: {p.source_state.last_complete_at||'None'}</p>
        {p.state==='removed'&&<p>This source did not list the role in a complete scan. Employer closure is unconfirmed.</p>}
        {!p.source_enabled&&<p>This source is disabled or no longer configured. Saved evidence remains available.</p>}
        {p.possible_duplicate_count>0&&<p>{p.possible_duplicate_count} similar role(s) on other providers. These remain separate saved roles.</p>}
        <Button onClick={()=>goto('jobs',{jobId:p.job_id})}>Review role</Button>
      </section>)}
      <Button disabled={offset===0||busy} onClick={()=>setOffset(Math.max(0,offset-50))}>Previous postings</Button>{' '}<Button disabled={!page?.has_more||busy} onClick={()=>setOffset(offset+50)}>More postings</Button>
    </section>
  </main>;
}

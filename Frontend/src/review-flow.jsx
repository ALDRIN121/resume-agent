import React from 'react';
import { Button, Textarea } from './components.jsx';
import { contentPreview, resumeRun, previewUrl, downloadPdf, reexportRun, recoverRun, getReadiness, getProfile, reviewProfile } from './api/client.js';
import { draftStore, draftKey, matchingDrafts, reviewIdentity, reviewAction, actionForRetry } from './draft-store.js';
import { FieldValue, targetLabel, AdvisoryList } from './profile-facts.jsx';

export function useFormDraft(identity, initial) {
  const key = draftKey(identity);
  const [value, setValue] = React.useState(initial);
  const [loaded, setLoaded] = React.useState(false);
  const [stale, setStale] = React.useState([]);
  const [storageError, setStorageError] = React.useState(null);
  const identityRef = React.useRef(identity); identityRef.current = identity;
  const writes = React.useRef(Promise.resolve());
  React.useEffect(() => {
    let alive = true;
    setLoaded(false);
    draftStore.list().then(rows => {
      if (!alive) return;
      const found = matchingDrafts(rows, identityRef.current);
      setValue(found.exact?.value || initial);
      setStale(found.stale);
    }).catch(e => { if (alive) setStorageError(e.message); }).finally(() => { if (alive) setLoaded(true); });
    return () => { alive = false; };
  }, [key]);
  const edit = next => setValue(current => {
    const updated = typeof next === 'function' ? next(current) : next;
    const target = identityRef.current;
    // Queue immediately, including the final keystroke before navigation.
    writes.current = writes.current.catch(() => {}).then(() => draftStore.put(target, updated)).catch(e => setStorageError(e.message));
    return updated;
  });
  const discard = async row => {
    try { await draftStore.remove(row.identity); setStale(items => items.filter(item => item.key !== row.key)); }
    catch (e) { setStorageError(e.message); }
  };
  const clear = async () => {
    await writes.current;
    try { await draftStore.remove(identityRef.current); } catch(e) { setStorageError(e.message); }
  };
  return { value, edit, loaded, stale, storageError, discard, clear };
}

export function DraftNotice({ draft, reconcile }) {
  return <>
    {draft.storageError && <p role="alert">{draft.storageError}</p>}
    {draft.stale.map(row => <section className="review-notice" key={row.key} aria-label="Older form draft">
      <strong>An older draft needs reconciliation</strong>
      <p>The review or profile revision changed. Compare these edits before copying them into the current review.</p>
      <FieldValue value={row.value}/>
      <Button size="sm" onClick={() => reconcile(row.value)}>Copy into current form</Button>{' '}
      <Button size="sm" variant="ghost" onClick={() => draft.discard(row)}>Discard older draft</Button>
    </section>)}
  </>;
}

export function DisplayProjection({ preview }) {
  if (!preview?.manifest) return null;
  return <section aria-label="Complete content preview" className="content-projection">
    <h3>Complete resume content</h3>
    {preview.manifest.display_fields.map((field, index) => <div key={index} className={`display-${field.kind}`}>
      {field.visible_label && <strong>{field.visible_label} </strong>}{field.text}
    </div>)}
    <h4>Omitted fields</h4>
    {preview.manifest.omissions.length ? <ul>{preview.manifest.omissions.map((item, i) => <li key={i}>{targetLabel(item.source_path, preview.projected_profile)}: {item.reason}</li>)}</ul> : <p>No fields omitted.</p>}
  </section>;
}

export function ReadinessPanel({ onReady, goto }) {
  const [state, setState] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [review, setReview] = React.useState(null);
  const refresh = React.useCallback(() => {
    setError(null);
    return getReadiness().then(data => { setState(data); onReady?.(data.generation_ready === true); }).catch(e => { setError(e.message); onReady?.(false); });
  }, []);
  React.useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    window.addEventListener('focus', refresh);
    return () => { clearInterval(timer); window.removeEventListener('focus', refresh); };
  }, [refresh]);
  const accept = async () => {
    try { await reviewProfile(review.revision); setReview(null); await refresh(); }
    catch(e) { setError(e.status === 409 ? 'The profile changed. Open and review the current profile again.' : e.message); setReview(null); await refresh(); }
  };
  return <section className="review-readiness" aria-label="Generation readiness">
    <h3>{error ? 'Readiness check failed' : !state ? 'Checking readiness…' : state.generation_ready ? 'Ready to create a resume' : 'Setup needs attention'}</h3>
    {error && <p role="alert">{error}</p>}
    {state && <><dl>{['profile','provider','parser','compiler','renderer'].map(key => <div key={key}><dt>{key}</dt><dd>{state[key]?.status || 'Unknown'}</dd></div>)}</dl>
      {state.provider?.status === 'configured_unverified' && <p>Provider configured. Authentication has not been verified.</p>}
      {state.next_steps?.length > 0 && <ul>{state.next_steps.map((step,i) => <li key={i}>{step}</li>)}</ul>}
      {state.profile?.status === 'review_required' && <Button onClick={async () => { try { setReview(await getProfile()); } catch(e) { setError(e.message); } }}>Review current base resume</Button>}
      {!state.generation_ready && <Button variant="ghost" onClick={() => goto?.('setup')}>Open setup</Button>}
    </>}
    {review && <section aria-label="Current profile review"><h4>Review the current base resume</h4><FieldValue value={review.profile}/><Button variant="primary" onClick={accept}>Confirm this profile</Button>{' '}<Button onClick={() => setReview(null)}>Close review</Button></section>}
    {error && <Button onClick={refresh}>Retry readiness check</Button>}
  </section>;
}

export function ReviewFlow({ run, onState }) {
  const pending = run.pending;
  const kind = pending.kind;
  const draft = useFormDraft({ form: kind === 'ask_missing' ? 'questions' : 'content', run: run.thread_id || run.id,
    review: reviewIdentity(pending), revision: run.source_revision || run.fixed_input_hashes?.profile_revision || pending.source_revision }, kind === 'ask_missing' ? {answers:{}} : {selected:[]});
  const [preview, setPreview] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [conflict, setConflict] = React.useState(false);
  const nextAction = React.useRef(actionForRetry());
  const runId = run.thread_id || run.id;
  const selected = draft.value.selected || [];
  const selectionKey = JSON.stringify(selected);
  const selectionRef = React.useRef(selectionKey); selectionRef.current = selectionKey;
  React.useEffect(() => { setPreview(null); }, [selectionKey]);
  const reconcile = value => {
    if (kind === 'ask_missing') draft.edit({answers:Object.fromEntries(pending.question_ids.map(id => [id,value.answers?.[id] || '']))});
    else draft.edit({selected:(value.selected || []).filter(id => pending.proposal_ids.includes(id))});
    setPreview(null);
  };
  const submit = async value => {
    if (busy || conflict) return;
    setBusy(true); setError(null);
    try {
      const action = nextAction.current(reviewAction(pending, value));
      const result = await resumeRun(runId, action);
      await draft.clear();
      onState(result);
    } catch(e) { setError(e.status === 409 ? 'This review changed. Refresh the run and reconcile your saved edits before submitting again.' : e.message); if(e.status === 409) setConflict(true); }
    finally { setBusy(false); }
  };
  const queryPreview = async () => {
    setBusy(true); setError(null); setPreview(null);
    const requested = selectionKey;
    try {
      const result = await contentPreview(runId,{review_id:pending.review_id,source_revision:pending.source_revision,approved_ids:selected});
      if (selectionRef.current === requested) setPreview(result);
    } catch(e) { setError(e.message); if(e.status === 409) setConflict(true); }
    finally { setBusy(false); }
  };
  const proposals = pending.payload?.proposals || [];
  return <div className="run-activity review-flow" style={{padding:24}}>
    {error && <p role="alert">{error}</p>}
    {conflict && <Button onClick={() => onState(null)}>Refresh current review</Button>}
    <DraftNotice draft={draft} reconcile={reconcile}/>
    <fieldset disabled={busy || !draft.loaded || conflict} style={{border:0,padding:0,minWidth:0}}>
      {kind === 'ask_missing' && <>
        <h2>Quick questions about your experience</h2><p>Answer honestly. Blank answers mean you are skipping those questions.</p>
        {(pending.payload?.questions || []).map(q => <label className="review-question" key={q.id}>
          <strong>{q.prompt}</strong><span>{q.why_asking}</span>
          <Textarea aria-label={q.prompt} placeholder="Your answer…" value={draft.value.answers?.[q.id] || ''} onChange={e => draft.edit(v => ({answers:{...v.answers,[q.id]:e.target.value}}))}/>
        </label>)}
        <Button variant="ghost" onClick={() => submit({answers:{}})}>Skip all</Button>{' '}
        <Button variant="primary" onClick={() => submit(draft.value)}>Submit answers</Button>
      </>}
      {kind === 'present_suggestions' && <>
        <h2>Suggested rewrites</h2><p>{selected.length} of {proposals.length} selected. Every proposal starts unselected.</p>
        {proposals.length === 0 && <p>No wording changes were proposed. Review the complete content before continuing.</p>}
        {proposals.map(proposal => <article className="review-proposal" key={proposal.id}>
          <label><input type="checkbox" aria-label={`Select ${targetLabel(proposal.target_path, pending.payload?.snapshot?.profile)}`} checked={selected.includes(proposal.id)} onChange={e => draft.edit({selected:e.target.checked ? [...selected,proposal.id] : selected.filter(id => id !== proposal.id)})}/> Select change to {targetLabel(proposal.target_path, pending.payload?.snapshot?.profile)}</label>
          <p>{proposal.rationale}</p><dl><dt>Before</dt><dd><FieldValue value={proposal.before ?? pointerValue(pending.payload?.snapshot?.profile,proposal.target_path)}/></dd><dt>After</dt><dd>{proposal.after ?? proposal.proposed_text ?? (proposal.operation === 'omit_from_display' ? 'Omit from display' : '')}</dd></dl>
          <h4>Evidence</h4><ul>{proposal.source_refs.map((ref,index) => <li key={index}>{ref.kind === 'profile' ? targetLabel(ref.target_path,pending.payload?.snapshot?.profile) : 'Your supplied answer'}{ref.quote && <>: {ref.quote}</>}</li>)}</ul>
        </article>)}
        <Button onClick={() => { draft.edit({selected:[]}); setPreview(null); }}>Reject all changes</Button>{' '}
        <Button onClick={queryPreview}>Review complete content</Button>
        <DisplayProjection preview={preview}/>
        {preview && <Button variant="primary" onClick={() => submit({...draft.value,preview})}>Confirm this content</Button>}
      </>}
      {kind === 'review_pdf' && <>
        <h2>Review the PDF</h2><p>{pending.payload?.page_count ?? 'Unknown'} pages · {pending.review.template_version} · {pending.review.layout_id}</p>
        <iframe title="Current PDF preview" className="review-pdf" src={previewUrl(runId)}/>
        <h3>Layout and advisory checks</h3><AdvisoryList records={pending.payload?.advisories || []}/>
        <p>Approve these exact preview bytes to release your download.</p>
        <Button variant="primary" onClick={() => submit({decision:'approve'})}>Approve and release PDF</Button>{' '}
        <Button onClick={() => submit({decision:'reject'})}>Reject PDF</Button>
      </>}
    </fieldset>
  </div>;
}
function pointerValue(profile,path) {
  return (path || '').split('/').slice(1).reduce((value,key) => value?.[key.replace(/~1/g,'/').replace(/~0/g,'~')],profile);
}

export function DurableRunState({ run, onState, goto }) {
  const [error,setError] = React.useState(null);
  const [busy,setBusy] = React.useState(false);
  const nextAction = React.useRef(actionForRetry());
  const id = run.thread_id || run.id;
  const act = async fn => { setBusy(true); setError(null); try { onState(await fn()); } catch(e) { setError(e.message); } finally { setBusy(false); } };
  return <div className="run-activity review-flow" style={{padding:24}}>
    {error && <p role="alert">{error}</p>}
    {run.legacy && run.status !== 'complete' && <section><h2>Legacy run needs fresh review</h2><p>Recovery creates a linked run and asks for new content and PDF decisions.</p><Button disabled={busy} onClick={() => act(() => recoverRun(id))}>Recover as a reviewed run</Button></section>}
    {run.status === 'complete' ? <>
      <h2>Resume completed</h2>
      {run.artifact_status === 'legacy_unverified' ? <><p>Legacy PDF · unverified. This file predates the reviewed workflow.</p><Button onClick={() => downloadPdf(id)}>Download unverified legacy PDF</Button></>
        : run.artifact_status === 'available' && run.release?.status === 'released' ? <><Button variant="primary" onClick={() => downloadPdf(id)}>Download PDF</Button>
          {!run.export_available && <><p>The saved export copy is missing. The approved PDF is still available.</p><Button disabled={busy} onClick={() => act(() => reexportRun(id,run.pending_reexport ? {...run.pending_reexport,recover:true} : nextAction.current({expected_pdf_hash:run.release.pdf_hash})))}>Restore export copy</Button></>}
          {run.pending_reexport && run.export_available && <Button disabled={busy} onClick={() => act(() => reexportRun(id,{...run.pending_reexport,recover:true}))}>Continue interrupted export</Button>}</>
        : <><h3>Released artifact unavailable</h3><p>The export is missing or its canonical PDF could not be verified. Reexport checks the approved hash before restoring the file.</p><Button disabled={busy || !run.release?.pdf_hash} onClick={() => act(() => reexportRun(id,nextAction.current({expected_pdf_hash:run.release.pdf_hash})))}>Reexport verified PDF</Button></>}
    </> : run.status === 'cancelled' ? <><h2>Run cancelled</h2><p>Your draft and review history are retained.</p></>
      : run.status === 'failed' ? <><h2>Generation failed</h2><p>{run.error || 'A required check failed.'}</p><pre>{JSON.stringify(run.diagnostics,null,2)}</pre><Button onClick={() => goto?.('new')}>Try again</Button>{' '}<Button onClick={() => goto?.('resume')}>Edit base resume</Button></>
      : run.cancellation_requested ? <><h2>Cancellation requested</h2><p>Waiting for the current operation to stop safely.</p></>
      : run.status === 'interrupted' && !run.pending && !run.legacy ? <><h2>Run interrupted</h2><p>Continue explicitly from the saved stage.</p><Button variant="primary" disabled={busy} onClick={() => act(() => resumeRun(id,nextAction.current({kind:'continue'})))}>Continue run</Button></>
      : <><h2>{run.stage || 'Generating your tailored resume…'}</h2><p>The latest saved state refreshes automatically.</p>{run.contract_version !== 2 && <Button disabled={busy} onClick={() => act(() => recoverRun(id))}>Recover as a reviewed run</Button>}</>}
  </div>;
}

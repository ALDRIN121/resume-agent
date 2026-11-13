// Only form answers belong here. Provider configuration never enters this store.
const FIELDS = {
  'new-run': ['tab', 'text', 'url', 'jobLocation', 'workMode', 'maxPages'],
  questions: ['answers'], content: ['selected'],
};
export const draftKey = identity => JSON.stringify(['v2', identity.form, identity.run || '', identity.review || '', identity.revision || '']);
export function safeFormValue(form, value) {
  if (!FIELDS[form]) throw new Error('Unsupported draft form');
  return Object.fromEntries(FIELDS[form].filter(key => key in value).map(key => [key, value[key]]));
}
export function matchingDrafts(records, identity) {
  const relevant = records.filter(row => row.identity.form === identity.form && row.identity.run === identity.run);
  return { exact: relevant.find(row => draftKey(row.identity) === draftKey(identity)), stale: relevant.filter(row => draftKey(row.identity) !== draftKey(identity)) };
}
export function createDraftStore(indexedDB = globalThis.indexedDB) {
  let database;
  const open = () => database ||= new Promise((resolve, reject) => {
    if (!indexedDB) { reject(new Error('Draft storage unavailable. Keep this page open to retain edits.')); return; }
    const request = indexedDB.open('resume-agent-form-drafts', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('drafts', { keyPath: 'key' });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error('Draft storage unavailable. Keep this page open to retain edits.'));
  });
  const execute = async (mode, fn) => {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('drafts', mode);
      const request = fn(tx.objectStore('drafts'));
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = tx.onabort = () => reject(new Error('Could not save form draft. Keep this page open to retain edits.'));
    });
  };
  return {
    list: () => execute('readonly', s => s.getAll()),
    put: (identity, value) => execute('readwrite', s => s.put({ key: draftKey(identity), identity, value: safeFormValue(identity.form, value) })),
    remove: identity => execute('readwrite', s => s.delete(draftKey(identity))),
  };
}
export const draftStore = createDraftStore();
export const reviewIdentity = p => p?.review_id || p?.request_id || p?.review?.review_id || '';
export const sameReview = (a, b) => a?.kind === b?.kind && reviewIdentity(a) === reviewIdentity(b) && a?.source_revision === b?.source_revision;
export function actionForRetry(uuid = () => crypto.randomUUID()) {
  let previous, id;
  return body => {
    const key = JSON.stringify(body);
    if (key !== previous) { previous = key; id = uuid(); }
    return { ...body, action_id: id };
  };
}
export function reviewAction(pending, value) {
  if (pending.kind === 'ask_missing') return {
    kind: pending.kind, request_id: pending.request_id,
    answers: Object.fromEntries(pending.question_ids.map(id => [id, value.answers?.[id] || ''])),
  };
  if (pending.kind === 'present_suggestions') {
    const selected = value.selected || [];
    const manifest = value.preview?.manifest;
    if (!manifest?.content_hash || manifest.source_revision !== pending.source_revision ||
        JSON.stringify([...manifest.approved_proposal_ids].sort()) !== JSON.stringify([...selected].sort())) throw new Error('Review the current content preview before confirming.');
    return { kind: pending.kind, review_id: pending.review_id, source_revision: pending.source_revision, approved_ids: selected, content_hash: manifest.content_hash };
  }
  if (pending.kind === 'review_pdf') {
    if (!['approve', 'reject'].includes(value.decision)) throw new Error('Choose an explicit PDF decision.');
    const { review_id, content_hash, render_hash, pdf_hash } = pending.review;
    return { kind: pending.kind, review_id, content_hash, render_hash, pdf_hash, decision: value.decision };
  }
  throw new Error('This review cannot be submitted from this form.');
}

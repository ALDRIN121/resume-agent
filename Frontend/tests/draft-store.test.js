import test from 'node:test';
import assert from 'node:assert/strict';
import { draftKey, matchingDrafts, safeFormValue, createDraftStore } from '../src/draft-store.js';
test('draft identity includes form, run, review and fixed profile revision', () => {
 const a={form:'questions',run:'r1',review:'q1',revision:'v1'};
 assert.notEqual(draftKey(a),draftKey({...a,review:'q2'}));
 assert.notEqual(draftKey(a),draftKey({...a,revision:'v2'}));
 assert.deepEqual(matchingDrafts([{identity:a,value:{q1:'hello'}}],{...a,review:'q2'}).stale[0].value,{q1:'hello'});
});
test('only explicitly allowed non-secret form fields are persisted', () => {
 assert.deepEqual(safeFormValue('new-run',{text:'job',apiKey:'secret',provider:'secret',maxPages:2}),{text:'job',maxPages:2});
 assert.throws(()=>safeFormValue('settings',{apiKey:'secret'}));
});
test('unavailable storage rejects visibly instead of losing current edits', async () => {
 const store=createDraftStore(null);
 await assert.rejects(store.put({form:'questions',run:'r',review:'q',revision:'v'},{answers:{q:'a'}}),/Draft storage unavailable/);
});

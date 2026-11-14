import test from 'node:test';
import assert from 'node:assert/strict';
import { reviewAction, actionForRetry, sameReview } from '../src/draft-store.js';
test('questions bind exact IDs and answers',()=>{
 const p={kind:'ask_missing',request_id:'q1',question_ids:['a','b']};
 assert.deepEqual(reviewAction(p,{answers:{a:'yes',rogue:'no'}}),{kind:'ask_missing',request_id:'q1',answers:{a:'yes',b:''}});
});
test('content cannot be approved without a matching current preview',()=>{
 const p={kind:'present_suggestions',review_id:'c1',source_revision:'v1',proposal_ids:['p1']};
 assert.throws(()=>reviewAction(p,{selected:[]}),/preview/);
 const preview={manifest:{source_revision:'v1',approved_proposal_ids:[],content_hash:'hash'}};
 assert.deepEqual(reviewAction(p,{selected:[],preview}),{kind:p.kind,review_id:'c1',source_revision:'v1',approved_ids:[],content_hash:'hash'});
 assert.throws(()=>reviewAction(p,{selected:['p1'],preview}),/preview/);
});
test('PDF actions bind all three hashes and require an explicit decision',()=>{
 const p={kind:'review_pdf',review:{review_id:'pdf1',content_hash:'c',render_hash:'r',pdf_hash:'p'}};
 assert.throws(()=>reviewAction(p,{}),/decision/);
 assert.deepEqual(reviewAction(p,{decision:'reject'}),{kind:'review_pdf',review_id:'pdf1',content_hash:'c',render_hash:'r',pdf_hash:'p',decision:'reject'});
});
test('same payload retries reuse action ID; editing creates a new action ID',()=>{
 let n=0; const next=actionForRetry(()=>String(++n));
 assert.equal(next({kind:'continue'}).action_id,next({kind:'continue'}).action_id);
 assert.notEqual(next({kind:'continue'}).action_id,next({kind:'ask_missing'}).action_id);
 assert.equal(sameReview({kind:'ask_missing',request_id:'a'},{kind:'ask_missing',request_id:'b'}),false);
});

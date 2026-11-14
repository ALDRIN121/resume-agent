import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto, createHash } from 'node:crypto';
import { factTargets, stringHash } from '../src/memory-draft.js';

test('fact choices preserve exact Unicode strings and escape pointer keys',async()=>{
  const profile={summary:'C++ — 450ms → 90ms',skills:{'A/B~C':['C#']},work_preferences:{preferred_locations:['Somewhere']}};
  const targets=factTargets(profile);
  assert.deepEqual(targets.map(t=>t.path),['/summary','/skills/A~1B~0C/0']);
  assert.equal(await stringHash(profile.summary,webcrypto),createHash('sha256').update(JSON.stringify(profile.summary)).digest('hex'));
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { reexportRun } from '../src/api/client.js';

test('reexport refreshes the durable run rather than replacing it with an export receipt', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (path, options) => {
    calls.push([path, options]);
    return {ok:true, json:async () => options?.method === 'POST'
      ? {status:'complete',destination:'/output/file.pdf'}
      : {id:'run-1',thread_id:'run-1',status:'complete',release:{pdf_hash:'hash'}}};
  };
  try {
    const result = await reexportRun('run-1', {action_id:'restore',expected_pdf_hash:'hash'});
    assert.equal(result.thread_id, 'run-1');
    assert.deepEqual(calls.map(([path]) => path), ['/api/runs/run-1/reexport','/api/runs/run-1']);
  } finally { globalThis.fetch = original; }
});

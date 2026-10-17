import { test } from 'node:test';
import assert from 'node:assert/strict';
import { subscribeRun } from '../src/api/ws.js';

for (const terminalType of ['complete', 'failed']) {
  test(`a ${terminalType} event stops reconnection`, () => {
    const sockets = [];
    const retries = [];
    globalThis.window = {
      location: { protocol: 'http:', host: '127.0.0.1:8000' },
      setTimeout: (fn) => { retries.push(fn); return 1; },
      clearTimeout: () => {},
    };
    globalThis.WebSocket = class {
      constructor() { sockets.push(this); }
      close() { this.onclose?.(); }
    };
    const events = [];
    const dispose = subscribeRun('sample', event => events.push(event));
    sockets[0].onopen();
    sockets[0].onmessage({ data: JSON.stringify({ type: terminalType }) });
    sockets[0].onclose();
    assert.equal(events.length, 1);
    assert.equal(retries.length, 0);
    dispose();
  });
}

test('an unexpected disconnect still reconnects an unfinished run', () => {
  const retries = [];
  let socket;
  globalThis.window = {
    location: { protocol: 'http:', host: '127.0.0.1:8000' },
    setTimeout: (fn) => { retries.push(fn); return 1; },
    clearTimeout: () => {},
  };
  globalThis.WebSocket = class {
    constructor() { socket = this; }
    close() { this.onclose?.(); }
  };
  const dispose = subscribeRun('sample', () => {});
  socket.onclose();
  assert.equal(retries.length, 1);
  dispose();
});

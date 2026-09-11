const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('active exam heartbeats once per minute and stops at expiry', async () => {
  const source = fs.readFileSync('static/platform-ui.js', 'utf8').split('\n').find(line => line.startsWith('function startServerTimer('));
  let now = 0, tick;
  const calls = [];
  const ctx = {Date: {now: () => now}, Number, Math, String, examTimerHandle: null,
    clearInterval: () => {}, setInterval: fn => {tick = fn; return 1;},
    $: () => ({}), notify: () => {}, openResultsAfterSubmit: () => {},
    api: path => {calls.push(path); return Promise.resolve({});}};
  vm.createContext(ctx); vm.runInContext(source, ctx);
  ctx.startServerTimer(7, 10800, 0);
  assert.deepEqual(calls, []);
  now = 60000; tick(); await new Promise(setImmediate);
  assert.deepEqual(calls, ['/api/auth/me']);
  now = 61000; tick(); assert.equal(calls.length, 1);
  now = 120000; tick(); await new Promise(setImmediate);
  assert.equal(calls.length, 2);
  now = 10800000; tick(); await new Promise(setImmediate);
  assert.equal(calls.at(-1), '/api/sessions/7/submit');
  assert.equal(calls.filter(path => path === '/api/auth/me').length, 2);
});

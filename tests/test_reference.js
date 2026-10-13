// Deterministic browser timer checks without a running HTTP server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const elements = new Map();
const element = id => {
  if (!elements.has(id)) elements.set(id, {
    hidden: false, disabled: false, textContent: '',
    removeAttribute(key) { delete this[key]; },
    addEventListener(event, action) { this[event] = action; }
  });
  return elements.get(id);
};
let now = 0, tick, state, finishDownload;
const revoked = [];
const context = vm.createContext({
  $: element, token: 'team-token', performance: {now: () => now},
  setInterval: action => { tick = action; },
  document: {addEventListener() {}},
  URL: {createObjectURL: () => 'blob:reference', revokeObjectURL: url => revoked.push(url)},
  json: async () => state,
  api: async () => ({blob: () => new Promise(resolve => { finishDownload = resolve; })}),
  guard: action => action()
});
vm.runInContext(fs.readFileSync('static/reference.js', 'utf8'), context);
const settle = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  state = {available: false, seconds_remaining: 30};
  tick(); await settle(); tick();
  assert.equal(element('load-reference').disabled, true);
  assert.equal(element('reference-timer').textContent, 'Next access in 30 seconds');
  now = 30000;
  state = {available: true, seconds_remaining: 30};
  tick(); await settle(); tick();
  assert.equal(element('load-reference').disabled, false);
  let loading = element('load-reference').click();
  await settle(); finishDownload({}); await loading;
  assert.equal(element('reference-preview').hidden, false);
  loading = element('load-reference').click();
  await settle();
  now = 60000;
  state = {available: false, seconds_remaining: 30};
  tick(); await settle(); tick();
  finishDownload({}); await loading;
  assert.equal(element('load-reference').disabled, true);
  assert.equal(element('reference-preview').hidden, true);
  assert.equal(element('reference-preview').src, undefined);
  assert.deepEqual(revoked, ['blob:reference']);
  vm.runInContext('resetReference()', context);
  assert.equal(element('load-reference').disabled, true);
  console.log('Reference timer, expiry, and late download checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });

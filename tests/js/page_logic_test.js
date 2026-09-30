// Runs the console page's own <script> against a fake DOM and scripted server states.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync(process.argv[2], 'utf8');
const js = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function makeEnv(states) {
  const els = {}, handlers = {}, posts = [];
  function el(id) {
    if (!els[id]) els[id] = {
      id, style: {}, className: '', textContent: '', innerHTML: '', hidden: false, dataset: {}, disabled: false,
      classList: { toggle() {} }, getAttribute() { return null; }, clientWidth: 0, clientHeight: 0,
      addEventListener(t, fn) { handlers[id + ':' + t] = fn; }, querySelector() { return null; }
    };
    return els[id];
  }
  let timer = null, i = 0, now = 0;
  const sandbox = {
    console, URLSearchParams, Promise, Math, Object, Array, Number, String, JSON, Date,
    document: { getElementById: el, querySelectorAll: () => [], querySelector: () => ({ id: 'v1' }) },
    window: { addEventListener() {}, devicePixelRatio: 1 },
    location: { search: '?t=abc', hash: '' }, history: { replaceState() {} },
    performance: { now: () => now },
    setInterval: (fn) => { timer = fn; }, encodeURIComponent,
    fetch: (url, opts) => {
      if (opts && opts.method === 'POST') { posts.push({ url, body: JSON.parse(opts.body) }); return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, path: '/x/runs/a-run.json' }) }); }
      const st = states[Math.min(i++, states.length - 1)];
      return Promise.resolve({ ok: true, json: () => Promise.resolve(st) });
    }
  };
  vm.runInNewContext(js, sandbox);
  return {
    el, handlers, posts,
    async tick() { timer(); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r)); }
  };
}

// state factory: sweeps seq0+1..seq0+n at 0.4 s spacing, values from fn(seq, t)
function statesFor(n, fn, seq0 = 0, t0 = 0) {
  const out = [];
  for (let k = 1; k <= n; k++) {
    const seq = seq0 + k, t = +(t0 + k * 0.4).toFixed(3), v = fn(seq, t), ch = {};
    Object.keys(v).forEach(pid => { ch[pid] = { name: pid, unit: '', samples: [[seq, t, v[pid]]] }; });
    out.push({ status: 'running', message: null, demo: true, seq, now: t, since_last_sample: 0.1, hz: 2.5, hz_measured: 2.5,
               seconds_left: 500, adapter: { chip: null, ati: 'SIM', protocol: 'SIM' }, channels: ch });
  }
  return out;
}
const idle = (s, t) => ({ '0C': 700, '05': 41, '06': -12, '07': -21, '08': -10, '09': -19, '10': 5, '42': 13.9 });
const rev = (s, t) => ({ '0C': 2500, '05': 41, '06': -11, '07': -21, '08': -10, '09': -19, '10': 46, '42': 13.9 });

(async () => {
  // 1) rich engine: idle capture, then 2500 rpm capture, then the verdict
  const all = statesFor(10, idle).concat(statesFor(45, idle, 10, 4), statesFor(60, rev, 55, 22));
  const env = makeEnv(all);
  for (let k = 0; k < 10; k++) await env.tick();
  assert(/LIVE/.test(env.el('chipLive').innerHTML), 'live chip');
  assert.strictEqual(env.el('pause').textContent, 'Stop sampling');
  env.handlers['go_idle:click']();
  for (let k = 0; k < 45; k++) await env.tick();
  assert.strictEqual(env.el('st_idle').className, 'step done', 'idle capture finishes after 15 s of sample time');
  assert(/Warm idle/.test(env.el('results').innerHTML) && /-21\.0/.test(env.el('results').innerHTML), 'idle row');
  assert.strictEqual(env.el('verdict').style.display, 'none', 'no verdict before both captures');
  env.handlers['go_rev:click']();
  for (let k = 0; k < 45; k++) await env.tick();
  assert.strictEqual(env.el('st_rev').className, 'step done');
  assert(/argues against a vacuum leak/.test(env.el('verdict').innerHTML), 'verdict for a rich engine');
  assert(/unreviewed/.test(env.el('verdict').innerHTML), 'verdict is labeled a draft');
  assert.strictEqual(env.el('st_cmp').className, 'step done');

  // 2) lean engine: high at idle, fading at 2500 rpm
  const lidle = (s, t) => Object.assign(idle(), { '07': 16 }), lrev = (s, t) => Object.assign(rev(), { '07': 3 });
  const env2 = makeEnv(statesFor(10, lidle).concat(statesFor(45, lidle, 10, 4), statesFor(60, lrev, 55, 22)));
  for (let k = 0; k < 10; k++) await env2.tick();
  env2.handlers['go_idle:click']();
  for (let k = 0; k < 45; k++) await env2.tick();
  env2.handlers['go_rev:click']();
  for (let k = 0; k < 45; k++) await env2.tick();
  assert(/unmetered air leak/.test(env2.el('verdict').innerHTML), 'verdict for a vacuum leak');

  // 3) capture is refused when not sampling; controls call the right endpoints
  const env3 = makeEnv([{ status: 'idle', message: null, demo: false, seq: 0, now: 0, since_last_sample: null, hz: null,
                          hz_measured: null, seconds_left: null, adapter: {}, channels: {} }]);
  await env3.tick();
  assert.strictEqual(env3.el('pause').textContent, 'Start sampling');
  assert(/NOT SAMPLING/.test(env3.el('chipLive').innerHTML));
  env3.handlers['go_idle:click']();
  assert(/Start sampling first/.test(env3.el('msg').textContent), 'must be sampling to capture');
  env3.handlers['pause:click']();
  await new Promise(r => setImmediate(r));
  const start = env3.posts.find(p => /\/api\/start/.test(p.url));
  assert(start && start.url.includes('t=abc') && start.body.pids.length === 8 && start.body.hz === 2.5, 'start request');
  assert.strictEqual(env3.el('simctl').hidden, true, 'sim controls hidden outside demo');

  // 4) a new run (seq restarts) resets the buffers instead of mixing runs
  const env4 = makeEnv(statesFor(5, idle).concat(statesFor(2, rev, 0, 0)));
  for (let k = 0; k < 7; k++) await env4.tick();
  assert(/2500/.test(env4.el('v1rpm').textContent), 'shows the new run');

  console.log('page logic OK');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });

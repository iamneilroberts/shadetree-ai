// Runs the console page's own <script> against a fake DOM and scripted server states.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync(process.argv[2], 'utf8');
const js = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function makeEnv(states, viewId = 'v1') {
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
    document: { getElementById: el, querySelectorAll: () => [], querySelector: () => ({ id: viewId }) },
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
    el, handlers, posts, sandbox,
    timer() { timer(); },
    async tick() { timer(); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r)); }
  };
}

// state factory: sweeps seq0+1..seq0+n at 0.4 s spacing, values from fn(seq, t)
function statesFor(n, fn, seq0 = 0, t0 = 0) {
  const out = [];
  for (let k = 1; k <= n; k++) {
    const seq = seq0 + k, t = +(t0 + k * 0.4).toFixed(3), v = fn(seq, t), ch = {};
    Object.keys(v).forEach(pid => { ch[pid] = { name: pid, unit: '', samples: [[seq, t, v[pid]]] }; });
    out.push({ status: 'running', run: 1, message: null, demo: true, seq, now: t, since_last_sample: 0.1, hz: 2.5, hz_measured: 2.5,
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

  // 5) adapter/ECU text is untrusted: it must reach the page as text, never as markup
  const evil = '<img src=x onerror=alert(1)//';
  const st5 = statesFor(2, idle);
  st5.forEach(s => { s.adapter = { chip: null, ati: evil, protocol: '<script>alert(2)</script>' }; s.message = '<b>x</b>'; });
  const env5 = makeEnv(st5);
  await env5.tick(); await env5.tick();
  assert.strictEqual(env5.el('chipConn').innerHTML, '', 'chipConn must not be built with innerHTML');
  assert(env5.el('chipConn').textContent.includes(evil), 'adapter text shown literally');
  assert.strictEqual(env5.el('msg').innerHTML, '', 'message bar must not use innerHTML');

  // 6) two polls never overlap: a slow response must not be raced by the next timer tick
  let calls = 0, release;
  const env6 = makeEnv([]);
  await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r));  // let the page's first poll settle
  {
    const pending = new Promise(r => { release = r; });
    const sb = env6.sandbox;
    sb.fetch = () => { calls++; return pending.then(() => ({ ok: true, json: () => Promise.resolve(statesFor(1, idle)[0]) })); };
  }
  env6.timer(); env6.timer(); env6.timer();
  assert.strictEqual(calls, 1, 'only one poll in flight at a time');
  release(); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r));

  // 7) a new run id resets the buffers even when its sequence numbers overtake the old ones
  const a = statesFor(3, idle, 0, 0);            // run 1: seq 1..3
  const b = statesFor(1, rev, 9, 50);            // run 2 already at seq 10
  b[0].run = 2;
  const env7 = makeEnv(a.concat(b), 'v2');       // the Scope view lists min/max over everything buffered
  for (let k = 0; k < 4; k++) await env7.tick();
  assert(/min 2500 · max 2500/.test(env7.el('rail').innerHTML), 'run 1 samples were dropped when run 2 began');

  // 8) sampling stopping mid-capture cancels the capture instead of leaving it stuck
  const run = statesFor(12, idle);
  const stopped = Object.assign({}, run[run.length - 1], { status: 'stopped', message: 'stopped' });
  const env8 = makeEnv(run.concat([stopped]));
  for (let k = 0; k < 12; k++) await env8.tick();
  env8.handlers['go_idle:click']();
  assert.strictEqual(env8.el('go_idle').disabled, true, 'capture started');
  await env8.tick();
  assert.strictEqual(env8.el('go_idle').disabled, false, 'button usable again after sampling stopped');
  assert(/stopped/.test(env8.el('tx_idle').textContent), 'says why');

  console.log('page logic OK');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });

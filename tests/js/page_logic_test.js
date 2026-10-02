// Runs the console page's own <script> against a fake DOM and scripted server states.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync(process.argv[2], 'utf8');
const js = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function makeNode(id, handlers) {
  const n = {
    id, style: {}, className: '', innerHTML: '', hidden: false, dataset: {}, disabled: false, type: '',
    clientWidth: 0, clientHeight: 0, offsetWidth: 0, offsetHeight: 0, children: [], attrs: {}, _t: '', on: {},   // on: this node's listeners (created nodes all share the id 'new')
    classList: { toggle(c, want) { const cs = n.className.split(' ').filter(x => x && x !== c); if (want === undefined ? !n.className.split(' ').includes(c) : want) cs.push(c); n.className = cs.join(' '); } },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    appendChild(c) { this.children = this.children.filter(x => x !== c); this.children.push(c); return c; },
    insertBefore(c, ref) { const cs = this.children.filter(x => x !== c), at = cs.indexOf(ref); cs.splice(at < 0 ? cs.length : at, 0, c); this.children = cs; return c; },
    removeChild(c) { this.children = this.children.filter(x => x !== c); return c; },
    contains(t) { return t === this || this.children.some(c => c.contains(t)); },
    closest(sel) { return sel[0] === '.' && this.className.split(' ').includes(sel.slice(1)) ? this : null; },
    getBoundingClientRect() { return { left: 0, top: 0, bottom: 0, right: 0 }; },
    addEventListener(t, fn) { handlers[id + ':' + t] = fn; this.on[t] = fn; }, querySelector() { return null; }
  };
  Object.defineProperty(n, 'textContent', { get() { return this._t; }, set(v) { this._t = v; this.children = []; } });
  return n;
}

function makeEnv(states, viewId = 'v0', help = null, runs = [], store = {}, page = {}) {   // page: { search, hash, views (view nodes the page toggles is-active on), absent (ids getElementById answers null for), postReply(url, body), prefersLight, narrow, storageThrows }
  const els = {}, handlers = {}, docHandlers = {}, winH = {}, posts = [];
  let parts = null;   // the page hands its shared parts to window.__shadetreeParts
  function el(id) { return els[id] || (els[id] = makeNode(id, handlers)); }
  (page.views || []).forEach(v => { els[v.id] = v; });   // page.views: real view sections, so show() toggling is observable
  // the Handheld panes and nav buttons, built from the page's own markup so they start as the page starts them
  const hhPanes = [...html.matchAll(/<div class="hh-pane" data-mode="(\w+)" id="(\w+)"( hidden)?>/g)].map(m => { const n = el(m[2]); n.dataset.mode = m[1]; n.hidden = !!m[3]; return n; });
  const hhNav = html.match(/<nav class="hh-nav">([\s\S]*?)<\/nav>/);
  const hhBtns = hhNav ? [...hhNav[1].matchAll(/<button data-mode="(\w+)"( class="on")?>/g)].map(m => { const b = makeNode('hh_' + m[1], handlers); b.dataset.mode = m[1]; b.className = m[2] ? 'on' : ''; return b; }) : [];
  let timer = null, i = 0, now = 0;
  const sandbox = {
    console, URLSearchParams, Promise, Math, Object, Array, Number, String, JSON, Date, parseInt, isFinite,
    document: { documentElement: el('html'), getElementById: (id) => ((page.absent || []).includes(id) ? null : el(id)),
                querySelectorAll: (sel) => (sel === '.vbtn' ? (page.vbtns || []) : sel === '.view' ? (page.views || []) : sel === '.hh-pane' ? hhPanes : sel === '.hh-nav button' ? hhBtns : []),
                querySelector: (sel) => (page.views && sel === '.view.is-active' ? page.views.find(v => v.className.split(' ').includes('is-active')) || null : { id: viewId }),
                createElement: () => makeNode('new', handlers), addEventListener(t, fn) { docHandlers[t] = fn; } },
    window: { addEventListener(t, fn) { (winH[t] = winH[t] || []).push(fn); }, devicePixelRatio: 1, innerWidth: 500, innerHeight: 800, __shadetreeParts: page.noHook ? undefined : (p) => { parts = p; } },
    location: { search: page.search || '?t=abc', hash: page.hash || '' }, history: { replaceState() {} },
    performance: { now: () => now },
    setInterval: (fn) => { timer = fn; }, encodeURIComponent,
    fetch: (url, opts) => {
      if (opts && opts.method === 'POST') {
        const body = JSON.parse(opts.body), r = page.postReply && page.postReply(url, body);
        posts.push({ url, body });
        if (r) return Promise.resolve({ ok: r.ok, status: r.status, json: () => Promise.resolve(r.j) });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true, path: '/x/runs/a-run.json' }) });
      }
      if (/\/api\/runs/.test(url)) return Promise.resolve({ ok: true, json: () => Promise.resolve(Array.isArray(runs) ? { runs } : runs) });
      if (/\/api\/scenarios(\?|$)/.test(url)) return Promise.resolve(page.scenariosFail ? { ok: false, json: () => Promise.resolve({}) } : { ok: true, json: () => Promise.resolve({ scenarios: page.scenarios || [] }) });
      if (/\/api\/help/.test(url)) return Promise.resolve(help ? { ok: true, json: () => Promise.resolve(help) } : { ok: false, json: () => Promise.resolve({}) });
      const st = states[Math.min(i++, states.length - 1)];
      return Promise.resolve({ ok: true, json: () => Promise.resolve(st) });
    }
  };
  if (store !== null) sandbox.localStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } };
  if (page.storageThrows) sandbox.localStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); } };
  if (page.prefersLight !== undefined || page.narrow !== undefined)   // a width query answers page.narrow, a colour-scheme query page.prefersLight
    sandbox.window.matchMedia = (q) => ({ matches: /max-width/.test(q) ? !!page.narrow : /light/.test(q) === !!page.prefersLight });
  vm.runInNewContext(js, sandbox);
  return {
    el, handlers, docHandlers, winH, posts, sandbox, store, hhBtns, parts: () => parts,
    timer() { timer(); }, setHelp(h) { help = h; }, advance(ms) { now += ms; },
    async tick() { timer(); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r)); }
  };
}

function walk(n, f) { f(n); (n.children || []).forEach(c => walk(c, f)); }
function flat(n) { let s = n.textContent || ''; (n.children || []).forEach(c => { s += ' ' + flat(c); }); return s; }
function findQ(root, key) { let r = null; walk(root, n => { if (n.className === 'q' && n.getAttribute('data-help') === key) r = n; }); return r; }

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
  assert(/SIMULATED/.test(env.el('chipLive').innerHTML) && !/LIVE/.test(env.el('chipLive').innerHTML), 'a demo run says SIMULATED, never LIVE');
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
  const lidle = (s, t) => Object.assign(idle(), { '07': 16, '09': 15 }), lrev = (s, t) => Object.assign(rev(), { '07': 3, '09': 2 });   // both banks lean: a verdict needs every bank to agree
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
  assert.strictEqual(env3.el('simctl').hidden, true, 'sim controls (and the Demo button in them) hidden outside demo');
  // a --demo console comes up idle: its Demo button starts the simulated run, and hides while it runs
  const demoIdle = { status: 'idle', message: null, demo: true, seq: 0, now: 0, since_last_sample: null, hz: null, hz_measured: null, seconds_left: null, adapter: {}, channels: {} };
  const dm = makeEnv([demoIdle, demoIdle, Object.assign({}, demoIdle, { status: 'running' })]);
  await dm.tick();
  assert.strictEqual(dm.el('simctl').hidden, false); assert.strictEqual(dm.el('demoBtn').hidden, false, 'Demo button shown on an idle demo console');
  dm.handlers['demoBtn:click']();
  await new Promise(r => setImmediate(r));
  const dstart = dm.posts.find(p => /\/api\/start/.test(p.url));
  assert(dstart && dstart.url.includes('t=abc') && dstart.body.pids.length === 8 && dstart.body.hz === 2.5, 'Demo starts the run like Start sampling');
  for (let k = 0; k < 2; k++) await dm.tick();
  assert.strictEqual(dm.el('demoBtn').hidden, true, 'hidden while the simulated run is going');

  // "Capture all supported": unticked, Start sends the same request as before; ticked, it adds capture: 'all' (Demo too); locked while running
  assert(!('capture' in start.body), 'the default start request is unchanged');
  const ca = makeEnv([demoIdle, demoIdle, Object.assign({}, demoIdle, { status: 'running', channels: { '05': { name: 'coolant_temp', unit: 'C', samples: [] } }, tiers: { fast: ['0C'], slow: ['05', '42'], slow_per_sweep: 1 } })], 'v6');
  await ca.tick();
  assert.strictEqual(ca.el('capAll').disabled, false, 'the option can be changed before a run');
  ca.el('capAll').checked = true;
  ca.handlers['pause:click'](); ca.handlers['demoBtn:click']();
  await new Promise(r => setImmediate(r));
  const cstarts = ca.posts.filter(p => /\/api\/start/.test(p.url));
  assert(cstarts.length === 2 && cstarts.every(p => p.body.capture === 'all' && p.body.pids.length === 8 && p.body.hz === 2.5), 'capture all on both buttons');
  for (let k = 0; k < 2; k++) await ca.tick();
  assert.strictEqual(ca.el('capAll').disabled, true, 'locked while a run is going: it only applies at Start');
  assert(/all supported: 1 fast every sweep, 2 slow in rotation/.test(ca.el('x_count').textContent), ca.el('x_count').textContent);

  // 4) a new run (seq restarts) resets the buffers instead of mixing runs
  const env4 = makeEnv(statesFor(5, idle).concat(statesFor(2, rev, 0, 0)), 'v3');
  for (let k = 0; k < 7; k++) await env4.tick();
  assert(/2500/.test(env4.el('v3rpm').textContent), 'shows the new run');

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
  const base0 = () => ({ '0C': 700, '05': 90, '06': 2, '07': 1, '08': 2, '09': 1, '0B': 36 });
  const a = statesFor(3, () => Object.assign(base0(), { '42': 15.4 }), 0, 0);    // run 1: seq 1..3, battery 15.4 V
  const b = statesFor(1, () => Object.assign(base0(), { '42': 12.1 }), 9, 1.2);  // run 2 already at seq 10, battery 12.1 V
  b[0].run = 2;
  const NOGAUGES = () => ({ 'shadetree.scen.general': '[]' });   // General with no gauges shows all five health tiles (the strip hides a tile its gauges repeat)
  const env7 = makeEnv(a.concat(b), 'v0', { pids: { '42': { title: 'Battery', measures: 'x', use: [], typical: '', status: [], watch: { ok: [13.2, 14.8], out: [11.5, 15.5] } } }, mode06: {} }, [], NOGAUGES());
  for (let k = 0; k < 5; k++) await env7.tick();
  let vt = null; walk(env7.el('o_tiles'), n => { if (n.getAttribute('data-key') === 'volts') vt = n; });
  let vbig = null; walk(vt, n => { if (n.className === 'big') vbig = n; });
  assert.strictEqual(vbig.textContent, '12.1', 'run 1 samples were dropped when run 2 began: battery reads 12.1, not the old 15.4');

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

  // 3) retro layouts D (cabinet) and E (handheld): trouble codes reach the page, escaped, with honest empty states
  const withCodes = (n, codes, status = 'running') => statesFor(n, idle).map(st => Object.assign(st, { status, codes }));
  const CODES = { read: true, note: null, mil: true,
    stored: [{ code: 'P0117', desc: 'Engine coolant temperature circuit low input', hint: 'Reads colder than real', known: true },
             { code: 'P0172', desc: '<img src=x onerror=alert(1)>', hint: '', known: false }],
    pending: [{ code: 'P0175', desc: 'System too rich (bank 2)', hint: 'Seen once', known: true }], permanent: [] };
  const codesOf = (e) => { let r = null; walk(e.el('d_codes_mount'), n => { if (n.id === 'd_codes') r = n; }); return r.innerHTML; };
  const cab = makeEnv(withCodes(3, CODES), 'v0');
  for (let k = 0; k < 3; k++) await cab.tick();
  const rows = codesOf(cab);
  assert(/P0117/.test(rows) && /STORED/.test(rows) && /PENDING/.test(rows) && /P0175/.test(rows), 'the Dashboard lists stored and pending codes');
  assert(!/<img/.test(rows) && /&lt;img/.test(rows), 'adapter/ECU-derived text is escaped, never markup');
  const cabNote = makeEnv(withCodes(3, { read: false, note: 'trouble codes not supported yet on SAE J1850 PWM protocol' }), 'v0');
  for (let k = 0; k < 3; k++) await cabNote.tick();
  assert(/NOT SUPPORTED YET/.test(codesOf(cabNote)), 'unsupported bus is stated on the Dashboard');
  const hh = makeEnv(withCodes(3, CODES), 'v5');
  for (let k = 0; k < 3; k++) await hh.tick();
  assert.strictEqual(hh.el('h_n').textContent, '3 CODES');
  assert(/P0117/.test(hh.el('h_codes').innerHTML) && /Reads colder than real/.test(hh.el('h_codes').innerHTML) && !/<img/.test(hh.el('h_codes').innerHTML), 'handheld cards');
  assert.strictEqual(hh.el('h_live').textContent, 'SIMULATED'); assert.strictEqual(hh.el('h_miltxt').textContent, 'Check engine ON');
  assert(/Check engine \(MIL\)/.test(hh.el('h_lamps').innerHTML) && /Sampling/.test(hh.el('h_lamps').innerHTML), 'the Lamps strip in Live');
  const hhWait = makeEnv(withCodes(3, { read: false, note: null }, 'idle'), 'v5');
  for (let k = 0; k < 3; k++) await hhWait.tick();
  assert.strictEqual(hhWait.el('h_n').textContent, '-- CODES'); assert.strictEqual(hhWait.el('h_live').textContent, 'NOT SAMPLING');
  assert.strictEqual(hhWait.el('h_miltxt').textContent, 'Check engine ?'); assert(/START SAMPLING TO READ CODES/.test(hhWait.el('h_codes').innerHTML));

  // 4) car chip: partial-VIN key, seen-before count, honest notes, never markup
  const withCar = (vehicle) => makeEnv(statesFor(3, idle).map(st => Object.assign(st, { vehicle })));
  const carText = async (vehicle) => { const e = withCar(vehicle); for (let k = 0; k < 3; k++) await e.tick(); return e.el('chipCar'); };
  const seen = (await carText({ key: 'ABCDEFGH-P', known: true, runs: 3, note: null })).textContent;
  assert(/ABCDEFGH-P/.test(seen) && /seen 3 times/.test(seen), 'known car shows key and run count');
  assert(/seen 1 time$/.test((await carText({ key: 'ABCDEFGH-P', known: true, runs: 1, note: null })).textContent), 'singular');
  assert(/new/.test((await carText({ key: 'ABCDEFGH-P', known: false, runs: 0, note: null })).textContent), 'first run says new');
  assert(/did not report a VIN/.test((await carText({ key: null, known: false, runs: 0, note: 'the car did not report a VIN' })).textContent), 'note shown when no key');
  assert.strictEqual((await carText(undefined)).textContent, 'car ?', 'no vehicle field');
  const evilCar = await carText({ key: null, known: false, runs: 0, note: '<img src=x onerror=1>' });
  assert.strictEqual(evilCar.innerHTML, '', 'chipCar is text only'); assert(evilCar.textContent.includes('<img src=x onerror=1>'), 'note shown literally');

  // 5) help popups: catalog text is shown as text, one panel at a time, closes on Escape/outside click, stays on screen
  const HELPFIX = { pids: { '04': { title: 'Engine load', measures: '<img src=x onerror=1>', use: ['first tip', 'second tip'],
                                     typical: 'about 15-30 % at idle', status: ['model_drafted', 'unreviewed'] } },
                    mode06: { evap: { title: 'EVAP leak test', measures: 'Checks the fuel vapor system.', use: ['a', 'b'], typical: 'pass',
                                      status: ['model_drafted', 'unreviewed'] } } };
  const m06 = { read: true, note: null, mids: ['3A'], results: [{ mid: '3A', tid: '01', uasid: '10', value: 1, minimum: 0, maximum: 5, within_limits: true }] };
  const extraStates = statesFor(4, () => Object.assign(idle(), { '04': 28, '99': 7 })).map(st => Object.assign(st, { mode06: m06 }));
  const hp = makeEnv(extraStates, 'v6', HELPFIX);
  for (let k = 0; k < 5; k++) await hp.tick();
  const panel = hp.el('helpPanel');
  const q04 = findQ(hp.el('x_grid'), '04');
  assert(q04, 'every extra reading card has a ? button');
  hp.docHandlers.click({ target: q04 });
  assert.strictEqual(panel.className, 'open');
  assert(flat(panel).includes('<img src=x onerror=1>') && panel.innerHTML === '', 'catalog text is shown as text');
  assert(/first tip/.test(flat(panel)) && /now 28/.test(flat(panel)) && /not yet reviewed/.test(flat(panel)), 'tips, live value, unreviewed tag');
  hp.docHandlers.click({ target: findQ(hp.el('x_grid'), '04') });
  assert.strictEqual(panel.className, '', 'the same ? again closes it');
  hp.docHandlers.click({ target: q04 }); hp.docHandlers.keydown({ key: 'Escape' });
  assert.strictEqual(panel.className, '', 'Escape closes');
  hp.docHandlers.click({ target: q04 }); hp.docHandlers.click({ target: {} });
  assert.strictEqual(panel.className, '', 'a click outside closes');
  hp.docHandlers.click({ target: findQ(hp.el('x_grid'), '99') });
  assert(/No bundled help/.test(flat(panel)), 'a reading with no entry gets the generic popup');
  hp.docHandlers.click({ target: findQ(hp.el('m6'), 'm06:evap') });
  assert(/EVAP leak test/.test(flat(panel)) && panel.className === 'open', 'Mode 06 lines have help, and opening another replaces the first');
  assert.strictEqual(hp.el('x_grid').children.filter(c => c.className === 'xr').length, 10, 'rows (7 main channels, 0x04, 0x10, 0x99) are updated in place, not duplicated');
  hp.docHandlers.keydown({ key: 'Escape' });
  panel.offsetWidth = 360; q04.getBoundingClientRect = () => ({ left: 480, top: 100, bottom: 120, right: 500 });
  hp.docHandlers.click({ target: q04 });
  const left = parseFloat(panel.style.left);
  assert(left >= 12 && left <= 500 - 360 - 12, 'panel stays inside a 500 px viewport, got left=' + left);
  const bad = makeEnv(extraStates, 'v6', { pids: null, mode06: null });
  for (let k = 0; k < 5; k++) await bad.tick();
  bad.docHandlers.click({ target: findQ(bad.el('x_grid'), '04') });
  assert(/No bundled help/.test(flat(bad.el('helpPanel'))), 'a malformed help reply falls back to the generic popup, no crash');

  // 6) Overview: tile state from the catalog's watch ranges on a 10 s median, honest empty states, attention list
  const tw = { ok: [-10, 10], out: [-20, 20] };
  const mk = (title, w, extra) => Object.assign({ title, measures: title + ' explained.', use: [], typical: '', status: [] }, w ? { watch: w } : {}, extra || {});
  const OVF = { pids: { '06': mk('Short-term trim, bank 1', tw), '07': mk('Long-term trim, bank 1', tw), '08': mk('Short-term trim, bank 2', tw),
                        '09': mk('Long-term trim, bank 2', tw), '05': mk('Coolant', { ok: [null, 105], out: [null, 112] }),
                        '42': mk('Battery', { ok: [13.2, 14.8], out: [11.5, 15.5] }, { watch_engine_off: { ok: [12.2, 14.8], out: [11.5, 15.5] } }),
                        '04': mk('Engine load'), '0B': mk('Manifold pressure') }, mode06: {} };
  const base = () => ({ '0C': 700, '05': 90, '06': 2, '07': 1, '08': 2, '09': 1, '0B': 36, '42': 14.2, '04': 28 });
  const ovEnv = async (fn, tweak) => {
    const e = makeEnv(statesFor(30, fn).map(st => (tweak ? tweak(st) : st)), 'v0', OVF, [], NOGAUGES());
    for (let k = 0; k < 32; k++) await e.tick();
    return e;
  };
  const tile = (e, key) => { let r = null; walk(e.el('o_tiles'), n => { if (n.getAttribute('data-key') === key) r = n; }); return r; };
  const part = (t, cls) => { let r = null; walk(t, n => { if (n.className === cls) r = n; }); return r.textContent; };
  const rowsOf = e => e.el('o_attn').children.map(c => c.getAttribute('data-key'));

  const okEnv = await ovEnv(base);
  assert.deepStrictEqual(['trims', 'ect', 'volts', 'load', 'map'].map(k => tile(okEnv, k).className), ['tile', 'tile', 'tile', 'tile neutral', 'tile neutral'], 'healthy: normal tiles, no-threshold tiles neutral');
  assert.strictEqual(okEnv.el('o_note').textContent, 'No flags in the 6 readings assessed');
  assert.strictEqual(part(tile(okEnv, 'load'), 'sub'), 'live');
  const wEnv = await ovEnv(() => Object.assign(base(), { '06': 13, '42': 12.1 }));
  assert.strictEqual(tile(wEnv, 'trims').className, 'tile watch'); assert.strictEqual(part(tile(wEnv, 'trims'), 'big'), '13.0');
  assert(/bank 1/.test(part(tile(wEnv, 'trims'), 'sub')), 'the subtitle names the worst trim');
  assert.strictEqual(tile(wEnv, 'volts').className, 'tile watch');
  assert.deepStrictEqual(rowsOf(wEnv), ['06', '42'], 'attention lists only out-of-range readings'); assert.strictEqual(wEnv.el('o_note').textContent, '');
  const oEnv = await ovEnv(() => Object.assign(base(), { '09': 25, '42': 12.1 }));
  assert.strictEqual(tile(oEnv, 'trims').className, 'tile out'); assert.deepStrictEqual(rowsOf(oEnv), ['09', '42'], 'out of range sorts before watch');
  const offEnv = await ovEnv(() => Object.assign(base(), { '0C': 0, '42': 12.4 }));
  assert.strictEqual(tile(offEnv, 'volts').className, 'tile', 'engine off: 12.4 V is normal');
  assert.strictEqual(tile(wEnv, 'volts').className, 'tile watch', 'engine running: low voltage is flagged');
  const hybridEnv = await ovEnv(() => Object.assign(base(), { '0C': 0, '42': 14.2 }));
  assert.strictEqual(tile(hybridEnv, 'volts').className, 'tile', 'engine off but charging (hybrid, start-stop): 14.2 V is not flagged');
  const lowOff = await ovEnv(() => Object.assign(base(), { '0C': 0, '42': 11.9 }));
  assert.strictEqual(tile(lowOff, 'volts').className, 'tile watch', 'engine off: a weak battery is still flagged');
  const highOff = await ovEnv(() => Object.assign(base(), { '0C': 0, '42': 24 }));
  assert.strictEqual(tile(highOff, 'volts').className, 'tile out', 'engine off: 24 V is out of range, not normal');
  const noLoad = await ovEnv(() => { const b = base(); delete b['04']; return b; });
  assert.strictEqual(tile(noLoad, 'load').className, 'tile idle'); assert.strictEqual(part(tile(noLoad, 'load'), 'sub'), 'not reported');
  const stale = await ovEnv((s) => { const b = base(); if (s > 10) delete b['04']; return b; });
  assert(/^last seen \d+ s ago$/.test(part(tile(stale, 'load'), 'sub')), 'a rotating extra shows its age: ' + part(tile(stale, 'load'), 'sub'));
  const stoppedEnv = await ovEnv(base, st => Object.assign(st, { status: 'stopped' }));
  assert.strictEqual(part(tile(stoppedEnv, 'ect'), 'sub'), 'not sampling'); assert.strictEqual(stoppedEnv.el('o_note').textContent, 'Not sampling');
  assert.deepStrictEqual(rowsOf(stoppedEnv), []);
  const chipsEnv = await ovEnv(base, st => Object.assign(st, { codes: { read: true, note: null, mil: true, stored: [{ code: 'P0300' }], pending: [], permanent: [] } }));
  assert.strictEqual(chipsEnv.el('chipLamp').textContent, 'check engine: ON'); assert.strictEqual(chipsEnv.el('chipCodes').textContent, '1 stored');
  const chipsNone = await ovEnv(base, st => Object.assign(st, { codes: { read: false, note: null } }));
  assert.strictEqual(chipsNone.el('chipLamp').textContent, 'check engine: ?'); assert.strictEqual(chipsNone.el('chipCodes').textContent, 'codes not read');
  const chipsOff = await ovEnv(base, st => Object.assign(st, { codes: { read: true, note: null, mil: false, stored: [], pending: [], permanent: [] } }));
  assert.strictEqual(chipsOff.el('chipLamp').textContent, 'check engine: off');
  assert.ok(/<span class="chip" id="chipLamp" title="Malfunction indicator lamp \(check-engine light\) as reported by the engine computer">check engine: \?<\/span>/.test(html), 'the check-engine chip explains itself in a tooltip');
  const qTrim = findQ(wEnv.el('o_attn'), '06'); assert(qTrim, 'attention rows have a ? button');
  wEnv.docHandlers.click({ target: qTrim }); assert(/Short-term trim, bank 1/.test(flat(wEnv.el('helpPanel'))) && /now 13/.test(flat(wEnv.el('helpPanel'))), 'row help shows the catalog and the live value');

  // 7) Overview honesty: help ranges not loaded (and a retry), last-seen age, spike vs median, odd help entries
  const noHelp = makeEnv(statesFor(30, base), 'v0', null);
  for (let k = 0; k < 32; k++) await noHelp.tick();
  assert.strictEqual(noHelp.el('o_note').textContent, 'Health ranges not loaded, so nothing is checked');
  noHelp.setHelp(OVF); noHelp.advance(6000);
  for (let k = 0; k < 4; k++) await noHelp.tick();
  assert.strictEqual(noHelp.el('o_note').textContent, 'No flags in the 6 readings assessed', 'the page retries loading the ranges');
  const gone = await ovEnv((s) => { const b = base(); if (s > 3) delete b['04']; return b; });
  assert.strictEqual(tile(gone, 'load').className, 'tile stale', 'an extra not seen for over 10 s keeps its last value, marked not current');
  assert.strictEqual(part(tile(gone, 'load'), 'sub'), 'last seen 11 s ago');
  const slow = await ovEnv((s) => { const b = base(); if (s > 20) delete b['04']; return b; }, st => Object.assign(st, { hz_measured: 0.5 }));
  assert.strictEqual(part(tile(slow, 'load'), 'sub'), 'live', 'on a slow bus 4 s is under three sweeps, so still live');
  const spike = await ovEnv((s) => Object.assign(base(), s === 30 ? { '06': 40 } : {}));
  assert.strictEqual(tile(spike, 'trims').className, 'tile', 'a one-sweep spike does not flip the tile');
  const odd = makeEnv(extraStates, 'v6', { pids: { '04': 'not an object' }, mode06: {} });
  for (let k = 0; k < 5; k++) await odd.tick();
  odd.docHandlers.click({ target: findQ(odd.el('x_grid'), '04') });
  assert(/No bundled help/.test(flat(odd.el('helpPanel'))), 'a non-object help entry falls back to the generic popup');

  // 8) replay UI: banner, transport bar, controls, picker, upload
  const REPLAY = (over) => Object.assign({ name: 'drive.json', duration: 370, pos: 151, speed: 1, playing: true, ended: false }, over);
  const rstates = (r) => statesFor(3, idle).map(st => Object.assign(st, { replay: r, vehicle: { key: 'ABCDEFGH-P', known: false, runs: 0, note: null } }));
  const RUNS = [{ name: 'a.json', size: 2048, duration: 370, time: '2026-09-30T21:32:56Z', meta: null }, { name: '<b>.json', size: 10, duration: 5, time: '2026-09-29T10:00:00Z', meta: null }];
  const rp1 = makeEnv(rstates(REPLAY()), 'v0', null, RUNS);
  for (let k = 0; k < 4; k++) await rp1.tick();
  assert.strictEqual(rp1.el('rbar').hidden, false); assert.strictEqual(rp1.el('replayBanner').hidden, false);
  assert(/Replay: drive\.json/.test(rp1.el('replayBanner').textContent), 'banner names the run');
  assert.strictEqual(rp1.el('rb_time').textContent, '2:31 / 6:10'); assert.strictEqual(rp1.el('rb_play').textContent, 'Pause');
  assert.strictEqual(rp1.el('rb_speed').value, '1'); assert.strictEqual(rp1.el('rb_seek').max, 370); assert.strictEqual(rp1.el('rb_seek').value, 151);
  assert.strictEqual(rp1.el('pause').disabled, true); assert.strictEqual(rp1.el('save').disabled, true);
  assert(/REPLAY/.test(rp1.el('chipLive').innerHTML) && !/LIVE/.test(rp1.el('chipLive').innerHTML), 'the status chip says REPLAY, not LIVE');
  assert.strictEqual(rp1.el('chipLive').className, 'chip live');
  assert(/replay/.test(rp1.el('chipCar').textContent) && !/new/.test(rp1.el('chipCar').textContent), 'the car chip says replay, not new');
  const lastPost = () => rp1.posts[rp1.posts.length - 1];
  rp1.handlers['rb_play:click'](); assert(/\/api\/replay\/control/.test(lastPost().url) && lastPost().body.action === 'pause');
  rp1.handlers['rb_restart:click'](); assert.strictEqual(lastPost().body.action, 'restart');
  rp1.el('rb_speed').value = '4'; rp1.handlers['rb_speed:change'](); assert.deepStrictEqual(lastPost().body, { action: 'speed', speed: 4 });
  rp1.el('rb_seek').value = '60';
  const beforeDrag = rp1.posts.length; rp1.handlers['rb_seek:input']();
  assert.strictEqual(rp1.posts.length, beforeDrag, 'dragging alone sends nothing');
  assert.strictEqual(rp1.el('rb_time').textContent, '1:00 / 6:10', 'the label follows the drag');
  rp1.handlers['rb_seek:change'](); assert.deepStrictEqual(lastPost().body, { action: 'seek', pos: 60 });
  rp1.handlers['rb_exit:click'](); assert.strictEqual(lastPost().body.action, 'exit');
  const ended = makeEnv(rstates(REPLAY({ playing: false, ended: true, pos: 370 })), 'v0');
  for (let k = 0; k < 4; k++) await ended.tick();
  assert(/REPLAY . ENDED/.test(ended.el('chipLive').innerHTML) && ended.el('chipLive').className === 'chip paused', 'an ended replay says so');
  assert.strictEqual(ended.el('rb_play').textContent, 'Replay'); assert.strictEqual(ended.el('rb_time').textContent, '6:10 / 6:10');
  const evilName = makeEnv(rstates(REPLAY({ name: '<img src=x onerror=1>' })), 'v0');
  for (let k = 0; k < 4; k++) await evilName.tick();
  assert(evilName.el('replayBanner').textContent.includes('<img src=x onerror=1>') && evilName.el('replayBanner').innerHTML === '', 'run name is shown as text');
  const live = makeEnv(statesFor(3, idle), 'v0');
  for (let k = 0; k < 4; k++) await live.tick();
  assert.strictEqual(live.el('rbar').hidden, true); assert.strictEqual(live.el('replayBanner').hidden, true); assert.strictEqual(live.el('pause').disabled, false);

  // picker and upload
  const pk = makeEnv(statesFor(3, idle), 'v0', null, RUNS);
  for (let k = 0; k < 3; k++) await pk.tick();
  pk.el('replayPanel').hidden = true;   // the page's markup starts it hidden; the fake DOM does not
  pk.handlers['replayBtn:click'](); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r));
  assert.strictEqual(pk.el('replayPanel').hidden, false);
  assert.strictEqual(pk.el('rp_runs').children.length, 2);
  assert.strictEqual(pk.el('rp_src').value, 'mine', 'no examples: the picker opens on My runs');
  assert.strictEqual(pk.el('rp_runs').children[0].textContent, '2026-09-30 21:32 UTC · 6:10 · a', 'option label: timestamp · length · title');
  assert(pk.el('rp_runs').children[1].textContent.includes('<b>') && pk.el('rp_runs').children[1].innerHTML === '', 'run names are shown as text');
  pk.el('rp_runs').value = 'a.json'; pk.handlers['rp_load:click'](); await new Promise(r => setImmediate(r));
  assert.deepStrictEqual(pk.posts[pk.posts.length - 1].body, { source: 'mine', name: 'a.json' }); assert.strictEqual(pk.el('replayPanel').hidden, true);
  const upload = async (file) => { pk.handlers['rp_file:change']({ target: { files: [file], value: 'x' } }); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r)); };
  await upload({ name: 'x.json', size: 100, text: () => Promise.resolve(JSON.stringify({ kind: 'live_run' })) });
  assert.deepStrictEqual(pk.posts[pk.posts.length - 1].body, { run: { kind: 'live_run' }, name: 'x.json' });
  const sent = pk.posts.length;
  await upload({ name: 'big.json', size: 9 * 1024 * 1024, text: () => Promise.resolve('{}') });
  assert.strictEqual(pk.posts.length, sent); assert(/too large/.test(pk.el('rp_err').textContent), 'oversize file refused before sending');
  await upload({ name: 'bad.json', size: 10, text: () => Promise.resolve('nope') });
  assert.strictEqual(pk.posts.length, sent); assert(/not a JSON file/.test(pk.el('rp_err').textContent));
  pk.el('replayPanel').hidden = false;
  pk.sandbox.fetch = () => Promise.resolve({ ok: false, json: () => Promise.resolve({ error: 'not a saved run' }) });
  pk.el('rp_runs').value = 'a.json'; pk.handlers['rp_load:click'](); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r));
  assert.strictEqual(pk.el('rp_err').textContent, 'not a saved run'); assert.strictEqual(pk.el('replayPanel').hidden, false, 'the panel stays open on an error');


  // 8b) replay picker: source, then Make -> Model -> Year narrowing, then runs newest first
  const M = (make, model, year, title) => ({ make, model, year, title });
  const EX = { runs: [{ name: 'mine-1.json', size: 9, duration: 30, time: '2026-09-01T08:00:00Z', meta: M('Ford', 'F-150', 1999, 'my truck') }],
    examples: [
      { name: 'h1.json', size: 9, duration: 366, time: '2026-09-30T21:32:56Z', meta: M('Honda', 'Ridgeline', 2024, 'Ridgeline 6 min drive') },
      { name: 't-old.json', size: 9, duration: 60, time: '2026-01-02T03:04:05Z', meta: M('Toyota', 'Highlander', 2023, 'old drive') },
      { name: 'h2.json', size: 9, duration: 90, time: '2026-08-01T00:00:00Z', meta: M('Honda', 'Ridgeline', 2023, 'older truck') },
      { name: 'p.json', size: 9, duration: 90, time: '2026-08-02T00:00:00Z', meta: M('Honda', 'Pilot', 2024, '<img src=x onerror=1>') },
      { name: 't-new.json', size: 9, duration: 125, time: '2026-09-15T12:00:00Z', meta: M('Toyota', 'Highlander', 2023, 'new drive') },
      { name: 'nolabel.json', size: 9, duration: 5, time: '2026-07-01T00:00:00Z', meta: null }] };
  const pp = makeEnv(statesFor(3, idle), 'v0', null, EX);
  for (let k = 0; k < 3; k++) await pp.tick();
  pp.el('replayPanel').hidden = true;
  pp.handlers['replayBtn:click'](); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r));
  const opts = (id) => pp.el(id).children.map(c => c.textContent);
  const vals = (id) => pp.el(id).children.map(c => c.value);
  const pick = (id, v) => { pp.el(id).value = v; pp.handlers[id + ':change'](); };
  assert.strictEqual(pp.el('rp_src').value, 'examples', 'examples exist: the picker opens on them');
  assert.deepStrictEqual(opts('rp_make'), ['Honda', 'Toyota', '(unlabelled)'], 'makes sorted, unlabelled last');
  assert.strictEqual(pp.el('rp_make').value, 'Honda');
  assert.deepStrictEqual(opts('rp_model'), ['Pilot', 'Ridgeline'], 'models narrowed to the make');
  assert.deepStrictEqual(opts('rp_year'), ['2024']);
  assert.strictEqual(pp.el('rp_runs').children[0].textContent, '2026-08-02 00:00 UTC · 1:30 · <img src=x onerror=1>');
  assert.strictEqual(pp.el('rp_runs').children[0].innerHTML, '', 'labels are shown as text');
  pick('rp_model', 'Ridgeline');
  assert.deepStrictEqual(opts('rp_year'), ['2024', '2023'], 'years newest first');
  assert.deepStrictEqual(vals('rp_runs'), ['h1.json']);
  assert.strictEqual(pp.el('rp_runs').children[0].textContent, '2026-09-30 21:32 UTC · 6:06 · Ridgeline 6 min drive');
  pick('rp_year', '2023'); assert.deepStrictEqual(vals('rp_runs'), ['h2.json']);
  pick('rp_make', 'Toyota');
  assert.deepStrictEqual(opts('rp_model'), ['Highlander']); assert.deepStrictEqual(opts('rp_year'), ['2023']);
  assert.deepStrictEqual(vals('rp_runs'), ['t-new.json', 't-old.json'], 'runs newest first');
  assert.strictEqual(pp.el('rp_runs').value, 't-new.json');
  pick('rp_make', '(unlabelled)');
  assert.deepStrictEqual(opts('rp_model'), ['(unlabelled)']); assert.deepStrictEqual(opts('rp_year'), ['(unlabelled)']);
  assert.strictEqual(pp.el('rp_runs').children[0].textContent, '2026-07-01 00:00 UTC · 0:05 · nolabel', 'an unlabelled run shows its file name');
  pp.handlers['rp_load:click'](); await new Promise(r => setImmediate(r));
  assert.deepStrictEqual(pp.posts[pp.posts.length - 1].body, { source: 'examples', name: 'nolabel.json' });
  pp.el('replayPanel').hidden = false;
  pick('rp_src', 'mine');
  assert.deepStrictEqual(opts('rp_make'), ['Ford']); assert.deepStrictEqual(vals('rp_runs'), ['mine-1.json']);
  pp.handlers['rp_load:click'](); await new Promise(r => setImmediate(r));
  assert.deepStrictEqual(pp.posts[pp.posts.length - 1].body, { source: 'mine', name: 'mine-1.json' });
  const none = makeEnv(statesFor(3, idle), 'v0', null, { runs: [], examples: [] });
  for (let k = 0; k < 3; k++) await none.tick();
  none.el('replayPanel').hidden = true;
  none.handlers['replayBtn:click'](); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r));
  assert.deepStrictEqual(none.el('rp_runs').children.map(c => c.textContent), ['no saved runs yet']);
  const before = none.posts.length; none.handlers['rp_load:click'](); assert.strictEqual(none.posts.length, before, 'nothing to load');

  // 9) after a seek (new run id, seq restarts below the page's old position) the page refetches the whole refill
  const fullState = (run, n, v) => ({ status: 'running', run, message: null, demo: false, seq: n, now: 0.4 * n, since_last_sample: 0.1, hz: 2.5,
    hz_measured: 2.5, seconds_left: null, adapter: {}, replay: REPLAY(),
    channels: { '42': { name: 'control_module_voltage', unit: 'V', samples: Array.from({ length: n }, (_, i) => [i + 1, +(0.4 * (i + 1)).toFixed(3), v]) } } });
  const urls = [];
  const sk = makeEnv([], 'v0', OVF, [], NOGAUGES());
  await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r));
  sk.sandbox.fetch = (url) => {
    urls.push(url);
    const after = +((/after=(\d+)/.exec(url) || [0, 0])[1]);
    const st = urls.length === 1 ? fullState(1, 5, 15.4) : fullState(2, 3, 12.1);   // the server only returns samples newer than `after`
    st.channels['42'].samples = st.channels['42'].samples.filter(s => s[0] > after);
    return Promise.resolve({ ok: true, json: () => Promise.resolve(st) });
  };
  for (let k = 0; k < 5; k++) await sk.tick();
  assert(urls.length >= 3 && /after=5/.test(urls[1]) && /after=0/.test(urls[2]), 'a run change is followed by a full refetch: ' + urls.join(' '));
  let skVolts = null; walk(sk.el('o_tiles'), n => { if (n.getAttribute('data-key') === 'volts') skVolts = n; });
  let skBig = null; walk(skVolts, n => { if (n.className === 'big') skBig = n; });
  assert.strictEqual(skBig.textContent, '12.1', 'the refilled window reached the page');

  // 10) a failed seek request does not leave the scrubber frozen
  const rp2 = makeEnv(rstates(REPLAY()), 'v0');
  for (let k = 0; k < 4; k++) await rp2.tick();
  rp2.el('rb_seek').value = '60'; rp2.handlers['rb_seek:input']();
  rp2.sandbox.fetch = (url, opts) => opts && opts.method === 'POST' ? Promise.reject(new Error('down'))
    : Promise.resolve({ ok: true, json: () => Promise.resolve(Object.assign(rstates(REPLAY({ pos: 200 }))[0], { seq: 99 })) });
  rp2.handlers['rb_seek:change']();
  await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r));
  for (let k = 0; k < 3; k++) await rp2.tick();
  assert.strictEqual(rp2.el('rb_time').textContent, '3:20 / 6:10', 'the scrubber follows playback again after a failed seek');

  // 11) units toggle: display only, metric by default, remembered, applied wherever a value is shown
  const uStates = (over, tweak) => statesFor(30, () => Object.assign(base(), over)).map(st => (tweak ? tweak(st) : st));
  const uEnv = async (over, view = 'v0', store = {}, tweak = null) => {
    const e = makeEnv(uStates(over, tweak), view, OVF, [], store);
    for (let k = 0; k < 32; k++) await e.tick();
    return e;
  };
  const big = (e, key) => part(tile(e, key), 'big'), tunit = (e, key) => part(tile(e, key), 'unit');
  const rowVal = (e, key) => { let r = null; walk(e.el('o_attn'), n => { if (n.getAttribute('data-key') === key) r = n; }); return part(r, 'val'); };
  const toggle = async (e) => { e.handlers['unitsBtn:click'](); for (let k = 0; k < 2; k++) await e.tick(); };
  const store = NOGAUGES();
  const um = await uEnv({ '05': 118 }, 'v0', store);
  assert.strictEqual(big(um, 'ect'), '118'); assert.strictEqual(tunit(um, 'ect'), '°C'); assert.strictEqual(um.el('unitsBtn').textContent, 'Units: Metric');
  assert.strictEqual(big(um, 'map'), '36'); assert.strictEqual(rowVal(um, '05'), '118 °C');
  await toggle(um);
  assert.strictEqual(big(um, 'ect'), '244'); assert.strictEqual(tunit(um, 'ect'), '°F');
  assert.strictEqual(big(um, 'map'), '10.6'); assert.strictEqual(tunit(um, 'map'), 'inHg');
  assert.strictEqual(big(um, 'trims'), '2.0'); assert.strictEqual(tunit(um, 'trims'), '%', 'percent does not change');
  assert.strictEqual(rowVal(um, '05'), '244 °F', 'attention rows follow the unit');
  assert.strictEqual(um.el('unitsBtn').textContent, 'Units: US'); assert.strictEqual(store['shadetree.units'], 'us');
  assert.strictEqual(tile(um, 'ect').className, 'tile out', 'the state is judged on the metric value');
  um.docHandlers.click({ target: findQ(um.el('o_tiles'), '05') });
  assert(/now 244 °F/.test(flat(um.el('helpPanel'))), 'the popup live line follows the unit: ' + flat(um.el('helpPanel')));
  const um2 = await uEnv({}, 'v0', store);
  assert.strictEqual(big(um2, 'ect'), '194', 'the choice is remembered');
  await toggle(um2); assert.strictEqual(big(um2, 'ect'), '90'); assert.strictEqual(store['shadetree.units'], 'metric');
  const noStore = makeEnv(uStates({}), 'v0', OVF, [], null);
  for (let k = 0; k < 32; k++) await noStore.tick();
  const ectVal = (e) => { let r = null; walk(e.el('d_panel'), n => { if (n.getAttribute && n.getAttribute('data-key') === '05:dial') r = n; }); return part(r, 'gval'); };   // no storage: General's own gauges, so the coolant gauge (its tile is hidden)
  assert.strictEqual(ectVal(noStore), '90 °C', 'without storage it starts metric');
  await toggle(noStore); assert.strictEqual(ectVal(noStore), '194 °F', 'and still toggles');

  // All readings: one table row per channel (main channels and extras, speed included): name (unit), now, min, max, average
  const RSTATS = { '0D': { n: 9, min: 0, max: 112.65, avg: 50 }, '05': { n: 9, min: 20, max: 90, avg: 70 }, '0C': { n: 9, min: 650, max: 3200, avg: 1500.4 },
                   '0B': { n: 9, min: 30, max: 101, avg: 40 } };
  const speedStates = (replay) => statesFor(4, idle).map(st => {
    st.channels['0D'] = { name: 'vehicle_speed', unit: 'km/h', samples: [[st.seq, st.now, 60]] };
    st.channels['0B'] = { name: 'intake_manifold_pressure', unit: 'kPa', samples: [[st.seq, st.now, 36]] };
    st.channels['03'] = { name: 'fuel_system_status', unit: null, labels: { '2': 'closed loop' }, samples: [[st.seq, st.now, 2]] };
    st.stats = RSTATS; if (replay) st.replay = { name: 'r.json', duration: 300, pos: st.now, speed: 1, playing: true, ended: false };
    return st;
  });
  const rrow = (e, key) => { let r = null; walk(e.el('x_grid'), n => { if (n.className === 'xr' && n.getAttribute('data-key') === key) r = n; }); return r; };
  const cells = (e, key) => rrow(e, key).children.map(c => flat(c).replace(/\s*\?$/, '').trim().replace(/\s+/g, ' '));   // the name cell ends with its ? button
  const sp = makeEnv(speedStates(true), 'v6', OVF, [], { 'shadetree.units': 'us' });
  for (let k = 0; k < 5; k++) await sp.tick();
  assert.deepStrictEqual(cells(sp, '0D'), ['Vehicle speed (mph)', '37', '0', '70', '31', '—', '9'], 'speed row converts every column: ' + cells(sp, '0D'));
  assert.deepStrictEqual(cells(sp, '05'), ['Coolant temp (°F)', '106', '68', '194', '158', '—', '9'], 'a main channel is a row too');
  assert.deepStrictEqual(cells(sp, '0B'), ['MAP (inHg)', '10.6', '8.9', '29.8', '11.8', '—', '9'], 'manifold pressure in inHg');
  assert.deepStrictEqual(cells(sp, '0C'), ['Engine speed (rpm)', '700', '650', '3200', '1500', '—', '9']);
  assert.deepStrictEqual(cells(sp, '06'), ['STFT bank 1 (%)', '-12.0', '—', '—', '—', '—', '—'], 'no stats from the server: dashes, not made-up numbers');
  assert.deepStrictEqual(cells(sp, '03'), ['Fuel system status', 'closed loop', '—', '—', '—', '—', '—'], 'a status reading shows its label and no statistics');
  assert(findQ(rrow(sp, '0D'), '0D'), 'every row keeps its ? help button');
  assert.strictEqual(sp.el('x_grid').children.filter(c => c.className === 'xr').length, 11, 'all 11 channels on one table, in pid order');
  assert.strictEqual(sp.el('x_grid').children[0].getAttribute('data-key'), '03');
  assert(/11 readings · stats over the whole run/.test(sp.el('x_count').textContent), sp.el('x_count').textContent);
  await toggle(sp);
  assert.deepStrictEqual(cells(sp, '0D'), ['Vehicle speed (km/h)', '60', '0', '112.7', '50', '—', '9'], 'metric after the toggle');
  const spl = makeEnv(speedStates(false), 'v6', OVF, [], {});
  for (let k = 0; k < 5; k++) await spl.tick();
  assert(/stats over this run so far/.test(spl.el('x_count').textContent), 'live says the stats are over the run so far');
  // the extra stats: std (scaled by the Units toggle without the offset), sample count and last-seen age, and when min and max happened (m:ss)
  const FSTATS = { '0D': { n: 9, min: 0, max: 112.65, avg: 50, std: 10, min_t: 12.4, max_t: 75.2, age: 1.24 },
                   '05': { n: 120, min: 20, max: 90, avg: 70, std: 2, min_t: 0.4, max_t: 3725, age: 75 } };
  const fullStates = speedStates(true).map(st => Object.assign(st, { stats: FSTATS }));
  const fs1 = makeEnv(fullStates, 'v6', OVF, [], { 'shadetree.units': 'us' });
  for (let k = 0; k < 5; k++) await fs1.tick();
  assert.deepStrictEqual(cells(fs1, '0D'), ['Vehicle speed (mph)', '37', '0 0:12', '70 1:15', '31', '6.2', '9 1.2 s ago'], 'speed row: ' + cells(fs1, '0D'));
  assert.deepStrictEqual(cells(fs1, '05'), ['Coolant temp (°F)', '106', '68 0:00', '194 62:05', '158', '3.6', '120 1:15 ago'], 'a spread in °F has no +32: ' + cells(fs1, '05'));
  await toggle(fs1);
  assert.deepStrictEqual(cells(fs1, '05'), ['Coolant temp (°C)', '41', '20 0:00', '90 62:05', '70', '2.0', '120 1:15 ago'], 'times do not change with units');
  assert.deepStrictEqual(cells(fs1, '0C'), ['Engine speed (rpm)', '700', '—', '—', '—', '—', '—'], 'a channel without stats stays dashes');

  // Dashboard, Handheld and Guided test: labels and digits
  const an = await uEnv({ '05': 41 }, 'v0', {});
  assert(/41/.test(flat(an.el('d_table'))) && /°C/.test(flat(an.el('d_table'))) && /kPa/i.test(flat(an.el('d_table'))), 'Dashboard rows in metric: ' + flat(an.el('d_table')).slice(0, 300));
  await toggle(an);
  assert(/106/.test(flat(an.el('d_table'))) && /°F/.test(flat(an.el('d_table'))) && /inHg/.test(flat(an.el('d_table'))), 'Dashboard rows convert to °F and inHg: ' + flat(an.el('d_table')).slice(0, 300));
  const hh2 = await uEnv({ '05': 41 }, 'v5', { 'shadetree.units': 'us' });
  assert(/106 °F/.test(flat(hh2.el('h_gauges'))), 'handheld gauges convert: ' + flat(hh2.el('h_gauges')).slice(0, 300));
  assert(/106/.test(flat(hh2.el('h_table'))) && /°F/.test(flat(hh2.el('h_table'))) && /inHg/.test(flat(hh2.el('h_table'))), 'handheld table converts: ' + flat(hh2.el('h_table')).slice(0, 300));
  const gt = await uEnv({ '05': 41 }, 'v3', { 'shadetree.units': 'us' });
  assert.strictEqual(gt.el('v3ect').textContent, '106'); assert.strictEqual(gt.el('v3ect_u').textContent, '°F'); assert.strictEqual(gt.el('v3map_u').textContent, 'inHg');

  // ?example=<file>: the page replays that example run on load, as picking it under Examples does; only examples, strict names
  const EXN = '2026-09-30T21-32-56Z-drive-rebuilt.json';
  const exEnv = async (search, postReply) => { const e = makeEnv(statesFor(3, idle), 'v0', null, [], {}, { search, postReply }); for (let k = 0; k < 3; k++) await e.tick(); return e; };
  const replays = (e) => e.posts.filter(p => /^\/api\/replay\?/.test(p.url));
  const exOk = await exEnv('?t=abc&example=' + EXN);
  assert.deepStrictEqual(replays(exOk).map(p => p.body), [{ source: 'examples', name: EXN }], 'loads the example by name from Examples only');
  assert.strictEqual(replays(exOk)[0].url, '/api/replay?t=abc', 'the token still goes only in the request URL');
  assert.strictEqual(exOk.el('exNote').textContent, '', 'no notice when it loads (the fake DOM ignores the hidden attribute)');
  const exNone = await exEnv('?t=abc');
  assert.strictEqual(replays(exNone).length, 0, 'no parameter, no replay'); assert.strictEqual(exNone.el('exNote').textContent, '');
  const exMissing = await exEnv('?t=abc&example=missing.json', () => ({ ok: false, status: 404, j: { error: 'no such saved run' } }));
  assert.strictEqual(exMissing.el('exNote').hidden, false); assert.strictEqual(exMissing.el('exNote').textContent, 'Example not found: missing.json');
  for (const bad of ['../runs/mine.json', '%2e%2e%2fmine.json', 'runs/mine.json', 'mine', '', 'a b.json', '<img src=x onerror=1>.json']) {
    const e = await exEnv('?t=abc&example=' + bad);
    assert.strictEqual(replays(e).length, 0, 'an invalid name is never sent: ' + bad);
    assert.strictEqual(e.el('exNote').hidden, false, 'and says so: ' + bad);
    assert(/^Example not found/.test(e.el('exNote').textContent) && e.el('exNote').innerHTML === '', 'as text: ' + bad);
    assert(!e.el('exNote').textContent.includes('abc'), 'the token never reaches the notice');
  }
  const exBusy = await exEnv('?t=abc&example=' + EXN, () => ({ ok: false, status: 409, j: { error: 'the console is already sampling; stop it first' } }));
  assert.strictEqual(exBusy.el('exNote').textContent, 'Could not load the example: the console is already sampling; stop it first', 'a busy console is not "not found"');

  // Theme: the stored choice beats the system preference; a bad stored value is ignored; dark when nothing is known; blocked storage is tolerated
  const thEnv = async (store, page) => { const e = makeEnv(statesFor(2, idle), 'v0', null, [], store, page); for (let k = 0; k < 2; k++) await e.tick(); return e; };
  const theme = (e) => e.el('html').getAttribute('data-theme');
  const th1 = await thEnv({ 'shadetree.theme': 'light' }, { prefersLight: false });
  assert.strictEqual(theme(th1), 'light', 'stored light beats a dark system'); assert.strictEqual(th1.el('themeBtn').textContent, 'Theme: Dark', 'the label names the mode a click switches to');
  assert.strictEqual(theme(await thEnv({ 'shadetree.theme': 'dark' }, { prefersLight: true })), 'dark', 'stored dark beats a light system');
  assert.strictEqual(theme(await thEnv({}, { prefersLight: true })), 'light', 'no stored choice: follow the system');
  assert.strictEqual(theme(await thEnv({ 'shadetree.theme': 'purple' }, { prefersLight: true })), 'light', 'a bad stored value is ignored');
  const th0 = await thEnv({}, {});
  assert.strictEqual(theme(th0), 'dark', 'no matchMedia: dark, as the page always was'); assert.strictEqual(th0.el('themeBtn').textContent, 'Theme: Light');
  const thStore = {}, th2 = await thEnv(thStore, { prefersLight: false });
  th2.handlers['themeBtn:click']();
  assert.strictEqual(theme(th2), 'light'); assert.strictEqual(thStore['shadetree.theme'], 'light', 'the choice is remembered');
  assert.strictEqual(th2.el('themeBtn').textContent, 'Theme: Dark');
  th2.handlers['themeBtn:click'](); assert.strictEqual(theme(th2), 'dark'); assert.strictEqual(thStore['shadetree.theme'], 'dark');
  const th3 = await thEnv({}, { prefersLight: true, storageThrows: true });
  assert.strictEqual(theme(th3), 'light', 'blocked storage: still follows the system');
  th3.handlers['themeBtn:click'](); assert.strictEqual(theme(th3), 'dark', 'and still toggles');

  // Skin: a stored choice beats the viewport; a bad stored value is ignored; Plain on a desktop, Retro on a phone; blocked storage is tolerated (Review Focus 1)
  const skin = (e) => e.el('html').getAttribute('data-skin');
  assert.strictEqual(skin(await thEnv({}, {})), 'plain', 'no matchMedia: Plain, as the page always was');
  assert.strictEqual(skin(await thEnv({}, { narrow: false })), 'plain', 'desktop width: Plain');
  assert.strictEqual(skin(await thEnv({}, { narrow: true })), 'retro', 'phone width: Retro');
  assert.strictEqual(skin(await thEnv({ 'shadetree.skin': 'plain' }, { narrow: true })), 'plain', 'a stored Plain beats a phone');
  assert.strictEqual(skin(await thEnv({ 'shadetree.skin': 'retro' }, { narrow: false })), 'retro', 'a stored Retro beats a desktop');
  for (const bad of ['Retro', 'oxblood', '', 'null', '{"skin":"retro"}']) {
    assert.strictEqual(skin(await thEnv({ 'shadetree.skin': bad }, { narrow: false })), 'plain', 'a bad stored value is ignored: ' + bad);
    assert.strictEqual(skin(await thEnv({ 'shadetree.skin': bad }, { narrow: true })), 'retro', 'and the viewport decides: ' + bad);
  }
  const skStore = {}, sk1 = await thEnv(skStore, { narrow: false });
  assert.strictEqual(sk1.el('skinBtn').textContent, 'Skin: Retro', 'the label names the skin a click switches to, as Theme does');
  sk1.handlers['skinBtn:click']();
  assert.strictEqual(skin(sk1), 'retro'); assert.strictEqual(skStore['shadetree.skin'], 'retro', 'the choice is remembered');
  assert.strictEqual(sk1.el('skinBtn').textContent, 'Skin: Plain');
  assert.strictEqual(sk1.el('html').getAttribute('data-theme'), 'dark', 'the skin leaves the theme alone');
  sk1.handlers['skinBtn:click'](); assert.strictEqual(skin(sk1), 'plain'); assert.strictEqual(skStore['shadetree.skin'], 'plain');
  const sk2 = await thEnv({}, { narrow: true, storageThrows: true });
  assert.strictEqual(skin(sk2), 'retro', 'blocked storage: still follows the viewport');
  sk2.handlers['skinBtn:click'](); assert.strictEqual(skin(sk2), 'plain', 'and still toggles');
  const sk3 = await thEnv({ 'shadetree.theme': 'light', 'shadetree.skin': 'retro' }, { narrow: false });
  assert.strictEqual(skin(sk3) + '/' + sk3.el('html').getAttribute('data-theme'), 'retro/light', 'skin and theme are independent');
  sk3.handlers['themeBtn:click'](); assert.strictEqual(skin(sk3), 'retro', 'the theme leaves the skin alone');
  for (const v of ['v0', 'v3', 'v5', 'v6']) {   // a render error would surface as DISCONNECTED (poll's catch)
    const e = makeEnv(statesFor(3, idle), v, OVF, [], { 'shadetree.skin': 'retro', 'shadetree.theme': 'light' });
    for (let k = 0; k < 3; k++) await e.tick();
    assert(/SIMULATED/.test(e.el('chipLive').innerHTML), 'Retro light renders ' + v);
  }
  // Panel: a card with a title plate; the title is text, never markup
  const pn = makeEnv(statesFor(2, idle)); await pn.tick();
  const card = pn.parts().panel('<img src=x onerror=1>');
  assert.strictEqual(card.root.className, 'panel'); assert.deepStrictEqual(card.root.children.map(c => c.className), ['ptitle', 'pbody']);
  assert.strictEqual(card.name.textContent, '<img src=x onerror=1>'); assert.strictEqual(card.name.innerHTML, '', 'the title is text');
  assert.strictEqual(card.plate.children[0], card.name, 'callers may add controls after the name');

  // Gauge: watch ranges become zones; a reading missing from the run is dimmed and says so, never a zero (Review Focus 3)
  const gOver = (over, tweak, help = OVF, store = {}) => {
    const e = makeEnv(statesFor(30, () => Object.assign(base(), over)).map(st => (tweak ? tweak(st) : st)), 'v0', help, [], store);
    return (async () => { for (let k = 0; k < 32; k++) await e.tick(); return e; })();
  };
  const zs = (P, w, lo, hi) => Array.from(P.gaugeZones(w, lo, hi), z => [z.from, z.to, z.s]);   // Array.from: the page runs in another realm
  const g1 = await gOver({}), P1 = g1.parts();
  assert.deepStrictEqual(zs(P1, { ok: [-10, 10], out: [-20, 20] }, -25, 25), [[-25, -20, 'out'], [-20, -10, 'watch'], [-10, 10, 'ok'], [10, 20, 'watch'], [20, 25, 'out']], 'trim bands');
  assert.deepStrictEqual(zs(P1, { ok: [null, 105], out: [null, 112] }, -20, 130), [[-20, 105, 'ok'], [105, 112, 'watch'], [112, 130, 'out']], 'an open low end');
  assert.deepStrictEqual(zs(P1, { ok: [12.2, null], out: [11.5, null] }, 10, 16), [[10, 11.5, 'out'], [11.5, 12.2, 'watch'], [12.2, 16, 'ok']], 'an open high end');
  assert.deepStrictEqual(zs(P1, null, 0, 100), [], 'no watch range: no zones');
  assert.deepStrictEqual(zs(P1, { ok: 'x', out: [1, 2] }, 0, 100), [], 'a malformed range draws nothing');
  const gbox = (e, specs) => { const b = e.el('gbox_' + Math.random()); e.parts().gauges(b, specs); return b; };
  const gk = (b, key) => b.children.find(c => c.getAttribute('data-key') === key);
  const gpart = (g, cls) => g.children.find(c => c.className.split(' ')[0] === cls);
  const b1 = gbox(g1, [{ pid: '05', form: 'dial' }, { pid: '07', form: 'bar' }, { pid: '42', form: 'seven' }, { pid: '0D', form: 'dial' }, { pid: '0D', form: 'bar' }, { pid: '5C', form: 'dial' }, { pid: '05', form: 'dial' }]);
  assert.deepStrictEqual(b1.children.map(c => c.getAttribute('data-key')), ['05:dial', '07:bar', '42:seven', '0D:dial', '0D:bar', '5C:seven'], 'in order, a repeat drawn once, no range: seven-segment');
  const ect = gk(b1, '05:dial');
  assert.strictEqual(ect.className, 'gauge dial'); assert.strictEqual(gpart(ect, 'gnote').textContent, '10 s: normal'); assert.strictEqual(gpart(ect, 'gval').textContent, '90 °C');
  assert(/class="z-ok"/.test(gpart(ect, 'gface').innerHTML) && /class="z-watch"/.test(gpart(ect, 'gface').innerHTML) && /class="z-out"/.test(gpart(ect, 'gface').innerHTML), 'coolant dial has its bands');
  assert(/class="dn"/.test(gpart(ect, 'gface').innerHTML), 'and a needle');
  assert(findQ(ect, '05'), 'every gauge has its ? help');
  assert(/aria-label="14.2"/.test(gpart(gk(b1, '42:seven'), 'gface').innerHTML), 'battery digits');
  const gs = await gOver({ '0C': 2500, '99': 123.4 }, st => { st.channels['99'] = { name: 'x', unit: '', samples: [[st.seq, st.now, 123.4]] }; return st; });   // Review Focus 3: digits fit the reading, never 9s
  const bs = gbox(gs, [{ pid: '0C', form: 'seven' }, { pid: '99', form: 'seven' }]);
  assert(/aria-label="2500"/.test(gpart(gk(bs, '0C:seven'), 'gface').innerHTML), 'rpm 2500 shown in full: ' + gpart(gk(bs, '0C:seven'), 'gface').innerHTML.slice(0, 80));
  assert(/aria-label="123.4"/.test(gpart(gk(bs, '99:seven'), 'gface').innerHTML), 'no-range 123.4 shown in full');
  for (const key of ['0D:dial', '0D:bar', '5C:seven']) {   // not in this run: dimmed, said in words, and no needle, lit cell or digit
    const g = gk(b1, key), face = gpart(g, 'gface').innerHTML;
    assert(g.className.split(' ').includes('dim'), key + ' dimmed'); assert.strictEqual(gpart(g, 'gnote').textContent, 'not in this run', key);
    assert(!/class="dn"/.test(face) && !/class="[gyrn]/.test(face), key + ' has no needle and no lit cell');
    if (key.endsWith(':seven')) assert(/aria-label="-+"/.test(face), key + ' shows dashes, not digits: ' + face.slice(0, 120));
    assert(['', '—'].includes(gpart(g, 'gval').textContent), key + ' value is blank or a dash');
  }
  assert(/\.gauge\.dim \.gface\s*\{/.test(html) && !/\.gauge\.dim\s*\{/.test(html), 'only the face is dimmed, so the note keeps full contrast');
  const g2 = await gOver({ '07': 15 }), trim = gk(gbox(g2, [{ pid: '07', form: 'bar' }]), '07:bar');
  assert.strictEqual(trim.className, 'gauge bar watch'); assert.strictEqual(gpart(trim, 'gnote').textContent, '10 s: watch');
  assert(/class="g/.test(gpart(trim, 'gface').innerHTML) && /class="y/.test(gpart(trim, 'gface').innerHTML) && !/class="r/.test(gpart(trim, 'gface').innerHTML), 'lit from 0 through ok into watch');
  const g3 = await gOver({ '0C': 0, '42': 12.6 }), off = gk(gbox(g3, [{ pid: '42', form: 'dial' }]), '42:dial');
  assert.strictEqual(gpart(off, 'gnote').textContent, '10 s: normal', 'engine off: judged on the engine-off range');
  const g4 = await gOver({}, null, null), nh = gk(gbox(g4, [{ pid: '05', form: 'dial' }]), '05:dial');
  assert(!/class="z-/.test(gpart(nh, 'gface').innerHTML) && gpart(nh, 'gnote').textContent === '', 'help not loaded: no bands, no verdict');
  const g5 = await gOver({}, null, OVF, { 'shadetree.units': 'us' }), us = gk(gbox(g5, [{ pid: '05', form: 'dial' }]), '05:dial');
  assert.strictEqual(gpart(us, 'gval').textContent, '194 °F', 'the value follows Units'); assert.strictEqual(gpart(us, 'gnote').textContent, '10 s: normal', 'and is judged in metric');
  const g6 = await gOver({}, st => { st.channels['99'] = { name: '"><img src=x onerror=1>', unit: '', samples: [[st.seq, st.now, 3]] }; return st; });
  const gEvil = gk(gbox(g6, [{ pid: '99', form: 'dial', lo: 0, hi: 10 }]), '99:dial');
  assert(!/<img/.test(gpart(gEvil, 'gface').innerHTML) && /&lt;img/.test(gpart(gEvil, 'gface').innerHTML), 'a channel name is escaped in the dial label');
  const idleSt = { status: 'idle', message: null, demo: false, seq: 0, now: 0, since_last_sample: null, hz: null, hz_measured: null, seconds_left: null, adapter: {}, channels: {} };
  const g7 = makeEnv([idleSt], 'v0', OVF); await g7.tick();
  assert.strictEqual(gpart(gk(gbox(g7, [{ pid: '0C', form: 'dial' }]), '0C:dial'), 'gnote').textContent, 'not sampling');
  const g8 = await gOver({}, st => { st.channels['0D'] = { name: 'vehicle_speed', unit: 'km/h', samples: [] }; return st; });
  const wait = gk(gbox(g8, [{ pid: '0D', form: 'dial' }]), '0D:dial');
  assert.strictEqual(gpart(wait, 'gnote').textContent, 'waiting', 'in the run, no sample yet'); assert(!wait.className.includes('dim'));

  // PID table: today's All readings rows for any list of PIDs, in the given order (Review Focus 4)
  const pt = makeEnv(speedStates(true), 'v6', OVF, [], {}); for (let k = 0; k < 5; k++) await pt.tick();
  const PT = pt.parts(), tbl = PT.pidTableEl();
  assert.strictEqual(tbl.root.className, 'rwrap'); assert.strictEqual(tbl.root.children[0].className, 'rd');
  assert.deepStrictEqual(flat(tbl.root).trim().split(/\s+/), ['Reading', 'Now', 'Min', 'Max', 'Avg', 'Std', 'Samples'], 'the All readings header');
  PT.pidRows(tbl.body, []); assert.strictEqual(tbl.body.children.length, 0, 'an empty list: no rows');
  PT.pidRows(tbl.body, ['0D', '05', '0D']);
  assert.deepStrictEqual(tbl.body.children.map(c => c.getAttribute('data-key')), ['0D', '05'], 'in the given order, a repeat listed once');
  const tcells = (row) => row.children.map(c => flat(c).replace(/\s*\?$/, '').trim().replace(/\s+/g, ' '));
  assert.deepStrictEqual(tcells(tbl.body.children[0]), ['Vehicle speed (km/h)', '60', '0', '112.7', '50', '—', '9'], 'the same cells as All readings');
  const many = Array.from({ length: 64 }, (_, i) => (i + 0x20).toString(16).toUpperCase());
  PT.pidRows(tbl.body, many);
  assert.strictEqual(tbl.body.children.length, 64, '64 PIDs (the run-file maximum): 64 rows');
  assert.deepStrictEqual(tcells(tbl.body.children[0]).slice(1), ['—', '—', '—', '—', '—', '—'], 'a PID not in the run: dashes, not zeros');
  PT.pidRows(tbl.body, ['05']); assert.deepStrictEqual(tbl.body.children.map(c => c.getAttribute('data-key')), ['05'], 'shrinking drops the old rows');
  assert.strictEqual(pt.el('x_grid').children.filter(c => c.className === 'xr').length, 11, 'All readings is unchanged beside it');

  // stage-1 reviewer carry-overs: MAP range, LED bars light from the low end (trims centre on 0), the hook is optional, pidRows keeps its nodes
  const gm = (await gOver({ '0B': 180 })).parts().gaugeModel({ pid: '0B', form: 'dial' });
  assert(gm.hi >= 250, 'the MAP dial reaches 250 kPa (turbo, boost): ' + gm.hi); assert.strictEqual(gm.v, 180, 'a 180 kPa reading is shown as is, not clamped');
  const ledCls = (g) => (gpart(g, 'gface').innerHTML.match(/<i class="[^"]*"><\/i>/g) || []).map(x => x.match(/class="([^"]*)"/)[1]);
  const gm05 = (await gOver({ '05': 10 })), t05 = ledCls(gk(gbox(gm05, [{ pid: '05', form: 'bar' }]), '05:bar'));
  assert(t05[0] !== '' && !t05.some(c => /\bz\b/.test(c)), 'a temperature bar (metric, 10 C in -20..130) lights from cell 0 and has no zero marker: ' + t05.join('|'));
  const tUs = ledCls(gk(gbox(await gOver({ '05': 93.33 }, null, OVF, { 'shadetree.units': 'us' }), [{ pid: '05', form: 'bar' }]), '05:bar'));   // 200 F in -4..266 F
  assert(tUs[0] !== '' && tUs.some(c => c === '') && !tUs.some(c => /\bz\b/.test(c)), 'US units: 200 F lights from cell 0, no zero marker: ' + tUs.join('|'));
  assert.strictEqual(tUs.filter(c => c !== '').length, 16, 'and lights up to the value (cells 0..15 of 21)');
  const trimC = ledCls(gk(gbox(await gOver({ '07': 15 }), [{ pid: '07', form: 'bar' }]), '07:bar'));
  assert(trimC[0] === '' && trimC[10] !== '' && trimC.some(c => /\bz\b/.test(c)), 'a trim bar still centres on 0 and keeps its zero marker: ' + trimC.join('|'));
  assert(!gm.centre, 'a non-trim PID is not centred');
  assert.strictEqual((await gOver({ '07': 15 })).parts().gaugeModel({ pid: '07', form: 'bar' }).centre, true, 'a trim PID is centred');
  const noHook = makeEnv(speedStates(true), 'v0', OVF, [], {}, { noHook: true }); for (let k = 0; k < 5; k++) await noHook.tick();
  assert.strictEqual(noHook.parts(), null, 'no hook defined: nothing is exposed'); let noHookG = null; walk(noHook.el('d_panel'), n => { if (n.className === 'gauges') noHookG = n; });
  assert(noHookG && noHookG.children.length > 0, 'and the page still runs and draws its gauges');
  const rr = makeEnv(speedStates(true), 'v6', OVF, [], {}); for (let k = 0; k < 3; k++) await rr.tick();
  const rt = rr.parts().pidTableEl(); rr.parts().pidRows(rt.body, ['0D', '05']); const rows1 = Array.from(rt.body.children);
  rr.parts().pidRows(rt.body, ['0D', '05']); assert(rows1.length === 2 && rt.body.children.every((c, i) => c === rows1[i]), 'the same PID list twice keeps the row nodes');

  // Dashboard: scenario tabs (and the phone dropdown), up to 8 gauges, the run's PID table with the scenario's PIDs marked, the health strip only in General
  const dash = async (store = {}, page = {}, states = statesFor(30, base)) => {
    const e = makeEnv(states, 'v0', OVF, [], store, page); for (let k = 0; k < 32; k++) await e.tick(); return e;
  };
  const dGauges = (e) => { let g = null; walk(e.el('d_panel'), n => { if (n.className === 'gauges') g = n; }); return g.children; };
  const dRows = (e) => e.el('d_table').children[0].children[0].children[1].children;   // .rwrap > table > tbody > rows
  {
    const dStore = {}, e = await dash(dStore);
    const tabs = e.el('d_tabs').children;
    assert.deepStrictEqual(tabs.map(t => t.textContent), ['General', 'Fuel trims', 'Cooling', 'Idle / misfire', 'Charging / electrical']);
    assert.deepStrictEqual(tabs.map(t => t.getAttribute('data-scen')), ['general', 'fuel', 'cooling', 'idle', 'charging']);
    assert.strictEqual(tabs[0].className, 'stab is-active', 'General is the default');
    assert.strictEqual(e.el('d_sel').children.length, 5, 'the phone dropdown lists the same five');
    assert.strictEqual(e.el('d_sel').value, 'general');
    assert.strictEqual(dGauges(e).length, 8, 'General: 8 gauges');
    { const cb = e.el('clarity'); assert.ok(cb.on && cb.on.click, 'the Dashboard has the Clarity rocker and it is wired');
      cb.on.click(); await e.tick(); assert.strictEqual(cb.textContent, 'Clarity: max'); cb.on.click(); await e.tick(); assert.strictEqual(cb.textContent, 'Clarity: standard');
      assert.strictEqual(dGauges(e).length, 8, 'still 8 gauges after toggling Clarity'); }
    assert.strictEqual(flat(e.el('d_panel').children[0].children[0]).trim(), 'General', 'the panel is titled with the scenario');
    assert.deepStrictEqual(dRows(e).map(r => r.getAttribute('data-key')), Object.keys(base()).sort(), 'the table lists every PID in the run');
    assert.deepStrictEqual(dRows(e).filter(r => r.className.split(' ').includes('scen')).map(r => r.getAttribute('data-key')), ['04', '05', '06', '0B', '0C', '42'], "General's PIDs are marked");
    assert.strictEqual(e.el('d_strip').hidden, false, 'General shows the health strip');
    tabs[1].on.click(); await e.tick();
    assert.strictEqual(e.el('d_strip').hidden, true, 'Fuel trims hides the health strip');
    assert.strictEqual(dStore['shadetree.scenario'], 'fuel', 'the choice is remembered');
    assert.strictEqual(dGauges(e).length, 8, 'Fuel trims: 8 gauges');
    assert.strictEqual(e.el('d_tabs').children[1].className, 'stab is-active'); assert.strictEqual(e.el('d_sel').value, 'fuel');
    assert.deepStrictEqual(dRows(e).filter(r => r.className.split(' ').includes('scen')).map(r => r.getAttribute('data-key')), ['04', '06', '07', '08', '09', '0B', '0C'], 'the marks follow the scenario');
    e.el('d_sel').value = 'charging'; e.handlers['d_sel:change'](); await e.tick();
    assert.strictEqual(dGauges(e).length, 4, 'the dropdown switches too'); assert.strictEqual(dStore['shadetree.scenario'], 'charging');
    const cool = await dash({ 'shadetree.scenario': 'cooling' });
    assert.strictEqual(cool.el('d_strip').hidden, true, 'a stored scenario reopens'); assert.strictEqual(cool.el('d_sel').value, 'cooling', 'and the dropdown shows it');
    const mine = await dash({}, { scenarios: [{ id: 'general', name: 'Mine', gauges: [{ pid: '05', form: 'seven' }] }] });
    assert.strictEqual(mine.el('d_tabs').children[0].textContent, 'Mine', 'a server general replaces the built-in tab'); assert.strictEqual(mine.el('d_tabs').children.length, 5);
    assert.strictEqual(mine.el('d_strip').hidden, false, 'and General keeps the health strip'); assert.strictEqual(dGauges(mine).length, 1);
    const bad = await dash({ 'shadetree.scenario': 'nope' });
    assert.strictEqual(bad.el('d_sel').value, 'general', 'an unknown stored scenario opens General'); assert.strictEqual(bad.el('d_strip').hidden, false);
    const srv = await dash({ 'shadetree.scenario': 'towing' }, { scenarios: [{ id: 'towing', name: '<img onerror=x>', gauges: [{ pid: '0C', form: 'dial' }] }] });
    const evil = srv.el('d_tabs').children[5];
    assert.strictEqual(evil.textContent, '<img onerror=x>', 'a server scenario name is text'); assert.strictEqual(evil.children.length, 0, 'and makes no elements');
    assert.strictEqual(srv.el('d_sel').value, 'towing', 'a stored server scenario reopens once the server list arrives'); assert.strictEqual(dGauges(srv).length, 1);
    const off = await dash({ 'shadetree.scenario': 'towing' }, { scenariosFail: true });
    assert.strictEqual(off.el('d_tabs').children.length, 5, 'no server list: the built-ins'); assert.strictEqual(off.el('d_sel').value, 'general');
  }
  {   // gauge titles: a short name with no unit (the value line carries it); the old "Name (unit)" is the tooltip; other PIDs fall back to their name
    const NAMES = { '04': 'calculated_engine_load', '0D': 'vehicle_speed', '11': 'throttle_position', '0E': 'timing_advance', '0F': 'intake_air_temp', '44': 'commanded_equivalence_ratio', '99': 'some_very_long_reading_name' };
    const UNITS = { '04': '%', '0D': 'km/h', '11': '%', '0E': 'deg', '0F': 'C', '44': 'ratio', '99': '' };
    const named = statesFor(4, () => Object.assign(base(), { '0D': 40, '11': 12, '0E': 10, '0F': 30, '44': 1, '99': 3 }))
      .map(st => { for (const p in NAMES) Object.assign(st.channels[p], { name: NAMES[p], unit: UNITS[p] }); return st; });
    const gName = (g) => g.children[0].children[0];   // .gtop > .gname
    for (const sc of ['general', 'fuel', 'cooling', 'idle', 'charging']) for (const units of ['metric', 'us']) {
      const e = await dash({ 'shadetree.scenario': sc, 'shadetree.units': units }, {}, named);
      assert.ok(dGauges(e).length >= 4, sc);
      for (const g of dGauges(e)) {
        const nm = gName(g), t = nm.textContent, tip = nm.getAttribute('title') || '', tag = sc + ' ' + units + ' ' + g.getAttribute('data-key');
        assert.ok(t.length >= 3 && t.length <= 14 && !t.includes('('), tag + ' gauge title is short and has no unit: ' + t);
        assert.ok(tip.length > t.length || tip === t, tag + ' tooltip: ' + tip);
      }
    }
    const sp = await dash({ 'shadetree.scenario': 'general', 'shadetree.units': 'us' }, {}, named), spG = dGauges(sp).filter(g => g.getAttribute('data-key') === '0D:dial')[0];
    assert.strictEqual(gName(spG).textContent, 'Speed'); assert.strictEqual(gName(spG).getAttribute('title'), 'Vehicle speed (mph)', 'the tooltip has the full name and unit');
    assert.ok(spG.children.some(c => c.className === 'gval' && c.textContent === '25 mph'), 'the value line keeps the unit');
    const fb = await dash({ 'shadetree.scen.general': JSON.stringify([{ pid: '99', form: 'seven' }]) }, {}, named), fbN = gName(dGauges(fb)[0]);
    assert.strictEqual(fbN.textContent, 'Some very long reading name', 'a PID with no short title falls back to its name (the CSS ellipsis shortens it)');
    assert.strictEqual(fbN.getAttribute('title'), 'Some very long reading name'); assert.strictEqual(fbN.children.length, 0, 'text, not markup');
    const tbl = flat(sp.el('d_table')); assert.ok(/Vehicle speed \(mph\)/.test(tbl), 'the table keeps the full name and unit');
  }
  {   // the General health strip does not repeat the gauges: a tile hides when all its PIDs are gauges; Needs attention is unchanged
    const tileKeys = (e) => e.el('o_tiles').children.map(t => t.getAttribute('data-key'));
    const g = await dash();
    assert.deepStrictEqual(tileKeys(g), ['trims'], 'General: coolant, battery, load and MAP are gauges already, so only Fuel trims shows');
    assert.strictEqual(g.el('o_health').hidden, false, 'the Health heading shows while a tile does');
    const P = g.parts(), gaugesOf = (id) => P.BUILTIN.filter(s => s.id === id)[0].gauges, keys = (id) => Array.from(P.stripTiles(gaugesOf(id))).map(t => t.key);
    assert.deepStrictEqual(keys('general'), ['trims']);
    assert.deepStrictEqual(keys('cooling'), ['trims', 'map'], 'Cooling: coolant, load and battery are gauges');
    assert.deepStrictEqual(keys('idle'), ['trims', 'ect'], 'Idle has no coolant gauge, so the coolant tile stays; one trim gauge does not hide the trims tile');
    const cool = await dash({ 'shadetree.scen.general': JSON.stringify(gaugesOf('cooling')) });
    assert.deepStrictEqual(tileKeys(cool), ['trims', 'map'], 'an edited General follows its gauges');
    const all = await dash({ 'shadetree.scen.general': JSON.stringify(['06', '07', '08', '09', '05', '42', '04', '0B'].map(pid => ({ pid, form: 'seven' }))) });
    assert.deepStrictEqual(tileKeys(all), [], 'every tile is a gauge: no tiles'); assert.strictEqual(all.el('o_health').hidden, true, 'and the Health heading hides');
    const hot = await dash({}, {}, statesFor(30, () => Object.assign(base(), { '05': 118 })));
    assert.ok(!tileKeys(hot).includes('ect'), 'no coolant tile');
    assert.deepStrictEqual(hot.el('o_attn').children.map(c => c.getAttribute('data-key')), ['05'], 'a hot engine is still listed under Needs attention'); assert.strictEqual(hot.el('o_note').textContent, '');
    assert.strictEqual(g.el('o_note').textContent, 'No flags in the 6 readings assessed', 'the note still judges every health reading');
  }
  // Dashboard honesty: a PID not in the run is dimmed, never a zero; a run with no channels says so
  {
    const e = await dash();   // base() has no 0D, so General's speed gauge is dim and says why
    const dim = dGauges(e).filter(g => g.className.split(' ').includes('dim'));
    assert.ok(dim.length >= 1 && dim.some(g => g.getAttribute('data-key') === '0D:dial'));
    assert.ok(dim.every(g => g.children.some(c => c.className === 'gnote' && c.textContent === 'not in this run')));
    const idleD = makeEnv([{ status: 'idle', channels: {}, stats: {}, extras: {}, seq: 1 }], 'v0', OVF); await idleD.tick();
    assert.ok(dGauges(idleD).every(g => g.children.some(c => c.className === 'gnote' && c.textContent === 'not sampling')), 'no channels: not sampling');
  }
  // The #vp preview is gone and Guided test still updates
  {
    assert.ok(!/id="vp"/.test(html) && !/renderParts/.test(html), 'the #vp preview is removed');
    const e = makeEnv(statesFor(5, base), 'v3', OVF); await e.tick();
    assert.ok(/target|in range/.test(e.el('v3band').textContent));
  }

  // Scenario logic: five built-in sets, cleaning, server merge, pure edit operations
  const J = (x) => JSON.parse(JSON.stringify(x));
  {
    const e = makeEnv(statesFor(5, idle), 'v0', OVF); await e.tick();
    const P = e.parts();
    assert.deepStrictEqual(Array.from(P.BUILTIN).map(s => s.id), ['general', 'fuel', 'cooling', 'idle', 'charging']);
    P.BUILTIN.forEach(s => { assert.ok(s.gauges.length >= 1 && s.gauges.length <= 8); });
    const cl = J(P.cleanSpecs([
      { pid: '0c', form: 'bar' }, { pid: '0C', form: 'bar' }, { pid: 'constructor' }, { pid: '7' }, 5, null, { pid: '05', form: 'pie' },
      ...Array.from({ length: 10 }, (_, i) => ({ pid: '1' + i })) ]));
    assert.deepStrictEqual(cl.slice(0, 2), [{ pid: '0C', form: 'bar' }, { pid: '05', form: 'dial' }], 'lower-case is upper-cased, the repeat of pid+form is dropped, a bad form becomes dial');
    assert.strictEqual(cl.length, 8, 'capped at 8');
    assert.ok(!cl.some(g => g.pid === 'CO' || g.pid === '7'), 'non-hex and one-digit PIDs are dropped');
    const l = P.scenarioList([{ id: 'general', name: 'Mine', gauges: [{ pid: '05', form: 'seven' }] }, { id: 'towing', name: '<img onerror=x>', gauges: [{ pid: '0C' }] }]);
    assert.deepStrictEqual(Array.from(l).map(s => s.id), ['general', 'fuel', 'cooling', 'idle', 'charging', 'towing']);
    assert.strictEqual(l[0].name, 'Mine');
    assert.strictEqual(l[5].name, '<img onerror=x>', 'kept as data; the UI sets it with textContent');
    const s3 = [{ pid: '0C', form: 'dial' }, { pid: '05', form: 'dial' }];
    assert.deepStrictEqual(J(P.editAdd(s3, '04')).map(g => g.pid), ['0C', '05', '04']);
    assert.strictEqual(P.editAdd(s3, '0C').length, 2, 'already shown');
    const eight = Array.from({ length: 8 }, (_, i) => ({ pid: '0' + i, form: 'dial' }));
    assert.strictEqual(P.editAdd(eight, '0F'), eight, 'cap: unchanged, same array');
    assert.deepStrictEqual(J(P.editRemove(s3, 0)), [{ pid: '05', form: 'dial' }]);
    assert.strictEqual(P.editRemove([s3[0]], 0).length, 0, 'the last gauge can go');
    assert.deepStrictEqual(J(P.editMove(s3, 0, 1)).map(g => g.pid), ['05', '0C']);
    assert.deepStrictEqual(J(P.editMove(s3, 0, -1)).map(g => g.pid), ['0C', '05'], 'off the end: unchanged');
    const forms = []; let cur = [{ pid: '0C', form: 'dial' }];
    for (let k = 0; k < 3; k++) { cur = P.editForm(cur, 0); forms.push(cur[0].form); }
    assert.deepStrictEqual(forms, ['bar', 'seven', 'dial'], 'dial -> bar -> seven -> dial');
    assert.strictEqual(P.editForm([{ pid: '99', form: 'seven' }], 0)[0].form, 'seven', 'no range: stays seven');
  }
  // Saved scenarios survive corrupt or blocked storage
  {
    const store = { 'shadetree.scen.general': '{not json', 'shadetree.scen.fuel': JSON.stringify([{ pid: '0C', form: 'bar' }]),
                    'shadetree.scen.idle': JSON.stringify([{ pid: 'zz' }]) };
    const e = makeEnv(statesFor(5, idle), 'v0', OVF, [], store); await e.tick();
    const P = e.parts(), L = P.scenarioList([]);
    assert.deepStrictEqual(J(P.specsFor(L[0])), J(L[0].gauges), 'corrupt -> defaults');
    assert.deepStrictEqual(J(P.specsFor(L[1])), [{ pid: '0C', form: 'bar' }], 'valid -> used');
    assert.deepStrictEqual(J(P.specsFor(L[3])), J(L[3].gauges), 'all-invalid -> defaults');
    P.saveSaved('cooling', [{ pid: '05', form: 'bar' }], L[2].gauges);
    assert.ok(store['shadetree.scen.cooling']);
    P.saveSaved('cooling', L[2].gauges, L[2].gauges);
    assert.strictEqual(store['shadetree.scen.cooling'], undefined, 'equal to defaults: key removed');
    store['shadetree.scen.charging'] = '[]'; assert.deepStrictEqual(J(P.specsFor(L[4])), [], 'a saved empty list means no gauges');
    P.saveSaved('charging', [], L[4].gauges); assert.strictEqual(store['shadetree.scen.charging'], '[]', 'saving an empty edit stores it');
    store['shadetree.scen.charging'] = '{"a":1}'; assert.deepStrictEqual(J(P.specsFor(L[4])), J(L[4].gauges), 'a stored non-array -> defaults');
    const t = makeEnv(statesFor(5, idle), 'v0', OVF, [], {}, { storageThrows: true }); await t.tick();
    assert.doesNotThrow(() => { const Q = t.parts(); Q.specsFor(Q.scenarioList([])[0]); Q.saveSaved('x', [], [{ pid: '0C', form: 'dial' }]); }, 'blocked storage: defaults, no throw');
  }

  // 13) Edit mode (pencil): add from the PIDs in the run, remove, reorder, change form, Reset; saved per scenario
  {
    const mkEd = async (store, states = statesFor(30, base), ticks = 32) => {
      const e = makeEnv(states, 'v0', OVF, [], store); for (let k = 0; k < ticks; k++) await e.tick();
      const ed = () => { let b = null; walk(e.el('d_panel'), n => { if (n.id === 'd_editor') b = n; }); return b; };
      const rows = () => ed().children.filter(c => c.className === 'edrow' && c.children.length === 5);   // gauge rows (the controls row has 4)
      const ctl = (id) => { let r = null; walk(ed(), n => { if (n.id === id) r = n; }); return r; };
      const btn = (row, name) => row.children.filter(c => c.textContent === name)[0];
      const named = (name) => { let r = null; walk(ed(), n => { if (n.textContent === name && n.type !== undefined && n.children.length === 0 && n.className === 'qbtn') r = n; }); return r; };
      const press = async (n) => { assert.ok(n && !n.disabled, 'a pressable control'); n.on.click(); await e.tick(); };
      const saved = () => JSON.parse(store['shadetree.scen.general']);
      return { e, ed, rows, ctl, btn, named, press, saved, opts: () => ctl('d_add').children.map(o => o.value) };
    };
    const store = {}, E = await mkEd(store), e = E.e;
    assert.strictEqual(E.ed(), null, 'no editor before the pencil');
    // press the pencil: editor appears, aria-pressed true, one row per gauge, Add offers only PIDs in the run and not shown
    e.el('d_edit').on.click();
    assert.strictEqual(e.el('d_edit').getAttribute('aria-pressed'), 'true');
    assert.strictEqual(E.ed().hidden, false); assert.strictEqual(E.ed().id, 'd_editor');
    assert.strictEqual(E.rows().length, 8, 'one row per gauge');
    assert.ok(E.rows()[0].children[0].textContent.includes('(0C, dial)'), 'a row names the gauge: pid and form');
    assert.deepStrictEqual(E.rows()[0].children.slice(1).map(c => c.textContent), ['Up', 'Down', 'Form', 'Remove']);
    assert.deepStrictEqual(E.opts(), ['07', '08', '09'], 'Add offers PIDs in the run that are not shown (not 0D or 11: not in this run)');
    assert.strictEqual(E.ctl('d_addbtn').disabled, true, 'General already shows 8 gauges: Add is disabled');
    const row0 = E.rows()[0]; await e.tick(); await e.tick();
    assert.strictEqual(E.rows()[0], row0, 'the poll does not rebuild the editor');
    // press Remove on row 1: 7 gauges, store holds 7 specs
    await E.press(E.btn(E.rows()[0], 'Remove'));
    assert.strictEqual(dGauges(e).length, 7); assert.strictEqual(E.saved().length, 7); assert.strictEqual(E.rows().length, 7);
    assert.ok(!E.saved().some(g => g.pid === '0C'), 'the removed gauge is gone from the stored specs');
    assert.deepStrictEqual(E.opts(), ['07', '08', '09', '0C'], 'a removed PID in the run can be added back');
    // press Form on row 1: its form changed in the stored specs
    assert.deepStrictEqual(E.saved()[0], { pid: '0D', form: 'dial' });
    await E.press(E.btn(E.rows()[0], 'Form'));
    assert.deepStrictEqual(E.saved()[0], { pid: '0D', form: 'bar' }, 'dial -> bar'); assert.ok(E.rows()[0].children[0].textContent.includes('bar'));
    // press Up on row 2: order changed in the stored specs
    assert.deepStrictEqual(E.saved().map(g => g.pid).slice(0, 2), ['0D', '05']);
    await E.press(E.btn(E.rows()[1], 'Up'));
    assert.deepStrictEqual(E.saved().map(g => g.pid).slice(0, 2), ['05', '0D'], 'moved up');
    assert.deepStrictEqual(Array.from(dGauges(e)).map(g => g.getAttribute('data-key')).slice(0, 2), ['05:dial', '0D:bar'], 'the gauges follow the order');
    await E.press(E.btn(E.rows()[0], 'Down'));
    assert.deepStrictEqual(E.saved().map(g => g.pid).slice(0, 2), ['0D', '05'], 'moved down');
    // choose a PID in d_add and press Add: 8 gauges again; with 8 gauges the Add button is disabled and d_add empty
    E.ctl('d_add').value = '07'; await E.press(E.ctl('d_addbtn'));
    assert.strictEqual(dGauges(e).length, 8); assert.strictEqual(E.saved().length, 8); assert.strictEqual(E.saved()[7].pid, '07', 'added at the end');
    assert.strictEqual(E.ctl('d_addbtn').disabled, true, 'at 8 gauges Add is disabled');
    E.ctl('d_add').value = '08'; E.ctl('d_addbtn').on.click(); await e.tick(); assert.strictEqual(dGauges(e).length, 8, 'and a click adds nothing'); assert.strictEqual(E.saved().length, 8);
    // press Reset: store key removed, 8 default gauges
    await E.press(E.named('Reset'));
    assert.strictEqual(store['shadetree.scen.general'], undefined, 'Reset removes the saved key');
    assert.strictEqual(dGauges(e).length, 8); assert.strictEqual(E.rows().length, 8);
    assert.deepStrictEqual(Array.from(dGauges(e)).map(g => g.getAttribute('data-key')).slice(0, 3), ['0C:dial', '0D:dial', '05:dial'], 'the defaults are back');
    // remove all gauges: the panel body says 'No gauges. Add one or Reset.' and Add and Reset still work
    for (let k = 0; k < 8; k++) await E.press(E.btn(E.rows()[0], 'Remove'));
    assert.strictEqual(dGauges(e).length, 0); assert.strictEqual(store['shadetree.scen.general'], '[]', 'an empty set is stored');
    assert.ok(flat(e.el('d_panel')).includes('No gauges. Add one or Reset.'));
    assert.strictEqual(E.rows().length, 0); assert.strictEqual(E.opts().length, 9, 'all nine PIDs in the run can be added');
    E.ctl('d_add').value = '0C'; await E.press(E.ctl('d_addbtn'));
    assert.strictEqual(dGauges(e).length, 1); assert.ok(!flat(e.el('d_panel')).includes('No gauges.'), 'the message goes once there is a gauge');
    await E.press(E.btn(E.rows()[0], 'Remove')); assert.ok(flat(e.el('d_panel')).includes('No gauges.'));
    await E.press(E.named('Reset'));
    assert.strictEqual(dGauges(e).length, 8); assert.strictEqual(store['shadetree.scen.general'], undefined);
    // press Done: editor gone, aria-pressed false; reload (new makeEnv with the same store) shows the saved set
    await E.press(E.btn(E.rows()[0], 'Remove')); await E.press(E.named('Done'));
    assert.strictEqual(E.ed().hidden, true, 'the editor is gone'); assert.strictEqual(E.ed().children.length, 0);
    assert.strictEqual(e.el('d_edit').getAttribute('aria-pressed'), 'false'); assert.strictEqual(dGauges(e).length, 7, 'Done keeps the edit');
    const E2 = await mkEd(store); assert.strictEqual(dGauges(E2.e).length, 7, 'reload shows the saved set'); assert.ok(!flat(E2.e.el('d_panel')).includes('No gauges.'));
    E2.e.el('d_edit').on.click();   // remove the rest, reload: still empty
    for (let k = 0; k < 7; k++) await E2.press(E2.btn(E2.rows()[0], 'Remove'));
    const E3 = await mkEd(store); assert.strictEqual(dGauges(E3.e).length, 0, 'an emptied scenario reloads empty'); assert.ok(flat(E3.e.el('d_panel')).includes('No gauges. Add one or Reset.'));
    E3.e.el('d_edit').on.click(); await E3.press(E3.named('Reset')); assert.strictEqual(dGauges(E3.e).length, 8); assert.strictEqual(store['shadetree.scen.general'], undefined);
    // switch scenario while editing: editor closes
    E3.e.el('d_tabs').children[1].on.click(); await E3.e.tick();
    assert.strictEqual(E3.ed().hidden, true, 'switching ends edit mode'); assert.strictEqual(E3.e.el('d_edit').getAttribute('aria-pressed'), 'false');
    E3.e.el('d_edit').on.click(); assert.strictEqual(E3.rows().length, 8, "the next edit starts from the new scenario's gauges"); assert.ok(E3.rows()[0].children[0].textContent.includes('(06, bar)'));
    // the pencil pressed twice closes the editor: hidden, no rows, aria-pressed false
    E3.e.el('d_edit').on.click();
    assert.strictEqual(E3.e.el('d_edit').getAttribute('aria-pressed'), 'false'); assert.strictEqual(E3.ed().hidden, true, 'pencil off hides the editor'); assert.strictEqual(E3.ed().children.length, 0, 'and clears its rows');
    // the editor follows the PIDs in the run when they change
    const more = statesFor(20, base).concat(statesFor(30, () => Object.assign(base(), { '10': 5 }), 20, 8));
    const E4 = await mkEd({}, more, 10); E4.e.el('d_edit').on.click();
    assert.ok(!E4.opts().includes('10')); for (let k = 0; k < 20; k++) await E4.e.tick();
    assert.ok(E4.opts().includes('10'), 'a PID that appears in the run is offered');
    // buttons that cannot act are disabled: Up on the first row, Down on the last, Form on a PID with no gauge range
    assert.strictEqual(E4.btn(E4.rows()[0], 'Up').disabled, true, 'Up on the first row'); assert.strictEqual(E4.btn(E4.rows()[1], 'Up').disabled, false);
    assert.strictEqual(E4.btn(E4.rows()[7], 'Down').disabled, true, 'Down on the last row'); assert.strictEqual(E4.btn(E4.rows()[0], 'Down').disabled, false);
    assert.ok(E4.rows().every(r => r.children[3].disabled === false), 'every General PID has a range: Form works');
    await E4.press(E4.btn(E4.rows()[0], 'Remove')); E4.ctl('d_add').value = '10'; await E4.press(E4.ctl('d_addbtn'));
    const lastR = E4.rows()[7]; assert.ok(lastR.children[0].textContent.includes('(10, seven)'));
    assert.strictEqual(E4.btn(lastR, 'Form').disabled, true, 'Form on a PID with no range'); assert.strictEqual(E4.btn(lastR, 'Down').disabled, true);
    assert.strictEqual(E4.btn(E4.rows()[6], 'Down').disabled, false, 'Down on a middle row'); assert.strictEqual(E4.btn(E4.rows()[6], 'Form').disabled, false);
    // the editor's controls sit together in one row; the Add list is styled like the other selects
    const ctlRow = E4.ed().children[E4.ed().children.length - 1];
    assert.strictEqual(ctlRow.className, 'edrow'); assert.deepStrictEqual(ctlRow.children.map(c => c.id !== 'new' ? c.id : c.textContent), ['d_add', 'd_addbtn', 'Reset', 'Done']);
    assert.strictEqual(E4.ctl('d_add').className, 'b', 'the Add list is a styled select');
    assert.ok(/<select class="b ssel" id="d_sel"/.test(html), 'the scenario dropdown is a styled select');
    assert.ok(/@media \(max-width: 600px\) \{ \.edrow \{ flex-wrap: wrap; \}/.test(html), 'edit rows wrap on a phone');
    assert.ok(/\.qbtn\[aria-pressed="true"\]/.test(html), 'the pencil shows when it is on');
    // no readings yet: the editor and the table both say so
    const emp = makeEnv([{ status: 'idle', channels: {}, stats: {}, extras: {}, seq: 1 }], 'v0', OVF); await emp.tick();
    assert.ok(flat(emp.el('d_table')).includes('No readings yet'), 'the table says so');
    emp.el('d_edit').on.click(); let edE = null; walk(emp.el('d_panel'), n => { if (n.id === 'd_editor') edE = n; });
    assert.ok(flat(edE).includes('Start sampling or load a replay to add readings'), 'the editor says so');
    assert.ok(!flat(E4.e.el('d_table')).includes('No readings yet'), 'and only when the run is empty');
  }

  // Phone Menu: a real button toggles a menu-open class on the topbar (CSS collapses the tabs, chips and controls behind it at phone width); a view pick closes it
  {
    const mkBtns = () => ['v0', 'v3', 'v5', 'v6'].map(v => { const b = makeNode('vb_' + v, {}); b.dataset.view = v; return b; });
    const vb = mkBtns(), m = makeEnv(statesFor(2, idle), 'v0', OVF, [], {}, { narrow: true, vbtns: vb }); await m.tick();
    const top = m.el('topbar'), btn = m.el('menuBtn'), open = () => top.className.split(' ').includes('menu-open');
    assert.ok(/<button type="button"[^>]*id="menuBtn"[^>]*aria-expanded="false"[^>]*aria-controls="[^"]+"[^>]*>Menu<\/button>/.test(html), 'a real Menu button, collapsed, with aria-controls');
    assert.ok(/<header class="topbar" id="topbar">\s*<div class="brand">[^<]*<\/div>\s*<button[^>]*id="menuBtn"/.test(html), 'the Menu button sits next to the brand');
    assert.ok(btn.on.click, 'Menu is wired'); assert.ok(!open(), 'collapsed by default');
    btn.on.click(); assert.ok(open(), 'tapping opens'); assert.strictEqual(btn.getAttribute('aria-expanded'), 'true');
    btn.on.click(); assert.ok(!open(), 'tapping again closes'); assert.strictEqual(btn.getAttribute('aria-expanded'), 'false');
    btn.on.click(); vb[2].on.click(); assert.ok(!open(), 'picking a view closes the menu'); assert.strictEqual(btn.getAttribute('aria-expanded'), 'false');
    assert.ok(vb[2].className.includes('is-active'), 'and navigates');
    // Handheld: the Menu stays (the topbar is not hidden there), and opening it reaches the view tabs
    const hv = mkBtns(), h = makeEnv(statesFor(2, idle), 'v5', OVF, [], { 'shadetree.skin': 'retro' }, { narrow: true, vbtns: hv, search: '?example=x.json' }); await h.tick();
    h.el('menuBtn').on.click(); assert.ok(h.el('topbar').className.includes('menu-open'), 'Handheld: Menu opens');
    hv[0].on.click(); assert.ok(hv[0].className.includes('is-active') && !h.el('topbar').className.includes('menu-open'), 'Handheld: Dashboard is one tap away from the menu');
    // desktop: nothing in the script depends on width, the CSS hides the button
    const dk = makeEnv(statesFor(2, idle), 'v0', OVF, [], {}, { narrow: false, vbtns: mkBtns() }); await dk.tick();
    assert.ok(!dk.el('topbar').className.includes('menu-open'), 'desktop: nothing collapsed or opened');
  }

  // 14) Lamps strip and Codes panel on the Dashboard
  {
    const byId = (e, root, id) => { let r = null; walk(e.el(root), n => { if (n.id === id) r = n; }); return r; };
    const cd = (codes, status = 'running') => statesFor(6, base).map(st => Object.assign(st, { status, codes }));
    const e = makeEnv(cd({ read: true, note: null, mil: true, stored: [{ code: 'P0171', desc: 'System too lean <b>x</b>', hint: 'check <i>air</i>' }], pending: [], permanent: [] }), 'v0', OVF);
    for (let k = 0; k < 6; k++) await e.tick();
    const m = e.parts().lampModel();
    assert.deepStrictEqual(Array.from(m).map(x => x.id), ['mil', 'ltft1', 'ltft2', 'ect', 'samp']);
    assert.strictEqual(m[0].on, true); assert.strictEqual(m[0].e, 'ON'); assert.strictEqual(m[4].e, 'simulated · 2.5 Hz');
    assert.ok(byId(e, 'd_codes_mount', 'd_cnt'), 'the count window is on the Dashboard');
    const codes = byId(e, 'd_codes_mount', 'd_codes');
    assert.ok(/P0171/.test(codes.innerHTML));
    assert.ok(!/<b>x<\/b>/.test(codes.innerHTML) && /&lt;b&gt;x&lt;\/b&gt;/.test(codes.innerHTML), 'description escaped');
    assert.ok(/&lt;i&gt;air&lt;\/i&gt;/.test(codes.innerHTML), 'hint escaped');
    assert.ok(/<i class="lens red"><\/i><div><b>Check engine \(MIL\)<\/b>/.test(e.el('d_lamps').innerHTML) && /lampbox lit/.test(e.el('d_lamps').innerHTML), 'the strip is drawn, MIL lit');
    const idleE = makeEnv([{ status: 'idle', channels: {}, stats: {}, extras: {}, seq: 1, codes: { read: false, note: null } }], 'v0', OVF); await idleE.tick();
    assert.ok(/START SAMPLING TO READ CODES/.test(byId(idleE, 'd_codes_mount', 'd_codes').innerHTML));
    const mi = idleE.parts().lampModel(); assert.strictEqual(mi[0].e, 'unknown'); assert.strictEqual(mi[4].e, 'not sampling');
    const none = makeEnv(cd({ read: true, note: null, mil: false, stored: [], pending: [], permanent: [] }), 'v0', OVF); for (let k = 0; k < 6; k++) await none.tick();
    assert.ok(/NO CODES STORED/.test(byId(none, 'd_codes_mount', 'd_codes').innerHTML)); assert.strictEqual(none.parts().lampModel()[0].e, 'off');
    const lean = makeEnv(statesFor(6, () => ({ '0C': 700, '05': 40, '06': 2, '07': 14, '08': 2, '09': -13 })), 'v0', OVF); for (let k = 0; k < 6; k++) await lean.tick();
    const ml = lean.parts().lampModel();
    assert.ok(ml[1].on && ml[1].e === 'LEAN 14.0 %: watch', 'trim above +10 lights LTFT 1, as the gauge says watch'); assert.ok(ml[2].on && /RICH/.test(ml[2].e), 'trim below -10 lights LTFT 2');
    assert.ok(!ml[3].on && ml[3].e === 'normal', 'coolant follows the shared range (this fixture has no low bound; the shipped one flags 40 C, see 19)');
  }

  {   // a stale #v4 (the removed Analyzer): the page has no such id, so the fragment is ignored and the Dashboard stays the only active view
    const views = ['v0', 'v3', 'v5', 'v6'].map(id => { const v = makeNode(id, {}); v.className = id === 'v0' ? 'view is-active' : 'view'; return v; });
    const st = makeEnv(statesFor(4, base), 'v0', OVF, [], {}, { hash: '#v4', absent: ['v4'], views });
    for (let k = 0; k < 4; k++) await st.tick();
    assert.deepStrictEqual(views.filter(v => v.className.split(' ').includes('is-active')).map(v => v.id), ['v0'], 'the Dashboard is still the one active view');
    assert.ok(/SIMULATED/.test(st.el('chipLive').innerHTML) && st.el('d_lamps').innerHTML.includes('Check engine'), 'and it renders');
    const good = ['v0', 'v3', 'v5', 'v6'].map(id => { const v = makeNode(id, {}); v.className = id === 'v0' ? 'view is-active' : 'view'; return v; });
    makeEnv(statesFor(1, base), 'v0', OVF, [], {}, { hash: '#v5', views: good });
    assert.deepStrictEqual(good.filter(v => v.className.split(' ').includes('is-active')).map(v => v.id), ['v5'], 'a real #v5 still opens Handheld (the harness can see a switch)');
  }

  {   // 17) pickView and the opening view: a phone opens Handheld, a desktop the Dashboard, a known hash wins, nothing is stored
    const P = makeEnv(statesFor(3, base), 'v0', OVF).parts();
    assert.strictEqual(P.pickView('', false), 'v0');
    assert.strictEqual(P.pickView('', true), 'v5');
    assert.strictEqual(P.pickView('#v6', true), 'v6');
    assert.strictEqual(P.pickView('v3', false), 'v3');
    assert.strictEqual(P.pickView('v4', true), 'v5', 'the removed view falls through to the default');
    assert.strictEqual(P.pickView('#vp', false), 'v0'); assert.strictEqual(P.pickView('nonsense', false), 'v0');
    const open = async (page, store = {}) => {
      const mk = () => ['v0', 'v3', 'v5', 'v6'].map(id => { const v = makeNode(id, {}); v.className = 'view'; return v; });
      const views = mk(), vbtns = ['v0', 'v3', 'v5', 'v6'].map(id => { const b = makeNode('vb_' + id, {}); b.dataset.view = id; return b; });
      const e = makeEnv(statesFor(3, base), 'v0', OVF, [], store, Object.assign({ views, vbtns }, page));
      await e.tick();
      const act = () => views.filter(v => v.className.split(' ').includes('is-active')).map(v => v.id);
      return { e, act, tabs: () => vbtns.filter(b => b.className.split(' ').includes('is-active')).map(b => b.dataset.view), store };
    };
    const ph = await open({ narrow: true });
    assert.deepStrictEqual(ph.act(), ['v5'], 'a phone with no hash opens Handheld'); assert.deepStrictEqual(ph.tabs(), ['v5'], 'and its tab');
    assert.strictEqual(ph.e.el('h_livepane').hidden, false, 'on the Live pane');
    assert.deepStrictEqual((await open({ narrow: true, hash: '#v0' })).act(), ['v0'], 'a phone with #v0 opens the Dashboard');
    assert.deepStrictEqual((await open({ narrow: true, hash: '#v4' })).act(), ['v5'], 'a stale #v4 on a phone falls to Handheld');
    assert.deepStrictEqual((await open({ narrow: false })).act(), ['v0'], 'a desktop opens the Dashboard');
    const dx = await open({ narrow: false, search: '?example=x.json' });
    assert.deepStrictEqual(dx.act(), ['v0'], '?example= alone does not change a desktop view'); assert.strictEqual(dx.e.posts.length, 1, 'and the replay still starts');
    assert.deepStrictEqual((await open({ narrow: true, search: '?example=x.json' })).act(), ['v5'], '?example= on a phone opens Handheld');
    const sv = await open({ narrow: true }, { 'shadetree.scenario': 'cooling' });
    assert.strictEqual(sv.e.el('d_sel').value, 'cooling', 'a stored scenario still wins on a phone'); assert.deepStrictEqual(Object.keys(sv.store), ['shadetree.scenario'], 'the opening view is not stored');
    const rz = await open({ narrow: true });
    rz.e.sandbox.window.matchMedia = () => ({ matches: false });
    assert.ok((rz.e.winH.resize || []).length, 'the page listens for resize'); rz.e.winH.resize.forEach(f => f());
    assert.deepStrictEqual(rz.act(), ['v5'], 'a resize after load does not switch views');
    const noMq = await open({}); assert.deepStrictEqual(noMq.act(), ['v0'], 'no matchMedia: not narrow, Dashboard');
  }

  {   // every code is a row in the Dashboard list (the CSS scrolls it; nothing is dropped here)
    const six = [1, 2, 3, 4, 5, 6].map(n => ({ code: 'P010' + n, desc: 'desc ' + n, hint: 'hint ' + n }));
    const e6 = makeEnv(statesFor(6, base).map(st => Object.assign(st, { codes: { read: true, note: null, mil: true, stored: six, pending: [], permanent: [] } })), 'v0', OVF);
    for (let k = 0; k < 6; k++) await e6.tick();
    let l6 = null; walk(e6.el('d_codes_mount'), n => { if (n.id === 'd_codes') l6 = n; });
    assert.strictEqual((l6.innerHTML.match(/class="crow"/g) || []).length, 6, 'six codes, six rows');
    assert.strictEqual((l6.innerHTML.match(/class="chint"/g) || []).length, 6, 'each with its hint');
  }

  {   // 15) Handheld: Live (lamps, the scenario's gauges, the full PID table) and Codes, opening on Live; its scenario dropdown and the Dashboard's follow each other
    const hhE = async (store = {}, states = statesFor(6, base)) => { const e = makeEnv(states, 'v5', OVF, [], store); for (let k = 0; k < states.length; k++) await e.tick(); return e; };
    const btn = (e, m) => e.hhBtns.find(b => b.dataset.mode === m), on = (b) => b.className.split(' ').includes('on');
    const hRows = (e) => e.el('h_table').children[0].children[0].children[1].children;   // .rwrap > table > tbody > rows
    const hKeys = (e) => e.el('h_gauges').children.map(g => g.getAttribute('data-key'));
    const hStore = {}, e = await hhE(hStore);
    assert.deepStrictEqual(e.hhBtns.map(b => b.dataset.mode), ['live', 'codes'], 'two modes: Live, Codes');
    assert.strictEqual(e.el('h_livepane').hidden, false, 'opens on Live'); assert.strictEqual(e.el('h_codes').hidden, true, 'Codes starts hidden');
    assert.ok(on(btn(e, 'live')) && !on(btn(e, 'codes')), 'the Live button is lit');
    btn(e, 'codes').on.click();
    assert.ok(e.el('h_livepane').hidden && !e.el('h_codes').hidden, 'Codes shows the codes and hides Live'); assert.ok(on(btn(e, 'codes')) && !on(btn(e, 'live')));
    btn(e, 'live').on.click(); assert.ok(!e.el('h_livepane').hidden && e.el('h_codes').hidden, 'and Live comes back');
    assert.deepStrictEqual(e.el('h_sel').children.map(o => o.value), ['general', 'fuel', 'cooling', 'idle', 'charging'], 'the dropdown lists the five scenarios');
    assert.strictEqual(e.el('h_sel').value, 'general');
    assert.strictEqual(e.el('h_gauges').children.length, 8, 'General: 8 gauges');
    assert.deepStrictEqual(hRows(e).map(r => r.getAttribute('data-key')), Object.keys(base()).sort(), 'the table lists every PID in the run');
    const dim = e.el('h_gauges').children.filter(g => g.getAttribute('data-key') === '0D:dial')[0];   // base() has no 0D
    assert.ok(dim && dim.className.split(' ').includes('dim') && dim.children.some(c => c.className === 'gnote' && c.textContent === 'not in this run'), 'a PID not in the run is a dim gauge that says so');
    assert.ok(/Check engine \(MIL\)/.test(e.el('h_lamps').innerHTML), 'the Lamps strip is drawn');
    e.el('h_sel').value = 'fuel'; e.handlers['h_sel:change'](); await e.tick();
    assert.strictEqual(hStore['shadetree.scenario'], 'fuel', 'the choice is remembered'); assert.strictEqual(e.el('d_sel').value, 'fuel', "the Dashboard's dropdown follows");
    assert.strictEqual(hKeys(e)[0], '06:bar', "Fuel trims' gauges"); assert.strictEqual(hKeys(e).length, 8);
    e.el('d_sel').value = 'charging'; e.handlers['d_sel:change'](); await e.tick();
    assert.strictEqual(e.el('h_sel').value, 'charging', "and the Handheld's follows the Dashboard's"); assert.strictEqual(hKeys(e).length, 4);
    assert.ok(!/aria-pressed|d_edit/.test(html.slice(html.indexOf('id="v5"'), html.indexOf('id="v6"'))), 'no gauge editing in the Handheld');
    const emp = await hhE({ 'shadetree.scen.general': '[]' });
    assert.strictEqual(emp.el('h_gauges').children.length, 0, 'an emptied scenario draws no gauges'); assert.strictEqual(hRows(emp).length, Object.keys(base()).length, 'and the table still lists the run');
    const gNote = (x) => { let r = null; walk(x.el('h_livepane'), n => { if (n.className === 'note') r = n; }); return r; };
    assert.ok(gNote(emp) && !gNote(emp).hidden && gNote(emp).textContent === 'No gauges in this scenario. Edit it on the Dashboard.', 'an emptied scenario says so');
    assert.ok(gNote(e) && gNote(e).hidden && gNote(e).textContent === '', 'a scenario with gauges has no note');
    assert.ok(!flat(e.el('h_table')).includes('No readings yet'), 'a run with channels has no empty-table note');
    const none = makeEnv([{ status: 'idle', channels: {}, stats: {}, extras: {}, seq: 1 }], 'v5', OVF); await none.tick();
    assert.strictEqual(hRows(none).length, 0, 'no channels: the table body is empty'); assert.ok(flat(none.el('h_table')).includes('No readings yet.'), 'and the table says so');
    assert.ok(none.el('h_gauges').children.every(g => g.children.some(c => c.className === 'gnote' && c.textContent === 'not sampling')), 'and the gauges say not sampling');
    // the table's heading is a button that says how many readings there are and scrolls to them
    assert.ok(/<button type="button" class="hh-tbl" id="h_tblbtn" aria-controls="h_table">All readings &#9662;<\/button>\s*<div id="h_table"><\/div>/.test(html), 'a real button right above the table');
    assert.strictEqual(e.el('h_tblbtn').textContent, 'All readings (' + Object.keys(base()).length + ') ▾', 'it counts the readings in the run');
    assert.strictEqual(e.el('h_tblbtn').children.length, 0, 'text, not markup');
    assert.strictEqual(none.el('h_tblbtn').textContent, 'All readings ▾', 'no readings: no count, and the table note says so');
    const grow = makeEnv([{ status: 'idle', channels: {}, stats: {}, extras: {}, seq: 0 }].concat(statesFor(3, base)), 'v5', OVF); await grow.tick();
    assert.strictEqual(grow.el('h_tblbtn').textContent, 'All readings ▾');
    for (let k = 0; k < 3; k++) await grow.tick();
    assert.strictEqual(grow.el('h_tblbtn').textContent, 'All readings (' + Object.keys(base()).length + ') ▾', 'the count follows the run');
    const calls = []; e.el('h_table').scrollIntoView = (o) => calls.push(JSON.stringify(o));
    e.el('h_tblbtn').on.click(); assert.deepStrictEqual(calls, ['{"block":"start"}'], 'a tap scrolls the table into view');
    none.el('h_tblbtn').on.click();   // no scrollIntoView on this node: guarded, no throw
  }

  {   // 16) a replay file's codes note is text, never markup, on the Dashboard and the Handheld
    const noteEnv = async (note, view) => { const e = makeEnv(statesFor(3, base).map(st => Object.assign(st, { codes: { read: false, note } })), view, OVF); for (let k = 0; k < 3; k++) await e.tick(); return e; };
    const dCodes = (e) => { let r = null; walk(e.el('d_codes_mount'), n => { if (n.id === 'd_codes') r = n; }); return r.innerHTML; };
    for (const [note, tag, shown] of [['<img src=x onerror=1>', /<img/i, '&lt;IMG'], ['<a href=//evil.example>tap</a>', /<a[\s>]/i, '&lt;A HREF']]) {
      const d = dCodes(await noteEnv(note, 'v0')), h = (await noteEnv(note, 'v5')).el('h_codes').innerHTML;
      assert.ok(!tag.test(d) && d.includes(shown), 'Dashboard codes note escaped: ' + d);
      assert.ok(!tag.test(h) && h.includes(shown), 'Handheld codes note escaped: ' + h);
    }
  }

  {   // 17) the page's notices (demo, replay, server/adapter message, example note) are repeated inside the Handheld frame, as text
    const quiet = (st) => Object.assign(st, { demo: false });
    const alertEnv = async (states, page = {}, seed) => { const e = makeEnv(states, 'v5', OVF, [], {}, page); if (seed) seed(e); for (let k = 0; k < 3; k++) await e.tick(); return e.el('h_alert'); };
    const demoText = html.match(/id="demoBanner" hidden>([^<]*)</)[1];
    const demo = await alertEnv(statesFor(3, base), {}, (e) => { e.el('demoBanner').textContent = demoText; });
    assert.ok(!demo.hidden && demo.textContent.includes('simulated engine, no car connected'), 'demo: ' + demo.textContent);
    const rep = await alertEnv(statesFor(3, base).map(st => Object.assign(quiet(st), { replay: { name: 'run.json', playing: true, ended: false, speed: 1, pos: 1, duration: 10 } })));
    assert.ok(!rep.hidden && rep.textContent.includes('Replay: run.json · recorded car, not live'), 'replay: ' + rep.textContent);
    const ex = await alertEnv(statesFor(3, base).map(quiet), { search: '?t=abc&example=x.json', postReply: (url) => (/\/api\/replay/.test(url) ? { ok: false, status: 404, j: { error: 'no' } } : null) });
    assert.ok(!ex.hidden && ex.textContent.includes('Example not found: x.json'), 'example: ' + ex.textContent);
    const msg = await alertEnv(statesFor(3, base).map(st => Object.assign(quiet(st), { message: 'Adapter <b>lost</b>' })));
    assert.ok(!msg.hidden && msg.textContent.includes('Adapter <b>lost</b>') && msg.children.length === 0 && msg.innerHTML === '', 'a message is text, never markup: ' + msg.textContent);
    const none = await alertEnv(statesFor(3, base).map(quiet));
    assert.strictEqual(none.hidden, true, 'no notices: the alert is hidden');
  }

  {   // 18) dial scale labels land on round numbers in the displayed unit, in metric and US, for every gauge
    const nt = (P, lo, hi, majors, div) => { const r = P.niceTicks(lo, hi, majors, div); return { step: r.step, dec: r.dec, values: Array.from(r.values), minors: Array.from(r.minors) }; };
    const P = (await gOver({})).parts();
    const labels = (r) => r.values.map(v => v.toFixed(r.dec));
    assert.deepStrictEqual(labels(nt(P, 0, 124.27, 5, 1)), ['0', '25', '50', '75', '100'], 'speed mph: one 3-character label at the end does not crowd');
    assert.deepStrictEqual(labels(nt(P, 0, 200, 5, 1)), ['0', '100', '200'], 'speed km/h: no two 3-character labels side by side beyond 4 labels');
    assert.deepStrictEqual(labels(nt(P, -4, 266, 5, 1)), ['0', '100', '200'], 'coolant F: 3-digit labels, at most 4');
    assert.deepStrictEqual(labels(nt(P, -20, 130, 5, 1)), ['0', '50', '100'], 'coolant C');
    assert.deepStrictEqual(labels(nt(P, 0, 73.8, 6, 1)), ['0', '20', '40', '60'], 'MAP inHg');
    assert.deepStrictEqual(labels(nt(P, 0, 250, 6, 1)), ['0', '100', '200'], 'MAP kPa');
    assert.deepStrictEqual(labels(nt(P, 10, 16, 6, 1)), ['10', '12', '14', '16'], 'voltage: 2-character labels, at most 5');
    assert.deepStrictEqual(labels(nt(P, 0, 7000, 7, 1000)), ['0', '1', '2', '3', '4', '5', '6', '7'], 'tach x1000: 1-character labels keep 8');
    assert.deepStrictEqual(labels(nt(P, -25, 25, 5, 1)), ['-25', '0', '25'], 'trims: a minus sign counts as a character');
    assert.deepStrictEqual(labels(nt(P, -20, 50, 7, 1)), ['-20', '0', '20', '40'], 'spark advance');
    assert.deepStrictEqual(labels(nt(P, 0.5, 1.5, 5, 1)), ['0.5', '1.0', '1.5'], 'lambda: no float noise');
    const capOf = (ls) => {   // the label-width cap: 4 where two neighbouring labels are both 3+ characters, 5 where any label is 2+, else 7+
      let both3 = false; for (let i = 1; i < ls.length; i++) if (ls[i - 1].length >= 3 && ls[i].length >= 3) both3 = true;
      return both3 ? 4 : ls.some(l => l.length >= 2) ? 5 : Infinity;
    };
    const units = { '0C': 'rpm', '0D': 'km/h', '05': '°C', '04': '%', '11': '%', '0B': 'kPa', '42': 'V', '06': '%', '07': '%', '08': '%', '09': '%', '0E': '°', '0F': '°C', '44': '' };
    const withChannels = (st) => { for (const pid in units) st.channels[pid] = { name: 'ch' + pid, unit: units[pid], samples: [[st.seq, st.now, 1]] }; return st; };
    for (const unitSys of ['metric', 'us']) {
      const e = await gOver({}, withChannels, OVF, { 'shadetree.units': unitSys }), Q = e.parts();
      for (const pid in units) {
        const m = Q.gaugeModel({ pid, form: 'dial' }), r = nt(Q, m.lo, m.hi, m.majors, m.div), tag = pid + ' ' + unitSys + ' [' + m.lo + ', ' + m.hi + ']';
        assert.ok(r.values.length >= 3 && r.values.length <= Math.max(7, m.majors + 1), tag + ' label count ' + r.values.length);
        assert.ok(r.values.length <= capOf(labels(r)), tag + ' labels crowd: ' + labels(r).join(' '));
        for (const v of r.values.concat(r.minors)) { assert.ok(v * m.div >= m.lo - 1e-6 && v * m.div <= m.hi + 1e-6, tag + ' tick outside the range: ' + v); }
        for (const v of r.values) {
          const k = v / r.step; assert.ok(Math.abs(k - Math.round(k)) < 1e-9, tag + ' label ' + v + ' not a multiple of ' + r.step);
          assert.strictEqual(Number(v.toFixed(r.dec)), v, tag + ' label ' + v + ' has more decimals than ' + r.dec);
        }
        for (let i = 1; i < r.values.length; i++) assert.ok(Math.abs(r.values[i] - r.values[i - 1] - r.step) < 1e-9, tag + ' labels evenly spaced');
        const face = gpart(gk(gbox(e, [{ pid, form: 'dial' }]), pid + ':dial'), 'gface').innerHTML;
        const txt = Array.from(face.matchAll(/<text x="[^"]*" y="[^"]*" font-size="13"[^>]*>([^<]*)<\/text>/g), x => x[1]);
        assert.deepStrictEqual(txt, labels(r), tag + ' dial text is the label list');
        assert.strictEqual((face.match(/class="dt"/g) || []).length, r.values.length + r.minors.length, tag + ' one tick per label or minor');
      }
    }
    const usSpeed = await gOver({}, withChannels, OVF, { 'shadetree.units': 'us' });
    const sf = gpart(gk(gbox(usSpeed, [{ pid: '0D', form: 'dial' }]), '0D:dial'), 'gface').innerHTML;
    assert.deepStrictEqual(Array.from(sf.matchAll(/font-size="13"[^>]*>([^<]*)<\/text>/g), x => x[1]), ['0', '25', '50', '75', '100'], 'US speed dial prints 0 25 50 75 100');
    const needle = (v) => { const m = P.dialSvg(v, 0, 200, 5, [], 'x', 1).match(/class="dn" x1="110" y1="118" x2="([\d.-]+)" y2="([\d.-]+)"/); return [+m[1], +m[2]]; };
    assert.ok(Math.abs(needle(100)[0] - 110) < 1e-6, 'mid value points straight up on the unchanged scale');
    assert.ok(needle(0)[0] < 110 && needle(200)[0] > 110, 'low end left, high end right');
    const mins = nt(P, 0, 124.27, 5, 1); assert.deepStrictEqual(mins.minors.slice(0, 3), [6.25, 12.5, 18.75], 'three minors between majors');
  }

  {   // 19) trust fixes: one assessment for lamps, gauges, tiles and attention; missing, old and replayed data never look healthy or live
    const OVC = { pids: Object.assign({}, OVF.pids, { '05': mk('Coolant', { ok: [60, 105], out: [null, 112] }) }), mode06: {} };   // the shipped coolant range
    const real = (st) => Object.assign(st, { demo: false });
    const lampE = (e, id) => Array.from(e.parts().lampModel()).find(x => x.id === id);
    const byId = (e, root, id) => { let r = null; walk(e.el(root), n => { if (n.id === id) r = n; }); return r; };
    const codesHtml = (e) => byId(e, 'd_codes_mount', 'd_codes').innerHTML;
    // 1. lamps and gauges agree: LTFT -18.8 is watch (amber) on both, -25 out of range (red) on both
    const ag = await gOver({ '07': -18.8, '09': -25 }), ab = gbox(ag, [{ pid: '07', form: 'bar' }, { pid: '09', form: 'bar' }]);
    assert.ok(gk(ab, '07:bar').className.includes('watch') && lampE(ag, 'ltft1').on && lampE(ag, 'ltft1').cls === 'amb' && /RICH -18\.8 %: watch/.test(lampE(ag, 'ltft1').e), 'watch is an amber lamp: ' + lampE(ag, 'ltft1').e);
    assert.ok(gk(ab, '09:bar').className.includes('out') && lampE(ag, 'ltft2').cls === 'red' && /out of range/.test(lampE(ag, 'ltft2').e), 'out of range is red on both');
    assert.strictEqual(ag.parts().assess('07').s, 'watch');
    const nd = makeEnv([{ status: 'idle', demo: false, channels: {}, stats: {}, seq: 0, codes: { read: false, note: null } }], 'v0', OVF); await nd.tick();
    ['ltft1', 'ltft2', 'ect'].forEach(id => assert.ok(!lampE(nd, id).on && lampE(nd, id).e === 'not available', id + ': ' + lampE(nd, id).e));
    const inline = await gOver({}, st => { delete st.channels['08']; delete st.channels['09']; return st; });
    assert.strictEqual(lampE(inline, 'ltft2').e, 'not available', 'no bank 2 in the run: not available, never "within range"');
    const cold = await gOver({ '05': 41 }, null, OVC), cg = gk(gbox(cold, [{ pid: '05', form: 'dial' }]), '05:dial');
    assert.ok(cg.className.includes('watch') && lampE(cold, 'ect').cls === 'amb' && /cold 41 °C: watch/.test(lampE(cold, 'ect').e), 'cold coolant: ' + lampE(cold, 'ect').e);
    const hot = await gOver({ '05': 125 }, null, OVC);
    assert.ok(lampE(hot, 'ect').cls === 'red' && /hot 125 °C: out of range/.test(lampE(hot, 'ect').e), 'hot coolant: ' + lampE(hot, 'ect').e);
    // 6. the gauge says which window its words describe; units on digits; labels for status readings; lambda keeps 2 decimals
    const steady = await gOver({});
    assert.strictEqual(gpart(gk(gbox(steady, [{ pid: '05', form: 'dial' }]), '05:dial'), 'gnote').textContent, '10 s: normal');
    assert.strictEqual(gpart(gk(gbox(steady, [{ pid: '42', form: 'seven' }]), '42:seven'), 'gval').textContent, 'V', 'seven-segment digits keep their unit');
    const spk = await gOver({}, st => { if (st.seq === 30) st.channels['05'].samples[0][2] = 125; return st; }), sg = gk(gbox(spk, [{ pid: '05', form: 'dial' }]), '05:dial');
    assert.strictEqual(gpart(sg, 'gnote').textContent, 'now: out of range · 10 s: normal'); assert.ok(sg.className.includes('out'), 'the gauge shows 125, so it is coloured by it');
    assert.ok(spk.parts().assess('05').s === 'ok' && spk.parts().assess('05').now === 'out', 'the sustained state is still the 10 s one');
    const lam = await gOver({}, st => { st.channels['24'] = { name: 'o2_b1s1_lambda', unit: 'ratio', labels: null, samples: [[st.seq, st.now, 0.96]] };
      st.channels['03'] = { name: 'fuel_system_status', unit: null, labels: { '2': 'Closed loop' }, samples: [[st.seq, st.now, 2]] }; return st; });
    const lb = gbox(lam, [{ pid: '24', form: 'seven' }, { pid: '03', form: 'seven' }]);
    assert.ok(/aria-label="0.96"/.test(gpart(gk(lb, '24:seven'), 'gface').innerHTML), 'lambda 0.96 is not rounded to 1.0');
    assert.strictEqual(gpart(gk(lb, '03:seven'), 'gval').textContent, 'Closed loop', 'a status reading shows its label'); assert.ok(!/aria-label/.test(gpart(gk(lb, '03:seven'), 'gface').innerHTML), 'not a number');
    lam.docHandlers.click({ target: findQ(gk(lb, '24:seven'), '24') }); assert.ok(/now 0\.96/.test(flat(lam.el('helpPanel'))), 'help keeps 2 decimals: ' + flat(lam.el('helpPanel')));
    // 3. stopped, lost server or a dropped reading: values kept, no health claim, a banner says which
    const stp = await gOver({ '07': -18.8 }, st => (st.seq === 30 ? Object.assign(st, { status: 'stopped' }) : st));
    assert.ok(stp.parts().assess('07').s === 'stale' && !lampE(stp, 'ltft1').on && lampE(stp, 'ltft1').e === 'not current', 'stopped: ' + lampE(stp, 'ltft1').e);
    assert.strictEqual(gpart(gk(gbox(stp, [{ pid: '05', form: 'dial' }]), '05:dial'), 'gnote').textContent, 'not current');
    assert.ok(!stp.el('lostBanner').hidden && /Sampling stopped/.test(stp.el('lostBanner').textContent) && /last readings, not current/.test(stp.el('lostBanner').textContent));
    const ls = makeEnv(statesFor(5, base).map(real), 'v5', OVF); for (let k = 0; k < 5; k++) await ls.tick();
    assert.strictEqual(ls.el('h_live').textContent, 'LIVE', 'a live car sampling says LIVE'); assert.strictEqual(ls.el('lostBanner').hidden, true);
    ls.sandbox.fetch = () => Promise.reject(new Error('down')); await ls.tick();
    assert.strictEqual(ls.el('h_live').textContent, 'NO LINK'); assert.ok(!ls.el('lostBanner').hidden && /Lost contact/.test(ls.el('lostBanner').textContent));
    assert.ok(/Lost contact/.test(ls.el('h_alert').textContent), 'repeated inside the Handheld frame');
    assert.ok(ls.parts().assess('05').s === 'stale' && ls.parts().assess('05').v === 90, 'the last reading is kept but not current');
    const drop = await gOver({}, st => { if (st.seq > 3) st.channels['07'].samples = []; return st; });
    assert.ok(drop.parts().assess('07').s === 'stale' && drop.parts().assess('05').s === 'ok', 'one reading not seen for over 10 s is not current, the rest are');
    // 4. one source state: the demo says SIMULATED, playback REPLAY, idle NOT SAMPLING; the Sampling lamp is never green in playback
    const dmo = makeEnv(statesFor(3, base), 'v5', OVF); for (let k = 0; k < 3; k++) await dmo.tick();
    assert.ok(dmo.el('h_live').textContent === 'SIMULATED' && /SIMULATED/.test(dmo.el('chipLive').innerHTML) && !/LIVE/.test(dmo.el('chipLive').innerHTML), 'the demo never says LIVE');
    assert.ok(lampE(dmo, 'samp').on && /simulated/.test(lampE(dmo, 'samp').e));
    const rps = makeEnv(statesFor(3, base).map(st => Object.assign(real(st), { replay: { name: 'r.json', duration: 10, pos: 1.2, speed: 1, playing: false, ended: false, demo: true } })), 'v5', OVF);
    for (let k = 0; k < 3; k++) await rps.tick();
    assert.strictEqual(rps.el('h_live').textContent, 'REPLAY · PAUSED'); assert.ok(!lampE(rps, 'samp').on && /replay/.test(lampE(rps, 'samp').e), 'no lit sampling lamp in playback');
    assert.ok(/recorded simulation/.test(rps.el('replayBanner').textContent), rps.el('replayBanner').textContent);
    const idl = makeEnv([{ status: 'idle', demo: false, channels: {}, stats: {}, seq: 0, codes: { read: false, note: null } }], 'v5', OVF); await idl.tick();
    assert.strictEqual(idl.el('h_live').textContent, 'NOT SAMPLING');
    // 2. unanswered is not empty: no green zero, no "lamp off", no passed Mode 06
    const CLEAR = { read: true, note: null, mil: false, unanswered: [], stored: [], pending: [], permanent: [] };
    const cdE = async (codes, m06, view = 'v0', fn = base, store = NOGAUGES()) => {
      const e = makeEnv(statesFor(30, fn).map(st => Object.assign(real(st), { codes, mode06: m06 || { read: false, note: null } })), view, OVF, [], store);
      for (let k = 0; k < 32; k++) await e.tick(); return e;
    };
    const silent = await cdE({ read: false, note: 'the car did not answer the trouble-code requests', mil: null });
    assert.ok(/DID NOT ANSWER/.test(codesHtml(silent)) && silent.el('chipLamp').textContent === 'check engine: ?' && lampE(silent, 'mil').e === 'unknown');
    const PART = { read: true, note: null, mil: null, unanswered: ['pending', 'mil'], stored: [], pending: [], permanent: [] };
    const part1 = await cdE(PART);
    assert.ok(/NO ANSWER FOR PENDING CODES/.test(codesHtml(part1)), codesHtml(part1)); assert.strictEqual(lampE(part1, 'mil').e, 'no answer');
    assert.ok(/no answer: pending/.test(part1.el('chipCodes').textContent), part1.el('chipCodes').textContent);
    assert.strictEqual(part1.el('d_codes_mount').hidden, true, 'no codes: the Codes panel collapses (the summary bar says why)');
    const part1h = await cdE(PART, null, 'v5');
    assert.ok(!part1h.el('h_n').className.includes('zero') && part1h.el('h_miltxt').textContent === 'Check engine ?', 'Handheld: no green zero, lamp unknown');
    const m6 = await cdE(CLEAR, { read: true, note: null, mids: ['01'], results: [] }, 'v6');
    assert.ok(m6.el('m6_count').textContent === 'no results' && m6.el('m6_count').className === 'tag', 'no results is neutral, never "0 outside limits" in green');
    const m6n = await cdE(CLEAR, { read: false, note: 'the car did not answer Mode 06 (no supported monitors reported)', mids: [], results: [] }, 'v6');
    assert.ok(/did not answer Mode 06/.test(flat(m6n.el('m6'))) && m6n.el('m6_count').textContent === '');
    // 5. the summary bar: source, lamp, distinct codes, readings, one next action, in every scenario
    const sb = await cdE({ read: true, note: null, mil: true, unanswered: [], stored: [{ code: 'P0117', desc: 'd', hint: '' }], pending: [{ code: 'P0117', desc: 'd', hint: '' }, { code: 'P0175', desc: 'x', hint: '' }], permanent: [] });
    const sbh = sb.el('d_sum').innerHTML;
    ['Live car · sampling', 'Check engine ON', '2 codes', 'No flags in the 6 readings assessed', 'Next: review the codes below'].forEach(t => assert.ok(sbh.includes(t), t + ' in ' + sbh));
    assert.ok(sb.el('d_sum').className === 'sumbar bad' && sb.el('d_codes_mount').hidden === false, 'codes: the panel shows');
    assert.ok(/Trouble codes read at run start, not live/.test(flat(sb.el('d_codes_mount'))), 'the Codes panel says codes are not live');
    for (const c of [(await cdE({ read: true, note: null, mil: true, unanswered: [], stored: [{ code: 'P0117', desc: 'd', hint: '' }], pending: [], permanent: [] }, null, 'v5')).el('h_codes'), (await cdE(CLEAR, null, 'v5')).el('h_codes')]) assert.ok(/Read at run start, not live/.test(c.innerHTML), 'Handheld Codes says so too, with and without codes');
    assert.strictEqual(sb.el('o_note').textContent, 'No flags in the 6 readings assessed');
    const ok = await cdE(CLEAR);
    assert.ok(/No codes stored/.test(ok.el('d_sum').innerHTML) && /Check engine off/.test(ok.el('d_sum').innerHTML) && ok.el('d_sum').className === 'sumbar ok', ok.el('d_sum').innerHTML);
    const out = await cdE(CLEAR, null, 'v0', () => Object.assign(base(), { '07': -25 }), { 'shadetree.scenario': 'fuel' });
    assert.ok(/1 out of range/.test(out.el('d_sum').innerHTML) && /Next: look at LTFT bank 1 first/.test(out.el('d_sum').innerHTML), out.el('d_sum').innerHTML);
    const idleBar = makeEnv([{ status: 'idle', demo: false, channels: {}, stats: {}, seq: 0, codes: { read: false, note: null } }], 'v0', OVF); await idleBar.tick();
    assert.ok(/Next: press Start sampling, or load a replay/.test(idleBar.el('d_sum').innerHTML) && /Codes not read/.test(idleBar.el('d_sum').innerHTML), idleBar.el('d_sum').innerHTML);
    assert.ok(/id="d_sum"/.test(html.slice(html.indexOf('id="v0"'), html.indexOf('id="d_panel"'))), 'the bar sits above the gauges');
    // the Handheld shows the same summary bar (source, lamp, codes and unanswered lists, readings to watch, next action)
    const hsb = await cdE(Object.assign({}, PART, { unanswered: ['pending'], mil: false }), null, 'v5', () => Object.assign(base(), { '07': 14 }), { 'shadetree.scenario': 'fuel' });
    const hsh = hsb.el('h_sum').innerHTML;
    ['Live car · sampling', 'Check engine off', 'No answer for pending codes', '1 to watch', 'Next: keep an eye on LTFT bank 1 first'].forEach(t => assert.ok(hsh.includes(t), t + ' in ' + hsh));
    assert.ok(hsb.el('h_sum').className === 'sumbar warn' && /id="h_sum"/.test(html.slice(html.indexOf('class="hh-body"'), html.indexOf('id="h_livepane"'))), 'above both Handheld panes');
    // Guided test: an unmatched pattern is "not classified", never "no large error"; no citations to playbooks that are not built
    const guided = async (fi, fr) => {
      const e = makeEnv(statesFor(10, fi).concat(statesFor(45, fi, 10, 4), statesFor(60, fr, 55, 22)), 'v3');
      for (let k = 0; k < 10; k++) await e.tick(); e.handlers['go_idle:click']();
      for (let k = 0; k < 45; k++) await e.tick(); e.handlers['go_rev:click']();
      for (let k = 0; k < 45; k++) await e.tick(); return e.el('verdict').innerHTML;
    };
    const high = await guided(() => Object.assign(idle(), { '07': 25, '09': 25 }), () => Object.assign(rev(), { '07': 25, '09': 25 }));
    assert.ok(/Pattern not classified/.test(high) && !/No large/.test(high) && /bank 1 LTFT 25\.0 % idle, 25\.0 % at 2500 rpm/.test(high), high);
    const noRev = await guided(idle, idle);
    assert.ok(/Pattern not classified/.test(noRev) && /averaged 700 rpm/.test(noRev), 'both captures at idle: ' + noRev);
    // a new run (Stop then Start, a replay loaded or left) clears the captures: they belong to the old run
    const nr = makeEnv(statesFor(10, idle).concat(statesFor(45, idle, 10, 4), statesFor(5, idle).map(st => Object.assign(st, { run: 2 }))), 'v3');
    for (let k = 0; k < 10; k++) await nr.tick(); nr.handlers['go_idle:click']();
    for (let k = 0; k < 45; k++) await nr.tick();
    assert.ok(nr.el('st_idle').className === 'step done' && /Warm idle/.test(nr.el('results').innerHTML), 'captured in run 1');
    for (let k = 0; k < 5; k++) await nr.tick();
    assert.ok(/No captures yet/.test(nr.el('results').innerHTML) && nr.el('st_idle').className === 'step active' && nr.el('tx_idle').textContent === '', 'run 2 starts with no captures');
    assert.ok(!/ref:playbook/.test(html) && /\[general knowledge, unverified\]/.test(env.el('verdict').innerHTML), 'unbuilt playbook ids are gone');
  }

  console.log('page logic OK');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });

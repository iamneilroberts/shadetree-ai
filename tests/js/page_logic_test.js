// Runs the console page's own <script> against a fake DOM and scripted server states.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync(process.argv[2], 'utf8');
const js = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function makeNode(id, handlers) {
  const n = {
    id, style: {}, className: '', innerHTML: '', hidden: false, dataset: {}, disabled: false, type: '',
    clientWidth: 0, clientHeight: 0, offsetWidth: 0, offsetHeight: 0, children: [], attrs: {}, _t: '',
    classList: { toggle() {} },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    appendChild(c) { this.children = this.children.filter(x => x !== c); this.children.push(c); return c; },
    removeChild(c) { this.children = this.children.filter(x => x !== c); return c; },
    contains(t) { return t === this || this.children.some(c => c.contains(t)); },
    closest(sel) { return sel[0] === '.' && this.className.split(' ').includes(sel.slice(1)) ? this : null; },
    getBoundingClientRect() { return { left: 0, top: 0, bottom: 0, right: 0 }; },
    addEventListener(t, fn) { handlers[id + ':' + t] = fn; }, querySelector() { return null; }
  };
  Object.defineProperty(n, 'textContent', { get() { return this._t; }, set(v) { this._t = v; this.children = []; } });
  return n;
}

function makeEnv(states, viewId = 'v1', help = null) {
  const els = {}, handlers = {}, docHandlers = {}, posts = [];
  function el(id) { return els[id] || (els[id] = makeNode(id, handlers)); }
  let timer = null, i = 0, now = 0;
  const sandbox = {
    console, URLSearchParams, Promise, Math, Object, Array, Number, String, JSON, Date, parseInt, isFinite,
    document: { getElementById: el, querySelectorAll: () => [], querySelector: () => ({ id: viewId }),
                createElement: () => makeNode('new', handlers), addEventListener(t, fn) { docHandlers[t] = fn; } },
    window: { addEventListener() {}, devicePixelRatio: 1, innerWidth: 500, innerHeight: 800 },
    location: { search: '?t=abc', hash: '' }, history: { replaceState() {} },
    performance: { now: () => now },
    setInterval: (fn) => { timer = fn; }, encodeURIComponent,
    fetch: (url, opts) => {
      if (opts && opts.method === 'POST') { posts.push({ url, body: JSON.parse(opts.body) }); return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, path: '/x/runs/a-run.json' }) }); }
      if (/\/api\/help/.test(url)) return Promise.resolve(help ? { ok: true, json: () => Promise.resolve(help) } : { ok: false, json: () => Promise.resolve({}) });
      const st = states[Math.min(i++, states.length - 1)];
      return Promise.resolve({ ok: true, json: () => Promise.resolve(st) });
    }
  };
  vm.runInNewContext(js, sandbox);
  return {
    el, handlers, docHandlers, posts, sandbox,
    timer() { timer(); },
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

  // 3) retro layouts D (cabinet) and E (handheld): trouble codes reach the page, escaped, with honest empty states
  const withCodes = (n, codes, status = 'running') => statesFor(n, idle).map(st => Object.assign(st, { status, codes }));
  const CODES = { read: true, note: null, mil: true,
    stored: [{ code: 'P0117', desc: 'Engine coolant temperature circuit low input', hint: 'Reads colder than real', known: true },
             { code: 'P0172', desc: '<img src=x onerror=alert(1)>', hint: '', known: false }],
    pending: [{ code: 'P0175', desc: 'System too rich (bank 2)', hint: 'Seen once', known: true }], permanent: [] };
  const cab = makeEnv(withCodes(3, CODES), 'v4');
  for (let k = 0; k < 3; k++) await cab.tick();
  const rows = cab.el('a_codes').innerHTML;
  assert(/P0117/.test(rows) && /STORED/.test(rows) && /PENDING/.test(rows) && /P0175/.test(rows), 'cabinet lists stored and pending codes');
  assert(!/<img/.test(rows) && /&lt;img/.test(rows), 'adapter/ECU-derived text is escaped, never markup');
  assert.strictEqual(cab.el('a_lp_mil').className, 'lampbox lit', 'MIL lamp lit when the ECU commands it');
  const cabNone = makeEnv(withCodes(3, { read: true, note: null, stored: [], pending: [], permanent: [], mil: false }), 'v4');
  for (let k = 0; k < 3; k++) await cabNone.tick();
  assert(/NO CODES STORED/.test(cabNone.el('a_codes').innerHTML) && cabNone.el('a_lp_mil').className === 'lampbox', 'healthy car: explicit none, lamp off');
  const cabWait = makeEnv(withCodes(3, { read: false, note: null }, 'idle'), 'v4');
  for (let k = 0; k < 3; k++) await cabWait.tick();
  assert(/START SAMPLING TO READ CODES/.test(cabWait.el('a_codes').innerHTML) && !/NO CODES STORED/.test(cabWait.el('a_codes').innerHTML), 'unread codes never look like a clean bill');
  const cabNote = makeEnv(withCodes(3, { read: false, note: 'trouble codes not supported yet on SAE J1850 PWM protocol' }), 'v4');
  for (let k = 0; k < 3; k++) await cabNote.tick();
  assert(/NOT SUPPORTED YET/.test(cabNote.el('a_codes').innerHTML), 'unsupported bus is stated');
  const hh = makeEnv(withCodes(3, CODES), 'v5');
  for (let k = 0; k < 3; k++) await hh.tick();
  assert.strictEqual(hh.el('h_n').textContent, '3 CODES');
  assert(/P0117/.test(hh.el('h_codes').innerHTML) && /Reads colder than real/.test(hh.el('h_codes').innerHTML) && !/<img/.test(hh.el('h_codes').innerHTML), 'handheld cards');
  assert.strictEqual(hh.el('h_live').textContent, 'LIVE');
  assert(/Check engine \(MIL\)/.test(hh.el('h_status').innerHTML) && /Read-only/.test(hh.el('h_status').innerHTML), 'status pane');
  const hhWait = makeEnv(withCodes(3, { read: false, note: null }, 'idle'), 'v5');
  for (let k = 0; k < 3; k++) await hhWait.tick();
  assert.strictEqual(hhWait.el('h_n').textContent, '-- CODES'); assert.strictEqual(hhWait.el('h_live').textContent, 'IDLE');

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
  assert.strictEqual(hp.el('x_grid').children.filter(c => c.className === 'xt').length, 3, 'cards (0x04, 0x10, 0x99) are updated in place, not duplicated');
  hp.docHandlers.keydown({ key: 'Escape' });
  panel.offsetWidth = 360; q04.getBoundingClientRect = () => ({ left: 480, top: 100, bottom: 120, right: 500 });
  hp.docHandlers.click({ target: q04 });
  const left = parseFloat(panel.style.left);
  assert(left >= 12 && left <= 500 - 360 - 12, 'panel stays inside a 500 px viewport, got left=' + left);
  const bad = makeEnv(extraStates, 'v6', { pids: null, mode06: null });
  for (let k = 0; k < 5; k++) await bad.tick();
  bad.docHandlers.click({ target: findQ(bad.el('x_grid'), '04') });
  assert(/No bundled help/.test(flat(bad.el('helpPanel'))), 'a malformed help reply falls back to the generic popup, no crash');

  console.log('page logic OK');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });

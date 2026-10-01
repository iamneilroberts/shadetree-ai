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

function makeEnv(states, viewId = 'v0', help = null, runs = [], store = {}, page = {}) {   // page: { search, postReply(url, body) }
  const els = {}, handlers = {}, docHandlers = {}, posts = [];
  function el(id) { return els[id] || (els[id] = makeNode(id, handlers)); }
  let timer = null, i = 0, now = 0;
  const sandbox = {
    console, URLSearchParams, Promise, Math, Object, Array, Number, String, JSON, Date, parseInt, isFinite,
    document: { getElementById: el, querySelectorAll: () => [], querySelector: () => ({ id: viewId }),
                createElement: () => makeNode('new', handlers), addEventListener(t, fn) { docHandlers[t] = fn; } },
    window: { addEventListener() {}, devicePixelRatio: 1, innerWidth: 500, innerHeight: 800 },
    location: { search: page.search || '?t=abc', hash: '' }, history: { replaceState() {} },
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
      if (/\/api\/help/.test(url)) return Promise.resolve(help ? { ok: true, json: () => Promise.resolve(help) } : { ok: false, json: () => Promise.resolve({}) });
      const st = states[Math.min(i++, states.length - 1)];
      return Promise.resolve({ ok: true, json: () => Promise.resolve(st) });
    }
  };
  if (store !== null) sandbox.localStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
  vm.runInNewContext(js, sandbox);
  return {
    el, handlers, docHandlers, posts, sandbox, store,
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
  const env7 = makeEnv(a.concat(b), 'v0', { pids: { '42': { title: 'Battery', measures: 'x', use: [], typical: '', status: [], watch: { ok: [13.2, 14.8], out: [11.5, 15.5] } } }, mode06: {} });
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
  assert(/Check engine \(MIL\)/.test(hh.el('h_status').innerHTML) && /Sampling/.test(hh.el('h_status').innerHTML), 'status pane');
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
                        '42': mk('Battery', { ok: [13.2, 14.8], out: [11.5, 15.5] }, { watch_engine_off: { ok: [12.2, null], out: [11.5, null] } }),
                        '04': mk('Engine load'), '0B': mk('Manifold pressure') }, mode06: {} };
  const base = () => ({ '0C': 700, '05': 90, '06': 2, '07': 1, '08': 2, '09': 1, '0B': 36, '42': 14.2, '04': 28 });
  const ovEnv = async (fn, tweak) => {
    const e = makeEnv(statesFor(30, fn).map(st => (tweak ? tweak(st) : st)), 'v0', OVF);
    for (let k = 0; k < 32; k++) await e.tick();
    return e;
  };
  const tile = (e, key) => { let r = null; walk(e.el('o_tiles'), n => { if (n.getAttribute('data-key') === key) r = n; }); return r; };
  const part = (t, cls) => { let r = null; walk(t, n => { if (n.className === cls) r = n; }); return r.textContent; };
  const rowsOf = e => e.el('o_attn').children.map(c => c.getAttribute('data-key'));

  const okEnv = await ovEnv(base);
  assert.deepStrictEqual(['trims', 'ect', 'volts', 'load', 'map'].map(k => tile(okEnv, k).className), ['tile', 'tile', 'tile', 'tile neutral', 'tile neutral'], 'healthy: normal tiles, no-threshold tiles neutral');
  assert.strictEqual(okEnv.el('o_note').textContent, 'Nothing out of range');
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
  const noLoad = await ovEnv(() => { const b = base(); delete b['04']; return b; });
  assert.strictEqual(tile(noLoad, 'load').className, 'tile idle'); assert.strictEqual(part(tile(noLoad, 'load'), 'sub'), 'not reported');
  const stale = await ovEnv((s) => { const b = base(); if (s > 10) delete b['04']; return b; });
  assert(/^last seen \d+ s ago$/.test(part(tile(stale, 'load'), 'sub')), 'a rotating extra shows its age: ' + part(tile(stale, 'load'), 'sub'));
  const stoppedEnv = await ovEnv(base, st => Object.assign(st, { status: 'stopped' }));
  assert.strictEqual(part(tile(stoppedEnv, 'ect'), 'sub'), 'not sampling'); assert.strictEqual(stoppedEnv.el('o_note').textContent, 'Not sampling');
  assert.deepStrictEqual(rowsOf(stoppedEnv), []);
  const chipsEnv = await ovEnv(base, st => Object.assign(st, { codes: { read: true, note: null, mil: true, stored: [{ code: 'P0300' }], pending: [], permanent: [] } }));
  assert.strictEqual(chipsEnv.el('chipLamp').textContent, 'lamp on'); assert.strictEqual(chipsEnv.el('chipCodes').textContent, '1 stored');
  const chipsNone = await ovEnv(base, st => Object.assign(st, { codes: { read: false, note: null } }));
  assert.strictEqual(chipsNone.el('chipLamp').textContent, 'lamp ?'); assert.strictEqual(chipsNone.el('chipCodes').textContent, 'codes not read');
  const qTrim = findQ(wEnv.el('o_attn'), '06'); assert(qTrim, 'attention rows have a ? button');
  wEnv.docHandlers.click({ target: qTrim }); assert(/Short-term trim, bank 1/.test(flat(wEnv.el('helpPanel'))) && /now 13/.test(flat(wEnv.el('helpPanel'))), 'row help shows the catalog and the live value');

  // 7) Overview honesty: help ranges not loaded (and a retry), last-seen age, spike vs median, odd help entries
  const noHelp = makeEnv(statesFor(30, base), 'v0', null);
  for (let k = 0; k < 32; k++) await noHelp.tick();
  assert.strictEqual(noHelp.el('o_note').textContent, 'Health ranges not loaded, so nothing is checked');
  noHelp.setHelp(OVF); noHelp.advance(6000);
  for (let k = 0; k < 4; k++) await noHelp.tick();
  assert.strictEqual(noHelp.el('o_note').textContent, 'Nothing out of range', 'the page retries loading the ranges');
  const gone = await ovEnv((s) => { const b = base(); if (s > 3) delete b['04']; return b; });
  assert.strictEqual(tile(gone, 'load').className, 'tile neutral', 'an extra not seen for over 10 s keeps its last value');
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
  assert(/REPLAY . PAUSED/.test(ended.el('chipLive').innerHTML) && ended.el('chipLive').className === 'chip paused', 'a paused replay says so');
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
  const sk = makeEnv([], 'v0', OVF);
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
  const store = {};
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
  assert.strictEqual(big(noStore, 'ect'), '90', 'without storage it starts metric');
  await toggle(noStore); assert.strictEqual(big(noStore, 'ect'), '194', 'and still toggles');

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
  assert.deepStrictEqual(cells(sp, '0D'), ['Vehicle speed (mph)', '37', '0', '70', '31'], 'speed row converts every column: ' + cells(sp, '0D'));
  assert.deepStrictEqual(cells(sp, '05'), ['Coolant temp (°F)', '106', '68', '194', '158'], 'a main channel is a row too');
  assert.deepStrictEqual(cells(sp, '0B'), ['MAP (inHg)', '10.6', '8.9', '29.8', '11.8'], 'manifold pressure in inHg');
  assert.deepStrictEqual(cells(sp, '0C'), ['Engine speed (rpm)', '700', '650', '3200', '1500']);
  assert.deepStrictEqual(cells(sp, '06'), ['STFT bank 1 (%)', '-12.0', '—', '—', '—'], 'no stats from the server: dashes, not made-up numbers');
  assert.deepStrictEqual(cells(sp, '03'), ['Fuel system status', 'closed loop', '—', '—', '—'], 'a status reading shows its label and no statistics');
  assert(findQ(rrow(sp, '0D'), '0D'), 'every row keeps its ? help button');
  assert.strictEqual(sp.el('x_grid').children.filter(c => c.className === 'xr').length, 11, 'all 11 channels on one table, in pid order');
  assert.strictEqual(sp.el('x_grid').children[0].getAttribute('data-key'), '03');
  assert(/11 readings · stats over the whole run/.test(sp.el('x_count').textContent), sp.el('x_count').textContent);
  await toggle(sp);
  assert.deepStrictEqual(cells(sp, '0D'), ['Vehicle speed (km/h)', '60', '0', '112.7', '50'], 'metric after the toggle');
  const spl = makeEnv(speedStates(false), 'v6', OVF, [], {});
  for (let k = 0; k < 5; k++) await spl.tick();
  assert(/stats over this run so far/.test(spl.el('x_count').textContent), 'live says the stats are over the run so far');

  // Analyzer, Handheld and Guided test: labels and digits
  const an = await uEnv({ '05': 41 }, 'v4', {});
  assert(/aria-label="41"/.test(an.el('a_ect').innerHTML) && /aria-label="36"/.test(an.el('a_map').innerHTML));
  assert.strictEqual(an.el('a_ect_u').textContent, '°C'); assert.strictEqual(an.el('a_map_u').textContent, 'KPA');
  await toggle(an);
  assert(/aria-label="106"/.test(an.el('a_ect').innerHTML) && /aria-label="10.6"/.test(an.el('a_map').innerHTML), 'cabinet digits convert');
  assert.strictEqual(an.el('a_ect_u').textContent, '°F'); assert.strictEqual(an.el('a_map_u').textContent, 'INHG');
  const hh2 = await uEnv({ '05': 41 }, 'v5', { 'shadetree.units': 'us' });
  assert(/aria-label="106"/.test(hh2.el('h_ect').innerHTML) && /aria-label="10.6"/.test(hh2.el('h_map').innerHTML), 'handheld digits convert');
  assert.strictEqual(hh2.el('h_ect_u').textContent, '°F'); assert.strictEqual(hh2.el('h_map_u').textContent, 'INHG');
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

  console.log('page logic OK');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });

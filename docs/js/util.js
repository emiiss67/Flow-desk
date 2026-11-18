/* FlowDesk shared helpers */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
function h(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function dec(p) { const a = Math.abs(p); return a < 10 ? 5 : a < 200 ? 3 : 2; }
function fp(p, d) { if (p == null || isNaN(p)) return '–'; return Number(p).toLocaleString('en-US', { minimumFractionDigits: d ?? dec(p), maximumFractionDigits: d ?? dec(p) }); }
/* account currency (EUR by default); the API reports it with every money response */
const Cur = { code: 'EUR', sym: '€', set(c, s) { if (!c) return; this.code = c; this.sym = s || ({ EUR: '€', USD: '$', GBP: '£', JPY: '¥' }[c] || c + ' '); try { localStorage.setItem('fd_ccy', JSON.stringify([this.code, this.sym])); } catch { } } };
try { const c = JSON.parse(localStorage.getItem('fd_ccy') || 'null'); if (c) { Cur.code = c[0]; Cur.sym = c[1]; } } catch { }
/* ONE account-money formatter for the whole desk (currency from the API, EUR by default).
   dp: decimals (null = 2 below 100, 0 above); sign: show + for gains. */
function fmtMoney(v, { sign = false, dp = 2 } = {}) {
  if (v == null || isNaN(v)) return '–';
  v = Number(v); const d = dp == null ? (Math.abs(v) < 100 && v !== 0 ? 2 : 0) : dp;
  const s = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  return (v < 0 && s.replace(/[0.,]/g, '') !== '' ? '-' : '') + (sign && v > 0 && s.replace(/[0.,]/g, '') !== '' ? '+' : '') + Cur.sym + s;
}
function money(v, sign = true) { return fmtMoney(v, { sign, dp: null }); }
function money2(v) { return fmtMoney(v, { dp: 2 }); }
/* How much went into a trade (API `stake`): "Risk €9.70 (20%) · Size 0.02 lots · Notional €1,630 · 81x" */
function levTxt(l) { return l == null ? '' : (l >= 1 ? Math.round(l).toLocaleString('en-US') : Number(l).toFixed(2)) + 'x'; }
function stakeText(s) { if (!s) return ''; return `Risk ${money2(s.risk_eur)}${s.risk_pct != null ? ` (${+s.risk_pct}%)` : ''} · Size ${s.size_text} · Notional ${money(s.notional_eur, false)}${s.leverage != null ? ' · ' + levTxt(s.leverage) : ''}`; }
function stakeRow(s, { pnl = false } = {}) {
  if (!s) return '';
  const simple = Mode.simple();
  const seg = [`<span title="Amount lost if the initial stop is hit${s.equity_at_entry ? ', as % of the ' + money2(s.equity_at_entry) + ' balance at entry' : ''}">${simple ? 'Money at risk' : 'Risk'} <b class="num">${money2(s.risk_eur)}</b>${s.risk_pct != null ? ` <span class="num">(${+s.risk_pct}%${simple ? ' of balance' : ''})</span>` : ''}</span>`,
    `<span title="Position size (${s.qty} units of the instrument)">Size <b class="num">${esc(s.size_text)}</b></span>`,
    `<span title="Notional value: size × price × point value × FX">${simple ? 'Trade size (with leverage)' : 'Notional'} <b class="num">${money(s.notional_eur, false)}</b></span>`];
  if (s.leverage != null) seg.push(`<span title="Notional ÷ balance at entry (paper leverage used)"><b class="num">${levTxt(s.leverage)}</b>${simple ? ' leverage' : ''}</span>`);
  if (pnl && s.pnl_pct_of_risk != null) seg.push(`<span title="P&amp;L as % of the amount risked">${simple ? 'Result' : 'P&amp;L'} <b class="num ${pnlClass(s.pnl_pct_of_risk)}">${s.pnl_pct_of_risk > 0 ? '+' : ''}${+s.pnl_pct_of_risk}%</b> of ${simple ? 'the money at risk' : 'risk'}</span>`);
  return `<div class="stake">${seg.join('<i>·</i>')}</div>`;
}
function pnlClass(v) { return v > 0 ? 'g' : v < 0 ? 'r' : 'm'; }
function ago(ts) {
  const s = Date.now() / 1000 - ts; if (s < 60) return 'just now'; if (s < 3600) return Math.round(s / 60) + 'm ago';
  if (s < 86400) return Math.round(s / 3600) + 'h ago'; return Math.round(s / 86400) + 'd ago';
}
function inTime(ts) { const m = (ts - Date.now() / 1000) / 60; if (m < 0) { const a = -m; return a < 90 ? Math.round(a) + 'm ago' : a < 2880 ? Math.round(a / 60) + 'h ago' : Math.round(a / 1440) + 'd ago'; } if (m < 120) return 'in ' + Math.round(m) + 'm'; if (m < 2880) return 'in ' + (m / 60).toFixed(1) + 'h'; return 'in ' + Math.round(m / 1440) + 'd'; }
function hm(ts) { return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
function dmy(ts) { return new Date(ts * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' }); }
const store = {
  get(k, d) { try { const v = localStorage.getItem('fd_' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('fd_' + k, JSON.stringify(v)); } catch { } },
  del(k) { try { localStorage.removeItem('fd_' + k); } catch { } },
};
function toast(msg, ms = 2600) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(t._t); t._t = setTimeout(() => t.hidden = true, ms); }
function rng(seed) { let s = seed >>> 0 || 1; return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296; }
function hash(str) { let x = 2166136261; for (const c of str) { x ^= c.charCodeAt(0); x = Math.imul(x, 16777619); } return x >>> 0; }

/* ---------- colour themes (CSS variables + values for canvas/chart code) ---------- */
const Theme = {
  PALETTES: {
    neon: { name: 'Neon', g: '#00FF66', r: '#EF4444', c: '#00D4FF', panel: '#101116', a: 0.42, glow: 1 },
    gold: { name: 'Gold', g: '#F5C451', r: '#E5484D', c: '#FFE6A8', panel: '#15110a', a: 0.45, glow: 0.9 },
    ice: { name: 'Ice blue', g: '#5CE1FF', r: '#FF5C7A', c: '#A9C7FF', panel: '#0c1219', a: 0.42, glow: 1 },
    purple: { name: 'Purple', g: '#B57BFF', r: '#FF4D8D', c: '#7AA2FF', panel: '#130f1c', a: 0.44, glow: 1.1 },
    mono: { name: 'Monochrome', g: '#F2F2F2', r: '#8C8C8C', c: '#CFCFCF', panel: '#111111', a: 0.5, glow: 0.35 },
    matrix: { name: 'Matrix', g: '#39FF14', r: '#FF3B30', c: '#00FF9C', panel: '#04100a', a: 0.48, glow: 1.3 },
  },
  /* full themes: palette + matching background scenes (+ light/dark mode) */
  THEMES: {
    tradefortis: { name: 'TradeFortis', sub: 'Dark · silver, statue in view', g: '#22C55E', r: '#EF4444', c: '#3B82F6', panel: '#0a0a0b', a: 0.16, glow: 0.35, tf: true, scenes: ['tfbust', 'tfeye', 'tfsamurai', 'tfburst', 'tfswirl'] },
    neon: { name: 'Neon Augustus', sub: 'Dark · green flow', g: '#00FF66', r: '#EF4444', c: '#00D4FF', panel: '#101116', a: 0.42, glow: 1, scenes: ['augustus', 'antinoos', 'severus'] },
    marble: { name: 'White Marble', sub: 'Light · gallery', light: true, g: '#0E9F5A', r: '#D6333F', c: '#2563EB', panel: '#FFFFFF', a: 0.66, glow: 0.35, scenes: ['marblewoman', 'marbleherodotos', 'marblewoman'] },
    gold: { name: 'Gold & Bronze', sub: 'Dark · imperial gold', g: '#F5C451', r: '#E5484D', c: '#FFD98A', panel: '#15110a', a: 0.46, glow: 0.9, scenes: ['antoninus', 'herodotos', 'warrior'] },
    crimson: { name: 'Crimson', sub: 'Dark · blood red', g: '#34D399', r: '#FF2E4D', c: '#FF6B81', panel: '#16090c', a: 0.46, glow: 1.05, scenes: ['verus', 'severus', 'warrior'] },
    ocean: { name: 'Ocean', sub: 'Dark · deep blue', g: '#2EE6C5', r: '#FF5C7A', c: '#4FA8FF', panel: '#08111c', a: 0.44, glow: 1, scenes: ['ocean', 'severus', 'warrior'] },
    emerald: { name: 'Emerald', sub: 'Dark · bronze patina', g: '#2CF59B', r: '#F0525F', c: '#9BE15D', panel: '#06130d', a: 0.46, glow: 1.1, scenes: ['emerald', 'herodotos', 'antinoos'] },
    luxury: { name: 'Luxury', sub: 'Dark · black & gold', g: '#E8C15A', r: '#E5484D', c: '#F6E3B0', panel: '#0c0a07', a: 0.52, glow: 0.8, scenes: ['luxskyline', 'luxchandelier', 'luxharbor'] },
    motivation: { name: 'Motivation', sub: 'Dark · sunrise energy', g: '#22E58A', r: '#FF3D57', c: '#FFB020', panel: '#120c0a', a: 0.46, glow: 1.1, scenes: ['motsummit', 'motmatterhorn', 'mottrack'] },
  },
  cur: null,
  rgb(hex) { const h = hex.replace('#', ''); const n = parseInt(h.length === 3 ? h.split('').map(x => x + x).join('') : h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255].join(','); },
  load() {
    // TradeFortis is the default look; switch everyone to it once (other themes stay selectable in Settings)
    if (!store.get('tfDefault', false)) { store.set('tfDefault', true); const { name, sub, ...v } = this.THEMES.tradefortis; store.set('theme', Object.assign({ light: false }, v, { theme: 'tradefortis', palette: 'tradefortis' })); store.set('bg', 'auto'); }
    const t = store.get('theme', null); this.cur = Object.assign({ theme: 'tradefortis' }, this.THEMES.tradefortis, t || {}); delete this.cur.name; return this.cur; },
  save(t) { this.cur = Object.assign({}, this.cur, t); store.set('theme', this.cur); this.apply(); },
  /* pick a whole theme: palette + background scenes + light/dark; custom colours can still override afterwards */
  setTheme(id) { const th = this.THEMES[id]; if (!th) return; const { name, sub, ...vals } = th; this.cur = Object.assign({ light: false }, vals, { theme: id, palette: id }); store.set('theme', this.cur); store.set('bg', 'auto'); this.apply(); },
  get theme() { return this.THEMES[(this.cur || this.load()).theme] || this.THEMES.tradefortis; },
  get light() { return !!(this.cur || this.load()).light; },
  apply() {
    const t = this.cur || this.load(); const s = document.documentElement.style;
    s.setProperty('--g-rgb', this.rgb(t.g)); s.setProperty('--r-rgb', this.rgb(t.r)); s.setProperty('--c-rgb', this.rgb(t.c));
    s.setProperty('--panel-rgb', this.rgb(t.panel)); s.setProperty('--panel-a', t.a); s.setProperty('--gk', t.glow);
    document.documentElement.classList.toggle('light', !!t.light);
    document.documentElement.classList.toggle('tf', t.theme === 'tradefortis');
    const mt = document.querySelector('meta[name=theme-color]'); if (mt) mt.content = t.light ? '#eceae6' : '#050607';
    // re-tint the baked-in green eye glow of the original two background photos to match the palette
    const hue = hx => { const [r, g, b] = this.rgb(hx).split(',').map(n => n / 255); const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn; if (!d) return null;
      let h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; return (h * 60 + 360) % 360; };
    const hg = hue(t.g); s.setProperty('--bg-filter', hg == null ? 'saturate(0)' : `hue-rotate(${Math.round(hg - 144)}deg)`);
  },
  get g() { return (this.cur || this.load()).g; }, get r() { return (this.cur || this.load()).r; }, get c() { return (this.cur || this.load()).c; },
  get G() { return this.rgb(this.g); }, get R() { return this.rgb(this.r); }, get C() { return this.rgb(this.c); },
  get glow() { return +(this.cur || this.load()).glow; },
};
Theme.load(); Theme.apply();

/* ---- friendly market names: one map from the instruments module (docs/names.json = /api/names) ---- */
const Names = {
  map: (() => { try { return JSON.parse(localStorage.getItem('fd_names') || '{}'); } catch { return {}; } })(),
  async load() {
    try { const r = await fetch('names.json', { cache: 'no-cache' }); if (r.ok) { this.map = await r.json(); localStorage.setItem('fd_names', JSON.stringify(this.map)); } } catch { }
  },
};
function nm(sym) {
  const s = String(sym || '').trim(), u = s.toUpperCase(); const x = Names.map[u]; if (x) return x.name;
  let m = u.match(/^([A-Z]{3})([A-Z]{3})=X$/); if (m) return m[1] + '/' + m[2];
  return u.replace(/=F$/, '').replace(/^\^/, '').replace(/-USD$/, '') || s;
}
function nmIcon(sym) { const x = Names.map[String(sym || '').toUpperCase()]; return x ? x.icon : ''; }
function nmH(sym) { const i = nmIcon(sym); return `${i ? `<span class="mk-ic" aria-hidden="true">${i}</span>` : ''}${esc(nm(sym))}`; }
/* replace raw tickers inside free text (stored reasons / learned rules) with friendly names */
function deTicker(t) { return String(t ?? '').replace(/\^?[A-Z0-9]{1,10}(=X|=F|-USD)|\^[A-Z0-9]{2,10}/g, m => nm(m)); }

/* ---- display mode: Simple (plain English, default) or Pro (full trading terms) ---- */
const Mode = {
  get() { try { return localStorage.getItem('fd_mode') || 'simple'; } catch { return 'simple'; } },
  set(m) { try { localStorage.setItem('fd_mode', m); } catch { } this.apply(); },
  simple() { return this.get() !== 'pro'; },
  apply() { document.documentElement.classList.toggle('simple', this.simple()); },
};
Mode.apply();
const smp = (simple, pro) => Mode.simple() ? simple : pro;
function tip(text) { return `<button type="button" class="tip" aria-label="${esc(text)}" data-tip="${esc(text)}">i</button>`; }
const TIPS = {
  stop: 'Stop loss: the price where the bot closes the trade to cap the loss.',
  tp: 'Take profit: the price where the bot locks in the gain (half at the first target, the rest at the second).',
  risk: 'The most this trade can lose if the stop loss is hit.',
  notional: 'The full value of the position. Leverage lets a small balance control a bigger trade, which makes wins and losses bigger.',
  entry: 'The price the trade was opened at.',
};
function sideWord(s) { return Mode.simple() ? (s === 'LONG' ? 'Buy' : s === 'SHORT' ? 'Sell' : s === 'NO TRADE' ? 'No trade' : s) : s; }
/* plain-English "why this trade" from the strategy tags */
function whyText(tags, side) {
  const up = side !== 'SHORT'; const T = new Set((tags || []).map(String));
  const P = [];
  const add = (k, s) => { if ([].concat(k).some(x => T.has(x))) P.push(s); };
  add('BOS', up ? 'price broke above a recent high' : 'price broke below a recent low');
  add('CHoCH', up ? 'the short-term trend just turned up' : 'the short-term trend just turned down');
  add('Liquidity sweep', up ? 'price dipped under a recent low and bounced back' : 'price poked above a recent high and fell back');
  add('Delta +', 'buyers were stronger'); add('Delta -', 'sellers were stronger');
  add('Pressure surge', up ? 'there was a burst of buying' : 'there was a burst of selling');
  add(['Absorption', 'HVN Absorption', 'Key Level Absorption Reversal'], up ? 'big orders soaked up the selling' : 'big orders soaked up the buying');
  add('Order block', 'price came back to a zone where big orders were placed before');
  add('FVG', 'price returned to a gap it left earlier');
  add('OTE', 'price pulled back to a good-value entry');
  add('Discount', 'price is in the cheap part of its recent range'); add('Premium', 'price is in the expensive part of its recent range');
  add('HTF bias', 'the bigger trend points the same way');
  add(['Volume node', 'Round number'], 'it is near a price level traders watch');
  add('Structure', 'the price pattern supports it');
  if (!P.length) return '';
  const top = P.slice(0, 3); let s = top.length > 1 ? top.slice(0, -1).join(', ') + ' and ' + top[top.length - 1] : top[0];
  if (T.has('Killzone')) s += ', during a busy trading session';
  return s.charAt(0).toUpperCase() + s.slice(1) + '.';
}
function whyH(tags, side, setup) {
  const t = whyText([...(tags || []), ...(setup ? [setup] : [])], side); if (!t) return '';
  return `<details class="why"><summary>Why this trade</summary><div>${esc(t)}</div></details>`;
}

document.addEventListener('click', e => {
  const t = e.target.closest('.tip');
  $$('.tip.on').forEach(x => { if (x !== t) x.classList.remove('on'); });
  if (t) { e.preventDefault(); e.stopPropagation(); t.classList.toggle('on'); }
}, true);

/* ---- motivational line on the dashboard (per theme; on by default in Simple mode, off in Pro) ---- */
const Quotes = {
  on() { const v = store.get('quotes', null); return v == null ? Mode.simple() : !!v; },
  set(v) { store.set('quotes', !!v); },
  LIST: {
    luxury: ['Quiet discipline builds loud results.', 'Protect the downside and the upside takes care of itself.', 'Patience is the most expensive skill in the room.', 'Small, careful steps compound into something big.'],
    motivation: ['One good habit a day beats one lucky trade.', 'The climb is the training. Keep going.', 'Show up, follow the plan, let the results come.', 'Losses are lessons. Review, adjust, go again.'],
    _: ['Follow the plan. Size small. Stay consistent.', 'No trade is also a position.', 'Every loss is capped. Every day is a fresh start.'],
  },
  today() { const th = Theme.cur?.theme; const l = this.LIST[th] || this.LIST._; const d = Math.floor(Date.now() / 86400000); return l[d % l.length]; },
};

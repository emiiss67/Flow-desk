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
    neon: { name: 'Neon Augustus', sub: 'Dark · green flow', g: '#00FF66', r: '#EF4444', c: '#00D4FF', panel: '#101116', a: 0.42, glow: 1, scenes: ['augustus', 'antinoos', 'severus'] },
    marble: { name: 'White Marble', sub: 'Light · gallery', light: true, g: '#0E9F5A', r: '#D6333F', c: '#2563EB', panel: '#FFFFFF', a: 0.66, glow: 0.35, scenes: ['marblewoman', 'marbleherodotos', 'marblewoman'] },
    gold: { name: 'Gold & Bronze', sub: 'Dark · imperial gold', g: '#F5C451', r: '#E5484D', c: '#FFD98A', panel: '#15110a', a: 0.46, glow: 0.9, scenes: ['antoninus', 'herodotos', 'warrior'] },
    crimson: { name: 'Crimson', sub: 'Dark · blood red', g: '#34D399', r: '#FF2E4D', c: '#FF6B81', panel: '#16090c', a: 0.46, glow: 1.05, scenes: ['verus', 'severus', 'warrior'] },
    ocean: { name: 'Ocean', sub: 'Dark · deep blue', g: '#2EE6C5', r: '#FF5C7A', c: '#4FA8FF', panel: '#08111c', a: 0.44, glow: 1, scenes: ['ocean', 'severus', 'warrior'] },
    emerald: { name: 'Emerald', sub: 'Dark · bronze patina', g: '#2CF59B', r: '#F0525F', c: '#9BE15D', panel: '#06130d', a: 0.46, glow: 1.1, scenes: ['emerald', 'herodotos', 'antinoos'] },
  },
  cur: null,
  rgb(hex) { const h = hex.replace('#', ''); const n = parseInt(h.length === 3 ? h.split('').map(x => x + x).join('') : h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255].join(','); },
  load() { const t = store.get('theme', null); this.cur = Object.assign({ theme: 'neon' }, this.THEMES.neon, t || {}); delete this.cur.name; return this.cur; },
  save(t) { this.cur = Object.assign({}, this.cur, t); store.set('theme', this.cur); this.apply(); },
  /* pick a whole theme: palette + background scenes + light/dark; custom colours can still override afterwards */
  setTheme(id) { const th = this.THEMES[id]; if (!th) return; const { name, sub, ...vals } = th; this.cur = Object.assign({ light: false }, vals, { theme: id, palette: id }); store.set('theme', this.cur); store.set('bg', 'auto'); this.apply(); },
  get theme() { return this.THEMES[(this.cur || this.load()).theme] || this.THEMES.neon; },
  get light() { return !!(this.cur || this.load()).light; },
  apply() {
    const t = this.cur || this.load(); const s = document.documentElement.style;
    s.setProperty('--g-rgb', this.rgb(t.g)); s.setProperty('--r-rgb', this.rgb(t.r)); s.setProperty('--c-rgb', this.rgb(t.c));
    s.setProperty('--panel-rgb', this.rgb(t.panel)); s.setProperty('--panel-a', t.a); s.setProperty('--gk', t.glow);
    document.documentElement.classList.toggle('light', !!t.light);
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

/* FlowDesk shared helpers */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
function h(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function dec(p) { const a = Math.abs(p); return a < 10 ? 5 : a < 200 ? 3 : 2; }
function fp(p, d) { if (p == null || isNaN(p)) return '–'; return Number(p).toLocaleString('en-US', { minimumFractionDigits: d ?? dec(p), maximumFractionDigits: d ?? dec(p) }); }
function money(v, sign = true) {
  if (v == null || isNaN(v)) return '–';
  const dg = Math.abs(v) < 100 && v !== 0 ? 2 : 0; const s = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: dg, maximumFractionDigits: dg });
  return (v < 0 ? '-' : sign && v > 0 ? '+' : '') + '$' + s;
}
function money2(v) { if (v == null || isNaN(v)) return '–'; return (v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
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
  cur: null,
  rgb(hex) { const h = hex.replace('#', ''); const n = parseInt(h.length === 3 ? h.split('').map(x => x + x).join('') : h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255].join(','); },
  load() { const t = store.get('theme', null); this.cur = Object.assign({}, this.PALETTES.neon, t || {}); return this.cur; },
  save(t) { this.cur = Object.assign({}, this.cur, t); store.set('theme', this.cur); this.apply(); },
  apply() {
    const t = this.cur || this.load(); const s = document.documentElement.style;
    s.setProperty('--g-rgb', this.rgb(t.g)); s.setProperty('--r-rgb', this.rgb(t.r)); s.setProperty('--c-rgb', this.rgb(t.c));
    s.setProperty('--panel-rgb', this.rgb(t.panel)); s.setProperty('--panel-a', t.a); s.setProperty('--gk', t.glow);
    // re-tint the baked-in green eye glow of the background photo to match the palette
    const hue = hx => { const [r, g, b] = this.rgb(hx).split(',').map(n => n / 255); const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn; if (!d) return null;
      let h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; return (h * 60 + 360) % 360; };
    const hg = hue(t.g); s.setProperty('--bg-filter', hg == null ? 'saturate(0)' : `hue-rotate(${Math.round(hg - 144)}deg)`);
  },
  get g() { return (this.cur || this.load()).g; }, get r() { return (this.cur || this.load()).r; }, get c() { return (this.cur || this.load()).c; },
  get G() { return this.rgb(this.g); }, get R() { return this.rgb(this.r); }, get C() { return this.rgb(this.c); },
  get glow() { return +(this.cur || this.load()).glow; },
};
Theme.load(); Theme.apply();

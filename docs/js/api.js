/* API connection: reads #api=...&key=... from the URL, keeps it in localStorage, falls back to DEMO data. */
/* Saved credentials live in localStorage + an IndexedDB copy (some iOS builds drop one of them), and in the URL
   fragment (never sent to a server). The tunnel address can change when the server restarts: the server publishes
   the current address (never the key) in endpoint.json, so the desk follows it with the key it already has. */
const IDB = {
  open() { return new Promise((res, rej) => { try { const r = indexedDB.open('flowdesk', 1); r.onupgradeneeded = () => r.result.createObjectStore('kv'); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); } catch (e) { rej(e); } }); },
  async get(k) { try { const db = await this.open(); return await new Promise(res => { const q = db.transaction('kv').objectStore('kv').get(k); q.onsuccess = () => res(q.result ?? null); q.onerror = () => res(null); }); } catch { return null; } },
  async set(k, v) { try { const db = await this.open(); await new Promise(res => { const t = db.transaction('kv', 'readwrite'); t.objectStore('kv').put(v, k); t.oncomplete = t.onerror = () => res(); }); } catch { } },
  async del(k) { try { const db = await this.open(); await new Promise(res => { const t = db.transaction('kv', 'readwrite'); t.objectStore('kv').delete(k); t.oncomplete = t.onerror = () => res(); }); } catch { } },
};
const ENDPOINTS = ['endpoint.json', 'https://raw.githubusercontent.com/emiiss67/Flow-desk/main/docs/endpoint.json'];
const API = {
  base: null, key: null, demo: true, lastError: null, alt: [],
  async init() {
    const hp = new URLSearchParams(location.hash.replace(/^#/, ''));
    if (hp.get('demo') === '1') { this.forget(); store.set('demoChosen', true); }
    let api = store.get('api', null), key = store.get('key', null);
    if (!(api && key)) { const c = await IDB.get('creds'); if (c && c.api && c.key) { api = c.api; key = c.key; } }   // localStorage lost: IndexedDB copy
    const ha = hp.get('api'), hk = hp.get('key');
    if (ha && hk) {
      const h = ha.replace(/\/$/, '');
      // a link in the URL wins when it carries a different key (a fresh paste / new /desk link); with the same key it is
      // just the address the home-screen icon was saved with - keep the newer saved address and try the old one only as a fallback
      if (!key || hk !== key || !api) { api = h; key = hk; } else if (h !== api) this.alt.push(h);
    }
    this.base = api; this.key = key; this.demo = !(api && key);
    if (!this.demo) { this.persist(); this.follow(); }
    this.syncHash();
    try { navigator.storage?.persist?.(); } catch { }
  },
  persist() { store.set('api', this.base); store.set('key', this.key); IDB.set('creds', { api: this.base, key: this.key, ts: Date.now() }); },
  forget() { store.del('api'); store.del('key'); IDB.del('creds'); },
  /* iOS "Add to Home Screen" saves the current URL, and the home-screen app has its own storage: keep the
     credentials in the URL fragment (never sent to any server) so the installed icon opens already connected. */
  hash() { return this.demo ? '' : '#api=' + encodeURIComponent(this.base) + '&key=' + encodeURIComponent(this.key); },
  syncHash() { if (!this.demo && location.hash !== this.hash()) history.replaceState(null, '', location.pathname + location.search + this.hash()); },
  standalone() { return navigator.standalone === true || matchMedia('(display-mode: standalone)').matches; },
  /* read the server-published current tunnel address (URL only) */
  async published() {
    for (const u of ENDPOINTS) {
      try { const r = await fetch(u + (u.includes('?') ? '&' : '?') + 't=' + Date.now(), { cache: 'no-store' }); if (!r.ok) continue;
        const j = await r.json(); const a = String(j.api || '').replace(/\/$/, ''); if (/^https:\/\/[a-z0-9.-]+(:\d+)?$/i.test(a) || /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/i.test(a)) return a; } catch { }
    }
    return null;
  },
  /* tunnel moved? switch to the published (or fallback) address if it accepts the saved key */
  async rediscover() {
    if (this._redisc) return this._redisc;
    this._redisc = (async () => {
      const cands = [...new Set([await this.published(), ...this.alt].filter(a => a && a !== this.base))];
      for (const a of cands) if (!(await this.verify(a, this.key))) { this.base = a; this.persist(); this.syncHash(); return true; }
      return false;
    })();
    try { return await this._redisc; } finally { setTimeout(() => { this._redisc = null; }, 5000); }
  },
  follow() { this.published().then(a => { if (a && a !== this.base) this.rediscover(); }).catch(() => { }); },
  /* accepts the whole Telegram message, a desk URL, or "api=...&key=..." */
  parseLink(text) {
    const t = String(text || '').trim();
    const a = t.match(/[#&?]?api=([^&\s#]+)/), k = t.match(/[#&?]?key=([^&\s#]+)/);
    if (!a || !k) return null;
    let api; try { api = decodeURIComponent(a[1]).replace(/\/$/, ''); } catch { return null; }
    if (!/^https:\/\/[a-z0-9.-]+(:\d+)?$/i.test(api) && !/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/i.test(api)) return null;
    return { api, key: decodeURIComponent(k[1]) };
  },
  async verify(api, key) {
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 15000);
    try {
      const r = await fetch(api + '/api/dashboard', { headers: { 'X-Desk-Key': key }, signal: ctl.signal });
      if (r.status === 401) return 'The desk key was rejected. Send /desk in Telegram for a fresh link.';
      if (!r.ok) return 'The API answered HTTP ' + r.status + '.';
      return null;
    } catch (e) { return 'Could not reach the API right now (server restarting?). The desk will reconnect by itself.'; }
    finally { clearTimeout(t); }
  },
  save(api, key) { store.del('demoChosen'); this.base = api; this.key = key; this.demo = false; this.persist(); this.syncHash(); },
  disconnect() { this.forget(); this.base = this.key = null; this.demo = true; history.replaceState(null, '', location.pathname + location.search); },
  async get(path, params = {}, retried = false) {
    if (this.demo) { Cur.set('EUR', '€'); return DEMO.get(path, params); }
    const u = new URL(this.base + path);
    Object.entries(params).forEach(([k, v]) => v != null && v !== '' && u.searchParams.set(k, v));
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 30000);
    let r;
    try {
      r = await fetch(u, { headers: { 'X-Desk-Key': this.key }, signal: ctl.signal });
    } catch (e) {
      clearTimeout(t);
      // tunnel address changed? follow the published endpoint with the saved key and retry once
      if (!retried && await this.rediscover()) return this.get(path, params, true);
      this.lastError = e.name === 'AbortError' ? 'API timed out' : 'API unreachable - the server may be restarting; retrying automatically';
      App.setConn(false, this.lastError);
      throw new Error(this.lastError);
    }
    clearTimeout(t);
    if (r.status === 401) { Unlock.show('This desk key was rejected. Send /desk in Telegram and paste the new link.'); throw new Error('Desk key rejected - get a fresh link with /desk in Telegram'); }
    if (r.status === 530 || r.status === 502 || r.status === 1033) {     // cloudflare: tunnel gone
      if (!retried && await this.rediscover()) return this.get(path, params, true);
    }
    if (!r.ok) { let d = ''; try { d = (await r.json()).detail } catch { } this.lastError = d || ('HTTP ' + r.status); App.setConn(false, this.lastError); throw new Error(this.lastError); }
    this.lastError = null; App.setConn(true);
    const j = await r.json(); if (j && j.currency) Cur.set(j.currency, j.currency_symbol); return j;
  },
};

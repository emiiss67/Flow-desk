/* API connection: reads #api=...&key=... from the URL, keeps it in localStorage, falls back to DEMO data. */
const API = {
  base: null, key: null, demo: true, lastError: null,
  init() {
    const hp = new URLSearchParams(location.hash.replace(/^#/, ''));
    if (hp.get('api') && hp.get('key')) { store.set('api', hp.get('api').replace(/\/$/, '')); store.set('key', hp.get('key')); }
    if (hp.get('demo') === '1') { store.del('api'); store.del('key'); store.set('demoChosen', true); }
    this.base = store.get('api', null); this.key = store.get('key', null);
    this.demo = !(this.base && this.key);
    this.syncHash();
  },
  /* iOS "Add to Home Screen" saves the current URL, and the home-screen app has its own storage: keep the
     credentials in the URL fragment (never sent to any server) so the installed icon opens already connected. */
  hash() { return this.demo ? '' : '#api=' + encodeURIComponent(this.base) + '&key=' + encodeURIComponent(this.key); },
  syncHash() { if (!this.demo && location.hash !== this.hash()) history.replaceState(null, '', location.pathname + location.search + this.hash()); },
  standalone() { return navigator.standalone === true || matchMedia('(display-mode: standalone)').matches; },
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
    } catch (e) { return 'Could not reach the API (the tunnel may have restarted). Send /desk in Telegram for the current link.'; }
    finally { clearTimeout(t); }
  },
  save(api, key) { store.set('api', api); store.set('key', key); store.del('demoChosen'); this.base = api; this.key = key; this.demo = false; this.syncHash(); },
  disconnect() { store.del('api'); store.del('key'); this.base = this.key = null; this.demo = true; history.replaceState(null, '', location.pathname + location.search); },
  async get(path, params = {}) {
    if (this.demo) return DEMO.get(path, params);
    const u = new URL(this.base + path);
    Object.entries(params).forEach(([k, v]) => v != null && v !== '' && u.searchParams.set(k, v));
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 30000);
    try {
      const r = await fetch(u, { headers: { 'X-Desk-Key': this.key }, signal: ctl.signal });
      if (r.status === 401) { Unlock.show('This desk key was rejected. Send /desk in Telegram and paste the new link.'); throw new Error('Desk key rejected - get a fresh link with /desk in Telegram'); }
      if (!r.ok) { let d = ''; try { d = (await r.json()).detail } catch { } throw new Error(d || ('HTTP ' + r.status)); }
      this.lastError = null; App.setConn(true);
      return await r.json();
    } catch (e) {
      this.lastError = e.name === 'AbortError' ? 'API timed out' : (e.message || 'API unreachable');
      App.setConn(false, this.lastError);
      if (e.name === 'TypeError' && API.standalone() && !this._offered) { this._offered = true; Unlock.show('Could not reach the API - the tunnel link may have changed. Send /desk in Telegram and paste the new link.'); }
      throw e;
    } finally { clearTimeout(t); }
  },
};

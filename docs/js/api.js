/* API connection: reads #api=...&key=... from the URL, keeps it in localStorage, falls back to DEMO data. */
const API = {
  base: null, key: null, demo: true, lastError: null,
  init() {
    const hp = new URLSearchParams(location.hash.replace(/^#/, ''));
    if (hp.get('api') && hp.get('key')) {
      store.set('api', hp.get('api').replace(/\/$/, '')); store.set('key', hp.get('key'));
      history.replaceState(null, '', location.pathname + location.search);   // keep the key out of the address bar
    }
    if (hp.get('demo') === '1') { store.del('api'); store.del('key'); }
    this.base = store.get('api', null); this.key = store.get('key', null);
    this.demo = !(this.base && this.key);
  },
  disconnect() { store.del('api'); store.del('key'); this.base = this.key = null; this.demo = true; },
  async get(path, params = {}) {
    if (this.demo) return DEMO.get(path, params);
    const u = new URL(this.base + path);
    Object.entries(params).forEach(([k, v]) => v != null && v !== '' && u.searchParams.set(k, v));
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 30000);
    try {
      const r = await fetch(u, { headers: { 'X-Desk-Key': this.key }, signal: ctl.signal });
      if (r.status === 401) throw new Error('Desk key rejected - get a fresh link with /desk in Telegram');
      if (!r.ok) { let d = ''; try { d = (await r.json()).detail } catch { } throw new Error(d || ('HTTP ' + r.status)); }
      this.lastError = null; App.setConn(true);
      return await r.json();
    } catch (e) {
      this.lastError = e.name === 'AbortError' ? 'API timed out' : (e.message || 'API unreachable');
      App.setConn(false, this.lastError);
      throw e;
    } finally { clearTimeout(t); }
  },
};

/* Auto-update: the page knows its own build (meta fd-version). It checks version.json on launch, when the app comes
   back to the foreground and every 5 minutes; a newer build reloads the page by itself. Saved unlock (localStorage +
   IndexedDB), theme and tab survive the reload. Loop guard: the same new version is tried at most once per 10 min. */
const Updater = {
  cur: document.querySelector('meta[name="fd-version"]')?.content || '',
  busy: false, every: 5 * 60 * 1000,
  async latest() {
    const r = await fetch('version.json?t=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) throw new Error('version ' + r.status);
    return (await r.json()).version;
  },
  async check(why = 'timer') {
    if (this.busy || !this.cur) return; this.busy = true;
    try {
      const v = await this.latest();
      if (v && v !== this.cur) {
        const k = 'fd_upd_' + v, last = +sessionStorage.getItem(k) || 0;
        if (Date.now() - last > 10 * 60 * 1000) {
          sessionStorage.setItem(k, Date.now());
          try { const reg = await navigator.serviceWorker?.getRegistration(); await reg?.update(); } catch { }
          window.dispatchEvent(new CustomEvent('fd-update', { detail: { from: this.cur, to: v, why } }));
          location.reload();
        }
      }
    } catch { } finally { this.busy = false; }
  },
  init() {
    if ('serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('sw.js').catch(() => { });
    this.check('launch');
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') this.check('visible'); });
    addEventListener('focus', () => this.check('focus'));
    addEventListener('pageshow', e => { if (e.persisted) this.check('pageshow'); });
    setInterval(() => this.check('timer'), this.every);
  },
};
Updater.init();

/* FlowDesk app shell: splash, router, backgrounds, connection state. */
const App = {
  tab: null, timers: [],
  BGS: [
    { id: 'auto', name: 'Cinematic (theme, per tab)' },
    { id: 'augustus', name: 'Augustus', src: 'assets/bg/bust-augustus.jpg', tint: true },
    { id: 'antinoos', name: 'Antinous', src: 'assets/bg/bust-antinoos.jpg', tint: true },
    { id: 'antoninus', name: 'Antoninus · gold', src: 'assets/bg/bust-antoninus-gold.jpg' },
    { id: 'verus', name: 'Lucius Verus · crimson', src: 'assets/bg/bust-verus-crimson.jpg' },
    { id: 'ocean', name: 'Antinous · ocean', src: 'assets/bg/bust-antinoos-ocean.jpg' },
    { id: 'emerald', name: 'Bronze · emerald', src: 'assets/bg/bust-bronze-emerald.jpg' },
    { id: 'herodotos', name: 'Herodotos', src: 'assets/bg/bust-herodotos.jpg' },
    { id: 'severus', name: 'Severus Alexander', src: 'assets/bg/bust-severus.jpg' },
    { id: 'warrior', name: 'Wounded warrior', src: 'assets/bg/statue-warrior.jpg' },
    { id: 'marblewoman', name: 'White marble · lady', src: 'assets/bg/marble-woman-light.jpg', light: true },
    { id: 'marbleherodotos', name: 'White marble · Herodotos', src: 'assets/bg/marble-herodotos-light.jpg', light: true },
    { id: 'luxskyline', name: 'Luxury · night skyline', src: 'assets/bg/luxury-skyline.jpg' },
    { id: 'luxchandelier', name: 'Luxury · golden lights', src: 'assets/bg/luxury-chandelier.jpg' },
    { id: 'luxharbor', name: 'Luxury · harbour at night', src: 'assets/bg/luxury-harbor.jpg' },
    { id: 'motsummit', name: 'Motivation · summit sunrise', src: 'assets/bg/motivation-summit.jpg' },
    { id: 'motmatterhorn', name: 'Motivation · Matterhorn', src: 'assets/bg/motivation-matterhorn.jpg' },
    { id: 'mottrack', name: 'Motivation · running track', src: 'assets/bg/motivation-track.jpg' },
    { id: 'ascend', name: 'Ascend (generated)', art: 'ascend' },
    { id: 'flow', name: 'Order flow (generated)', art: 'flow' },
    { id: 'none', name: 'Plain' },
  ],
  /* per-tab scene: a slot in the theme's scene list, or generated art on dark themes */
  SCENE: { dashboard: 0, check: 1, chart: 'flow', signals: 'flow', positions: 2, news: 1, journal: 2, performance: 'ascend', learning: 1, settings: 0 },
  scene(tab) { const sc = this.SCENE[tab] ?? 0; const list = Theme.theme.scenes || ['augustus']; if (typeof sc === 'string') return Theme.light ? list[1] || list[0] : sc; return list[sc % list.length]; },
  TABS: ['check', 'dashboard', 'chart', 'signals', 'positions', 'news', 'journal', 'performance', 'learning', 'settings'],
  async init() {
    await Promise.all([API.init(), Names.load()]); Unlock.init();
    $('#demoBanner').hidden = !API.demo;
    $('#unlockOpen')?.addEventListener('click', () => Unlock.show());
    if (API.demo && (new URLSearchParams(location.search).get('unlock') === '1' || (API.standalone() && !store.get('demoChosen', false)))) Unlock.show();
    $('#footSrc').textContent = API.demo ? 'DEMO data' : 'Live API';
    if (!store.get('splash', true)) $('#splash').classList.add('hide'); else setTimeout(() => $('#splash').classList.add('hide'), 1500);
    FX.ambient = FX.dust(); this.applyDim(); Anim.init();
    $('#tabs').addEventListener('click', e => { const b = e.target.closest('button[data-tab]'); if (b) this.go(b.dataset.tab); });
    $('.brand').addEventListener('click', e => { e.preventDefault(); this.go('dashboard'); });
    $('#avatarBtn').onclick = () => this.go('settings');
    $('#bellBtn').onclick = () => this.go('news');
    addEventListener('popstate', () => this.go(this.fromUrl(), false));
    this.go(this.fromUrl(), false);
    this.bell(); this.loadCfg();
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') this.loadCfg(); });
  },
  cfg: null,
  async loadCfg() { try { this.cfg = await API.get('/api/config'); } catch { } return this.cfg; },
  fromUrl() { const t = new URLSearchParams(location.search).get('tab'); return this.TABS.includes(t) ? t : store.get('tab', 'dashboard'); },
  timer(fn, ms) { this.timers.push(setInterval(fn, ms)); },
  async go(tab, push = true) {
    if (!this.TABS.includes(tab)) tab = 'dashboard';
    this.timers.forEach(clearInterval); this.timers = [];
    this.tab = tab; store.set('tab', tab);
    $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
    const on = $(`#tabs button[data-tab="${tab}"]`); if (on) on.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
    if (push) { const u = new URL(location); u.searchParams.set('tab', tab); u.hash = API.hash(); history.pushState(null, '', u); }
    this.applyBg(tab);
    PnlWidget.show(tab === 'dashboard' || tab === 'chart');
    if (tab === 'dashboard' || tab === 'chart') this.timer(() => PnlWidget.refresh(), 15000);
    Anim.stamp(); const v = $('#view'); v.classList.remove('enter'); void v.offsetWidth; v.classList.add('enter');
    window.scrollTo({ top: 0 });
    try { await Views[tab](v); } catch (e) { console.error(e); v.innerHTML = `<div class="panel">${unavailable(tab, e.message)}</div>`; }
  },
  applyBg(tab) {
    let id = store.get('bg', 'auto'); if (id === 'auto') id = this.scene(tab);
    const b = this.BGS.find(x => x.id === id) || this.BGS[1];
    const img = $('#bgImg'), art = $('#bgArt');
    if (b.src) { img.classList.toggle('tinted', !!b.tint); if (img.dataset.src !== b.src) { img.classList.remove('on'); const im = new Image(); im.onload = () => { img.style.backgroundImage = `url(${b.src})`; img.dataset.src = b.src; img.classList.add('on'); }; im.src = b.src; } else img.classList.add('on'); art.classList.remove('on'); }
    else if (b.art) { img.classList.remove('on'); const ak = b.art + Theme.g + Theme.c; if (art.dataset.k !== ak) { FX.drawArt(art, b.art, Math.min(1920, innerWidth * 1.5), Math.min(1200, innerHeight * 1.5)); art.dataset.k = ak; } art.classList.add('on'); }
    else { img.classList.remove('on'); art.classList.remove('on'); }
  },
  applyDim() { const k = store.get('dim', 25) / 100; $('.bg-shade').style.backgroundColor = Theme.light ? `rgba(245,243,238,${k * .8})` : `rgba(0,0,0,${k})`; },
  setConn(ok, msg) { const b = $('#connBanner'); if (ok) { b.hidden = true; return; } b.hidden = false; b.textContent = '⚠ ' + (msg || 'API unreachable') + ' - showing what could be loaded.'; },
  async bell() { try { const c = await API.get('/api/calendar'); const now = Date.now() / 1000; $('#bellDot').hidden = !(c.events || []).some(e => e.impact === 'High' && e.ts > now && e.ts - now < 6 * 3600); } catch { } },
};
document.addEventListener('DOMContentLoaded', () => App.init());

/* "Paste your desk link" unlock screen (home-screen app without credentials, or a stale tunnel link). */
const Unlock = {
  show(msg) {
    const el = $('#unlock'); el.hidden = false; document.body.classList.add('locked');
    $('#ulErr').textContent = msg || ''; $('#ulErr').hidden = !msg;
    setTimeout(() => $('#ulText').focus(), 50);
  },
  hide() { $('#unlock').hidden = true; document.body.classList.remove('locked'); },
  init() {
    const go = async () => {
      const p = API.parseLink($('#ulText').value);
      if (!p) { $('#ulErr').hidden = false; $('#ulErr').textContent = 'That does not look like a FlowDesk link. Paste the whole message from /desk in Telegram.'; return; }
      const b = $('#ulGo'); b.disabled = true; b.textContent = 'Checking…';
      const err = await API.verify(p.api, p.key);
      b.disabled = false; b.textContent = 'Unlock desk';
      if (err && /rejected/.test(err) && !$('#ulErr').dataset.force) { $('#ulErr').hidden = false; $('#ulErr').textContent = err + ' Tap Unlock again to save it anyway.'; $('#ulErr').dataset.force = '1'; return; }
      API.save(p.api, p.key); location.reload();
    };
    $('#ulGo').onclick = go;
    $('#ulText').addEventListener('input', () => { delete $('#ulErr').dataset.force; });
    $('#ulPaste').onclick = async () => { try { $('#ulText').value = await navigator.clipboard.readText(); go(); } catch { $('#ulText').focus(); } };
    $('#ulDemo').onclick = () => { store.set('demoChosen', true); this.hide(); };
  },
};

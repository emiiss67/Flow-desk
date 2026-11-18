/* FlowDesk app shell: splash, router, backgrounds, connection state. */
const App = {
  tab: null, timers: [],
  BGS: [
    { id: 'auto', name: 'Cinematic (per tab)' },
    { id: 'augustus', name: 'Marble · Augustus', src: 'assets/bg/bust-augustus.jpg' },
    { id: 'antinoos', name: 'Marble · Antinous', src: 'assets/bg/bust-antinoos.jpg' },
    { id: 'ascend', name: 'Ascend (generated)', art: 'ascend' },
    { id: 'flow', name: 'Order flow (generated)', art: 'flow' },
    { id: 'none', name: 'Pure black' },
  ],
  SCENE: { dashboard: 'augustus', check: 'antinoos', chart: 'flow', signals: 'flow', positions: 'augustus', news: 'antinoos', journal: 'augustus', performance: 'ascend', settings: 'augustus' },
  TABS: ['check', 'dashboard', 'chart', 'signals', 'positions', 'news', 'journal', 'performance', 'settings'],
  init() {
    API.init();
    $('#demoBanner').hidden = !API.demo;
    $('#footSrc').textContent = API.demo ? 'DEMO data' : 'Live API';
    if (!store.get('splash', true)) $('#splash').classList.add('hide'); else setTimeout(() => $('#splash').classList.add('hide'), 1500);
    FX.dust(); this.applyDim();
    $('#tabs').addEventListener('click', e => { const b = e.target.closest('button[data-tab]'); if (b) this.go(b.dataset.tab); });
    $('.brand').addEventListener('click', e => { e.preventDefault(); this.go('dashboard'); });
    $('#avatarBtn').onclick = () => this.go('settings');
    $('#bellBtn').onclick = () => this.go('news');
    addEventListener('popstate', () => this.go(this.fromUrl(), false));
    this.go(this.fromUrl(), false);
    this.bell();
  },
  fromUrl() { const t = new URLSearchParams(location.search).get('tab'); return this.TABS.includes(t) ? t : store.get('tab', 'dashboard'); },
  timer(fn, ms) { this.timers.push(setInterval(fn, ms)); },
  async go(tab, push = true) {
    if (!this.TABS.includes(tab)) tab = 'dashboard';
    this.timers.forEach(clearInterval); this.timers = [];
    this.tab = tab; store.set('tab', tab);
    $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
    const on = $(`#tabs button[data-tab="${tab}"]`); if (on) on.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
    if (push) { const u = new URL(location); u.searchParams.set('tab', tab); u.hash = ''; history.pushState(null, '', u); }
    this.applyBg(tab);
    const v = $('#view'); v.classList.remove('enter'); void v.offsetWidth; v.classList.add('enter');
    window.scrollTo({ top: 0 });
    try { await Views[tab](v); } catch (e) { console.error(e); v.innerHTML = `<div class="panel">${unavailable(tab, e.message)}</div>`; }
  },
  applyBg(tab) {
    let id = store.get('bg', 'auto'); if (id === 'auto') id = this.SCENE[tab] || 'augustus';
    const b = this.BGS.find(x => x.id === id) || this.BGS[1];
    const img = $('#bgImg'), art = $('#bgArt');
    if (b.src) { if (img.dataset.src !== b.src) { img.classList.remove('on'); const im = new Image(); im.onload = () => { img.style.backgroundImage = `url(${b.src})`; img.dataset.src = b.src; img.classList.add('on'); }; im.src = b.src; } else img.classList.add('on'); art.classList.remove('on'); }
    else if (b.art) { img.classList.remove('on'); const ak = b.art + Theme.g + Theme.c; if (art.dataset.k !== ak) { FX.drawArt(art, b.art, Math.min(1920, innerWidth * 1.5), Math.min(1200, innerHeight * 1.5)); art.dataset.k = ak; } art.classList.add('on'); }
    else { img.classList.remove('on'); art.classList.remove('on'); }
  },
  applyDim() { $('.bg-shade').style.backgroundColor = `rgba(0,0,0,${store.get('dim', 25) / 100})`; },
  setConn(ok, msg) { const b = $('#connBanner'); if (ok) { b.hidden = true; return; } b.hidden = false; b.textContent = '⚠ ' + (msg || 'API unreachable') + ' - showing what could be loaded.'; },
  async bell() { try { const c = await API.get('/api/calendar'); const now = Date.now() / 1000; $('#bellDot').hidden = !(c.events || []).some(e => e.impact === 'High' && e.ts > now && e.ts - now < 6 * 3600); } catch { } },
};
document.addEventListener('DOMContentLoaded', () => App.init());

/* Tab views */
const Views = {};
const ICON_SEARCH = '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>';
const sidePill = s => `<span class="pill ${s === 'LONG' ? 'long' : s === 'SHORT' ? 'short' : 'none'}">${s === 'LONG' ? '▲' : s === 'SHORT' ? '▼' : '•'} ${esc(sideWord(s))}</span>`;
const fold = (title, html, extra = '') => Mode.simple() ? `<details class="panel fold" style="margin-top:16px"><summary>${title}</summary>${html}</details>` : `<div class="panel" style="margin-top:16px"><h3>${title}${extra}</h3>${html}</div>`;
const unavailable = (what, err) => `<div class="unavail">${esc(what)}: data unavailable${err ? `<br><span style="font-size:11.5px;color:var(--dim)">${esc(err)}</span>` : ''}</div>`;
const greeting = () => { const h = new Date().getHours(); return h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'; };
async function load(path, params) { try { return [await API.get(path, params), null]; } catch (e) { return [null, e.message || String(e)]; } }

function topupBar() {
  if (API.demo) return '';
  return `<form class="topup-row" id="topupForm" action="#" onsubmit="return false">
      <span class="m">${esc(Cur.sym)}</span>
      <input id="topupAmt" type="number" min="0.01" step="0.01" inputmode="decimal" placeholder="Amount" aria-label="Top-up amount in euros">
      <button type="submit" class="btn pri" id="topupBtn">Top up</button>
      <button type="button" class="btn" id="withdrawBtn">Withdraw</button>
    </form>`;
}
function bindTopup() {
  const go = async (kind) => {
    const inp = $('#topupAmt');
    if (!inp) return;
    const amt = Number(String(inp.value || '').replace(',', '.'));
    if (!isFinite(amt) || amt <= 0) { toast('Enter an amount in euros'); inp.focus(); return; }
    const isW = kind === 'withdraw';
    const msg = (isW ? 'Withdraw ' : 'Add ') + money2(amt) + (isW ? ' from' : ' to') + ' the paper balance? This is a ' + (isW ? 'withdrawal' : 'deposit') + ', not P&L.';
    if (!confirm(msg)) return;
    const btn = isW ? $('#withdrawBtn') : $('#topupBtn');
    if (btn) btn.disabled = true;
    try {
      const r = await API.get(isW ? '/api/withdraw' : '/api/topup', { amount: amt, confirm: 1 });
      toast((isW ? 'Withdrew ' : 'Topped up ') + money2(r.amount || amt) + ' · balance ' + money2(r.balance));
      App.go(App.tab || 'dashboard', false);
    } catch (e) {
      toast((isW ? 'Withdraw' : 'Top up') + ' failed: ' + e.message);
      if (btn) btn.disabled = false;
    }
  };
  const form = $('#topupForm'); if (!form) return;
  form.addEventListener('submit', ev => { ev.preventDefault(); go('topup'); });
  const w = $('#withdrawBtn'); if (w) w.addEventListener('click', () => go('withdraw'));
}

/* ================= DASHBOARD ================= */
const SETUP_NAMES = ['HVN Absorption', 'Key Level Absorption Reversal'];
const isSetup = x => SETUP_NAMES.includes(x);
const tagH = x => `<span class="tag${isSetup(x) ? ' setup' : ''}">${isSetup(x) ? '🎯 ' : ''}${esc(x)}</span>`;
const tagsH = (arr, setup, side) => { if (Mode.simple()) return whyH(arr, side, setup); const a = [...new Set([...(setup ? [setup] : []), ...(arr || [])])]; return a.sort((p, q) => isSetup(q) - isSetup(p)).map(tagH).join(''); };

Views.dashboard = async (v) => {
  v.innerHTML = `<div class="greet"><div><h1>${Theme.theme.tf ? 'Welcome back' : greeting()}, ${esc(store.get('name', 'Emis'))}.</h1>
    <div class="sub">${new Date().toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })} · <span id="mkt"></span></div>${Quotes.on() ? `<div class="quote">“${esc(Quotes.today())}”</div>` : ''}</div>
    <div class="seg" id="dashRange"><button class="on">30D</button></div></div>
    <div class="grid cols-main" style="margin-top:8px"><div id="dMain"><div class="skeleton" style="height:420px"></div></div><div id="dSide"></div></div>`;
  const [[d, err], [perf]] = await Promise.all([load('/api/dashboard'), load('/api/performance')]);
  if (!d) { $('#dMain').innerHTML = `<div class="panel">${unavailable('Dashboard', err)}</div>`; return; }
  const kz = (() => { const ny = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' })); const t = ny.getHours() + ny.getMinutes() / 60, wd = ny.getDay();
    if (wd === 6 || (wd === 0 && t < 18) || (wd === 5 && t >= 17)) return 'Markets closed (weekend)'; if (t >= 2 && t < 5) return 'London killzone active'; if (t >= 7 && t < 10) return 'New York killzone active'; if (t >= 20) return 'Asia session'; return 'Markets open'; })();
  $('#mkt').textContent = kz;
  const net30 = d.daily_30.reduce((a, b) => a + b.pnl, 0);
  const heroNet = d.reset ? (d.net ?? 0) : net30;   // after a paper reset the headline counts from the fresh €50 start
  const heroLbl = d.reset ? `Net P&amp;L · since reset ${new Date(d.reset.ts * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}` : 'Net P&amp;L · 30 days';
  const st = d.status; const stCls = st === 'running' ? '' : st === 'paused' ? 'pause' : 'off';
  const lt = d.last_trades || []; const mx = Math.max(1, ...lt.map(t => Math.abs(t.pnl)));
  const dm = Math.max(1, ...d.daily_30.map(x => Math.abs(x.pnl)));
  const streakDash = Array.from({ length: 14 }, (_, i) => { const t = lt[lt.length - 14 + i]; return `<i class="${t ? (t.pnl > 0 ? 'w' : 'l') : ''}"></i>`; }).join('');
  $('#dMain').innerHTML = `
    <div class="hero"><div class="label">${heroLbl}</div><div class="huge num ${heroNet > 0 ? 'glow-g' : heroNet < 0 ? 'glow-r' : ''}">${money(heroNet)}</div>
      <div class="sub">Paper balance <b class="num hi">${money2(d.balance)}</b> · equity <span class="num">${money2(d.equity)}</span>${d.deposited ? ` · deposits <b class="num">${money2(d.deposited)}</b> <span class="m">(not in P&amp;L)</span>` : ''}</div>
      ${topupBar()}</div>
    <div class="grid cols-4" style="margin-top:26px">
      <div class="panel stat"><div class="label">Status today</div><div class="v"><span class="dot-live ${stCls}"></span>${st === 'running' ? 'Clean' : st === 'paused' ? 'Paused' : 'Offline'}</div><div class="sub">${d.daily_limit_hit ? `<span class="r">Daily loss limit hit</span>${API.demo ? '' : ' <button class="btn" id="resetDL" style="padding:6px 10px;margin-top:6px">Reset daily limit</button>'}` : 'Bot ' + esc(st) + (d.heartbeat ? ' · scan ' + ago(d.heartbeat) : '')}</div></div>
      <div class="panel stat"><div class="label">Net result · today</div><div class="v num ${pnlClass(d.today_pnl)}">${money(d.today_pnl)}</div><div class="sub">Realized, paper</div></div>
      <div class="panel stat"><div class="label">Win rate</div><div class="v num">${d.win_rate}%</div><div class="sub">${d.trades} closed trades${Mode.simple() ? '' : ` · PF ${d.profit_factor ?? '–'}`}</div></div>
      <div class="panel stat"><div class="label">Risk blocks · 24h</div><div class="v num">${d.blocked_24h}</div><div class="sub">${d.signals_24h} signals · ${d.entries_24h} entries</div></div>
    </div>
    <div class="panel eq-dash" style="margin-top:16px"><h3>Equity curve <span class="right">hover or drag to read any point</span></h3><div class="eq-box"><canvas id="eqd"></canvas></div></div>
    <div class="grid cols-3" style="margin-top:16px">
      <div class="panel"><h3>Win streak</h3><div class="big num">${d.streak}</div><div class="sub">wins in a row · best ${d.best_streak}</div><div class="streak">${streakDash}</div></div>
      <div class="panel"><h3>Last 14 trades</h3><div class="bars-mid"><div class="axis"></div><div class="cols">${lt.length ? lt.map((t, i) => `<div class="col" data-i="${i}" title="${esc(nm(t.symbol))} ${t.side || ''} ${money(t.pnl)}${t.stake ? ' · ' + esc(stakeText(t.stake)) + (t.stake.pnl_pct_of_risk != null ? ' · P&L ' + t.stake.pnl_pct_of_risk + '% of risk' : '') : ''}"><i class="${t.pnl > 0 ? 'p' : 'n'}" style="height:${Math.max(3, Math.abs(t.pnl) / mx * 48)}%"></i></div>`).join('') : '<div class="m" style="margin:auto;font-size:13px">No trades yet</div>'}</div></div>
        ${lt.slice(-3).reverse().map(t => `<div class="lt-row"><div><b>${nmH(t.symbol)}</b> ${t.side ? sidePill(t.side) : ''} <span class="m num" style="font-size:11.5px">${dmy(t.time)} ${hm(t.time)}</span><b class="num right ${pnlClass(t.pnl)}">${money(t.pnl)}</b></div>${stakeRow(t.stake, { pnl: true })}</div>`).join('')}</div>
      <div class="panel"><h3>P&amp;L · 30 days <span class="right num ${pnlClass(net30)}">${money(net30)}</span></h3><div class="bars">${d.daily_30.map(x => `<div class="b ${x.pnl > 0 ? 'p' : x.pnl < 0 ? 'n' : 'z'}" title="${x.date} ${money(x.pnl)}" style="height:${x.pnl ? Math.max(6, Math.abs(x.pnl) / dm * 100) : 3}%"></div>`).join('')}</div></div>
    </div>
    ${fold('When it works · hour by weekday', heatmap(d.heatmap), ' <span class="right">UTC hours · entries</span>')}`;
  { const nowS = Math.floor(Date.now() / 1000); let ser = perf?.equity_curve?.length ? perf.equity_curve : (perf?.equity_snapshots?.length >= 2 ? perf.equity_snapshots : []);
    if (!ser.length) ser = [{ time: nowS - 7 * 86400, value: d.balance }, { time: nowS, value: d.balance }];
    FX.equity($('#eqd'), ser, { base: perf?.start_balance ?? ser[0].value, small: true, pad: { t: 30, r: 64 } }); }
  const rb = $('#resetDL'); if (rb) rb.onclick = async () => { if (!confirm('Restart today\'s daily-loss window from the current balance? The ' + 'limit % stays the same.')) return; rb.disabled = true; try { const r = await API.get('/api/reset_daily', { confirm: 1 }); toast('Daily limit reset · new baseline ' + money2(r.baseline)); App.go('dashboard', false); } catch (e) { toast('Reset failed: ' + e.message); rb.disabled = false; } };
  bindTopup();
  const ev = d.upcoming_events || [];
  $('#dSide').innerHTML = sessionCard(d.session) + `
    <div class="panel"><h3>Today's plan</h3><ul class="plan">${d.plan.map(p => `<li><span class="ck">✓</span>${esc(p)}</li>`).join('')}</ul></div>
    <div class="panel" style="margin-top:16px"><h3>Open positions <span class="right">${d.open_positions.length}</span></h3>${d.open_positions.length ? d.open_positions.map(p => `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid var(--line)"><div><b>${nmH(p.symbol)}</b> ${sidePill(p.side)}<div class="sub">@ ${fp(p.entry)} · SL ${fp(p.sl)}</div></div><div class="num ${pnlClass(p.unrealized)}" style="font-weight:800">${money(p.unrealized)}</div></div>${p.stake ? `<div style="padding:0 0 8px;border-bottom:1px solid var(--line);margin-top:-1px">${stakeRow(p.stake)}</div>` : ''}`).join('') : '<div class="m" style="font-size:13px">Flat. Waiting for confluence.</div>'}</div>
    <div class="panel" style="margin-top:16px"><h3>High-impact next</h3>${ev.length ? ev.map(e => `<div class="ev" style="grid-template-columns:60px 40px 1fr"><span class="m num">${inTime(e.ts)}</span><span class="ccy">${esc(e.ccy)}</span><span><i class="imp High" style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px"></i>${esc(e.title)}</span></div>`).join('') : '<div class="m" style="font-size:13px">Nothing high-impact left this week.</div>'}</div>
    <div class="panel glass-lite" style="margin-top:16px"><h3>About to trade?</h3><div class="sub" style="margin:0 0 12px">Run any instrument through the order-flow + ICT check first.</div><button class="btn pri" style="width:100%" onclick="App.go('check')">Open pre-trade check →</button></div>`;
};

function heatmap(hm) {
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
  let s = '<div class="heat"><div></div>' + Array.from({ length: 24 }, (_, i) => `<div class="h">${i % 3 === 0 ? String(i).padStart(2, '0') : ''}</div>`).join('');
  const mx = Math.max(1, ...Object.values(hm || {}).map(c => Math.abs(c.pnl)));
  days.forEach((d, di) => { s += `<div class="d">${d}</div>`; for (let hr = 0; hr < 24; hr++) { const c = (hm || {})[di + '-' + hr]; let cls = ''; if (c) { const k = Math.abs(c.pnl) / mx; cls = c.pnl > 0 ? (k > .35 ? 'p' : 'p2') : c.pnl < 0 ? (k > .35 ? 'n' : 'n2') : ''; } s += `<div class="cell ${cls}" title="${d} ${hr}:00 UTC${c ? ' · ' + c.n + ' trades · ' + money(c.pnl) : ''}"></div>`; } });
  return s + '</div>';
}

/* ================= CHECK ================= */
Views.check = async (v) => {
  const sel = store.get('checkSym', 'EURUSD=X'); const tf = store.get('checkTf', '15m'); let cat = store.get('checkCat', 'All');
  v.innerHTML = `<div class="page-title">Pre-trade check</div><div class="page-sub">Pick any instrument, press Check. FlowDesk reads estimated order flow, ICT structure, liquidity and the news calendar, then calls it. <span class="est">order flow estimated</span></div>
  <div class="grid check-layout">
    <div><div class="panel">
      <h3>Instrument</h3>
      <div class="filters" id="cats">${['All', 'Forex', 'Indices', 'Futures', 'Commodities', 'Crypto'].map(c => `<button class="chip ${c === cat ? 'on' : ''}" data-c="${c}">${c}</button>`).join('')}</div>
      <div class="search">${ICON_SEARCH}<input id="q" placeholder="${smp('Search a market, e.g. Gold, EUR/USD, Nasdaq', 'Search or type any Yahoo ticker (e.g. AAPL, EURNOK)')}" autocomplete="off" autocapitalize="characters" spellcheck="false"></div>
      <div class="inst-list" id="ilist"></div>
      <div class="selected-inst"><div><div class="label" style="margin:0 0 4px">Selected</div><div class="n" id="selSym">${nmH(sel)}</div></div><div class="seg" id="tfs">${['5m', '15m', '1h', '4h', '1d'].map(t => `<button data-tf="${t}" class="${t === tf ? 'on' : ''}">${t}</button>`).join('')}</div></div>
      <button class="check-btn" id="go">Check</button>
      <div class="sub" style="text-align:center;margin-top:10px">Analysis only · never places a trade</div>
    </div></div>
    <div id="res"><div class="panel empty"><div><div class="big-ic">◎</div><div class="hi" style="font-weight:600;margin-bottom:6px">Ready when you are</div>Select an instrument and press <b>Check</b>.</div></div><div id="topBox"></div></div>
  </div>`;
  load('/api/signal/top', { limit: 5 }).then(([t]) => { const b = $('#topBox'); if (b && t && t.ok) b.innerHTML = topHTML(t); });
  let items = INSTRUMENTS; let selected = sel; let tfSel = tf;
  load('/api/instruments').then(([r]) => { if (r?.items?.length) { items = r.items; draw(); } });
  const draw = () => {
    const q = $('#q').value.trim().toLowerCase();
    const list = items.filter(i => (cat === 'All' || i.category === cat) && (!q || i.symbol.toLowerCase().includes(q) || i.name.toLowerCase().includes(q) || nm(i.symbol).toLowerCase().includes(q)));
    let html = list.map(i => `<div class="inst ${i.symbol === selected ? 'on' : ''}" data-s="${esc(i.symbol)}"><b>${nmH(i.symbol)}</b><span>${esc(i.name)}</span></div>`).join('');
    if (q && !list.some(i => i.symbol.toLowerCase() === q)) html = `<div class="inst" data-s="${esc($('#q').value.trim().toUpperCase())}"><b>${esc($('#q').value.trim().toUpperCase())}</b><span>${smp('Look up this market →', 'Use as Yahoo ticker →')}</span></div>` + html;
    $('#ilist').innerHTML = html || '<div class="m" style="padding:10px;font-size:13px">No match</div>';
  };
  draw();
  $('#q').addEventListener('input', draw);
  $('#q').addEventListener('keydown', e => { if (e.key === 'Enter') { const f = $('#ilist .inst'); if (f) f.click(); run(); } });
  $('#cats').addEventListener('click', e => { const b = e.target.closest('.chip'); if (!b) return; cat = b.dataset.c; store.set('checkCat', cat); $$('#cats .chip').forEach(x => x.classList.toggle('on', x === b)); draw(); });
  $('#ilist').addEventListener('click', e => { const it = e.target.closest('.inst'); if (!it) return; selected = it.dataset.s; store.set('checkSym', selected); $('#selSym').innerHTML = nmH(selected); draw(); });
  $('#tfs').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; tfSel = b.dataset.tf; store.set('checkTf', tfSel); $$('#tfs button').forEach(x => x.classList.toggle('on', x === b)); });
  const run = async (ev) => {
    const notify = !!(ev && ev.isTrusted) && !API.demo;   // a real press of Check also sends the result to Telegram
    const btn = $('#go'); btn.disabled = true; btn.innerHTML = '<span class="spin"></span>Reading the flow…';
    $('#res').innerHTML = '<div class="panel"><div class="skeleton" style="height:120px"></div><div class="skeleton" style="height:330px;margin-top:14px"></div></div>';
    const [r, err] = await load('/api/check', { symbol: selected, tf: tfSel, notify: notify ? 1 : '' });
    btn.disabled = false; btn.textContent = 'Check';
    if (!r || !r.ok) { $('#res').innerHTML = `<div class="panel">${unavailable(selected, err || r?.detail)}</div>`; return; }
    renderResult(r);
  };
  $('#go').addEventListener('click', e => run(e));
  if (store.get('autoCheck', false) || App.demoAuto) { App.demoAuto = false; run(); }
};

function renderResult(r) {
  const D = r.decision; const cls = D === 'LONG' ? 'long' : D === 'SHORT' ? 'short' : 'none';
  const col = D === 'LONG' ? Theme.g : D === 'SHORT' ? Theme.r : '#9CA3AF'; const lv = r.levels;
  const risk = lv ? Math.abs(lv.entry - lv.sl) : null;
  $('#res').innerHTML = `
    <div id="sigBox"><div class="panel"><div class="skeleton" style="height:90px"></div></div></div>
    <div class="panel" style="margin-top:16px">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">
        <div><div class="label" style="margin-bottom:6px">${nmH(r.symbol)}${r.name && r.name !== r.symbol && !Mode.simple() ? ' · ' + esc(r.name) : ''} · ${esc(r.tf)} · ${esc(r.category || '')}</div>
          ${r.setup ? `<div class="setup-badge" style="margin-bottom:10px">🎯 ${esc(r.setup)}</div>` : (r.setups || []).length ? `<div class="sub" style="margin:0 0 8px">Setup seen on the other side: ${esc(r.setups.map(x => x.name + ' (' + x.side + ')').join(', '))}</div>` : ''}
          <div class="verdict"><div class="call ${cls}">${esc(sideWord(D))}</div>
          <div class="gauge" title="Confluence score: how many independent reasons line up, weighted. It is a score out of 100, not a probability of winning.">${FX.gauge(r.confluence, col)}<div class="gv num" style="color:${col}">${r.confluence}</div><div class="gl">${smp('score /100', 'confluence /100')}</div></div></div>
          ${Mode.simple() ? simpleCall(r) : '<div class="sub" style="margin-top:8px">Confluence score (0-100) · not a probability of winning</div>'}</div>
        <div style="text-align:right"><div class="label" style="margin-bottom:6px">${smp('Price now', 'Last price')}</div><div class="big num mono">${fp(r.price)}</div>${Mode.simple() ? '' : `<div class="sub">L ${r.scores.long} · S ${r.scores.short} · ATR ${fp(r.atr)}</div>`}</div>
      </div>
      ${lv ? `<div class="levels">
${Mode.simple() ? simpleLevels(r, lv) : `
        <div class="lv en"><div class="k">Entry</div><div class="v">${fp(lv.entry)}</div></div>
        <div class="lv sl"><div class="k">Stop loss</div><div class="v">${fp(lv.sl)}</div><div class="sub">${esc(lv.sl_basis)} · ${fp(risk)}</div></div>
        <div class="lv tp"><div class="k">TP1 · ${lv.rr1}R</div><div class="v">${fp(lv.tp1)}</div><div class="sub">${esc(lv.tp1_basis)}</div></div>
        <div class="lv tp"><div class="k">TP2 · ${lv.rr2}R</div><div class="v">${fp(lv.tp2)}</div><div class="sub">${esc(lv.tp2_basis)}</div></div>
        <div class="lv"><div class="k">Risk : reward</div><div class="v">1 : ${lv.rr2}</div><div class="sub">50% off at TP1</div></div>`}</div>`
      : Mode.simple() ? '' : `<div class="warn" style="margin-top:16px">⚪ ${esc(r.watch?.note || 'Not enough confluence')}${r.watch ? ` · lean ${esc(r.watch.bias.toLowerCase())}, ref SL ${fp(r.watch.sl)} / TP ${fp(r.watch.tp1)}` : ''}</div>`}
      <div id="wrBox">${wrHTML(r.winrate, r)}</div>
      <div id="szBox">${szHTML(r)}</div>
      ${r.telegram === 'sent' ? '<div class="sub" style="margin-top:8px">📨 Also sent to your Telegram.</div>' : ''}
      ${r.blackout ? `<div class="warn block">⛔ High-impact ${esc(r.blackout.ccy)} event "${esc(r.blackout.title)}" too close - standing aside.</div>` : ''}
      ${(r.warnings || []).map(w => `<div class="warn">⚠️ ${esc(w.text)}</div>`).join('')}
    </div>
    <div class="panel" style="margin-top:16px;padding:12px"><div class="toggles" id="ckTg" style="margin-bottom:8px">${[['imb', 'Imbalance levels'], ['hvz', 'HVN zones'], ['habs', 'Heavy absorption']].map(([k, n]) => `<button class="chip ${ckTg()[k] ? 'on' : ''}" data-k="${k}">${n}</button>`).join('')}</div><div class="chart-box" id="ckChart"></div>
      <div class="legend"><span><i style="background:rgba(${Theme.G},.35)"></i>Bull FVG</span><span><i style="background:rgba(${Theme.R},.35)"></i>Bear FVG</span><span><i style="background:rgba(${Theme.C},.45)"></i>Bull OB</span><span><i style="background:rgba(245,181,68,.45)"></i>Bear OB · POC</span><span><i style="background:rgba(110,139,255,.4)"></i>Killzones</span><span>$$$ liquidity</span><span><i style="background:rgba(225,50,120,.6)"></i>Imbalance (ratio | count)</span><span><i style="background:rgba(245,170,50,.8)"></i>HVN (volume | % session)</span><span>◯ heavy absorption: <b class="g">green</b> trapped buyers · <b class="r">red</b> trapped sellers</span></div></div>
    ${Mode.simple() ? '<details class="fold-plain" style="margin-top:16px"><summary>All the details behind this call</summary>' : ''}<div class="grid cols-2" style="margin-top:16px">
      <div class="panel"><h3>Why ${D === 'NO TRADE' ? '(strongest side)' : esc(D.toLowerCase())}</h3><ul class="reasons">${r.reasons.map(x => `<li class="${isSetup(x.tag) ? 'is-setup' : ''}"><span class="pt">+${x.points}</span><div>${esc(deTicker(x.text))}${Mode.simple() ? '' : `<div>${tagH(x.tag)}</div>`}</div></li>`).join('') || '<li class="m">No confluence found</li>'}</ul></div>
      <div class="panel"><h3>Against it</h3><ul class="reasons against">${(r.against || []).map(x => `<li><span class="pt">-${x.points}</span><div>${esc(deTicker(x.text))}${Mode.simple() ? '' : `<div><span class="tag">${esc(x.tag)}</span></div>`}</div></li>`).join('') || '<li class="m" style="font-size:13px">Nothing meaningful against it.</li>'}</ul>
        ${(r.headlines || []).length ? `<h3 style="margin-top:16px">Related headlines</h3>${r.headlines.map(n => `<a class="news-item" href="${esc(n.link)}" target="_blank" rel="noopener"><div class="t">${esc(n.title)}</div><div class="meta">${esc(n.source)} · ${ago(n.ts)}</div></a>`).join('')}` : ''}
        <div class="sub" style="margin-top:14px">Source: ${esc(r.source)}. ${esc(r.source_note || '')} Order flow: <span class="est">estimated</span> (${esc(r.volume_source || 'OHLCV')}).</div></div>
    </div>${Mode.simple() ? '</details>' : ''}`;
  load('/api/signal', { symbol: r.symbol }).then(([d]) => { const b = $('#sigBox'); if (!b) return; b.innerHTML = d && d.ok ? signalHTML(d) : ''; });
  const c = Charts.create($('#ckChart')); Charts.set(c, r, ckTg());
  $('#ckTg').addEventListener('click', e => { const b = e.target.closest('.chip'); if (!b) return; const t = ckTg(); t[b.dataset.k] = !t[b.dataset.k]; store.set('ckToggles', t); b.classList.toggle('on', t[b.dataset.k]); c.opts[b.dataset.k] = t[b.dataset.k]; Charts.set(c, r, Object.assign({ fit: false }, t)); });
  if (r.winrate && r.winrate.status === 'computing') pollWR(r);
}

/* ---- "Best strategy" panel: same call the live bot would make (finished candles, costs, quality gate, risk caps) ---- */
const sgStat = z => (!z || !z.n) ? '<span class="m">no history yet</span>'
  : `<b class="num">${Math.round(z.win_rate)}%</b> win · <b class="num ${pnlClass(z.exp_r)}">${z.exp_r > 0 ? '+' : ''}${(+z.exp_r).toFixed(2)}R</b>${smp('', ' / trade')} · n=${z.n}${z.low_sample ? ' <span class="warn-t" title="Fewer than 10 held-out trades: anecdotal">⚠ low sample</span>' : ''}`;
function signalHTML(d) {
  const buy = d.call === 'BUY', sell = d.call === 'SELL', act = buy || sell, p = d.plan, z = d.size;
  const col = buy ? Theme.g : sell ? Theme.r : '#9CA3AF';
  const rg = d.regime ? `${esc(d.regime.trend)} · ${esc(d.regime.session)} · ${esc(d.regime.volatility)} volatility` : '';
  const head = `<div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:flex-start">
    <div><div class="label" style="margin-bottom:6px">${smp('Best strategy for ' + esc(d.name), 'Best strategy · ' + esc(d.name) + ' · ' + esc(d.tf))}</div>
      ${d.best ? `<div style="font-weight:700;font-size:16px">🏆 ${esc(d.best.name)}${d.best.edge ? '' : ' <span class="sub">(best available - no proven edge here)</span>'}</div><div class="sub" style="margin:4px 0 0">${smp('Its record on this market (tested on data it never saw, after costs): ', esc(d.best.basis) + ': ')}${sgStat(d.best)}</div>` : '<div class="sub">No strategy is allowed to trade this market right now.</div>'}
      ${rg && !Mode.simple() ? `<div class="sub" style="margin:4px 0 0">Regime now: ${rg}</div>` : ''}</div>
    <div style="text-align:right"><div class="call ${buy ? 'long' : sell ? 'short' : 'none'}" style="font-size:26px">${smp(act ? (buy ? 'Buy' : 'Sell') : 'No trade', d.call)}</div>
      ${act ? `<div class="sub" style="margin:2px 0 0">via ${esc(d.strategy.name)}</div>` : ''}</div></div>`;
  let body = '';
  if (act) {
    body = `<div class="levels" style="margin-top:14px">
      <div class="lv en"><div class="k">Entry</div><div class="v">${fp(p.entry)}</div></div>
      <div class="lv sl"><div class="k">${smp('Stop loss', 'Stop')}</div><div class="v">${fp(p.sl)}</div>${z ? `<div class="sub">lose ${money2(z.risk_amount)}</div>` : ''}</div>
      <div class="lv tp"><div class="k">${smp('Take profit 1', 'Target 1')} · ${p.rr1}R</div><div class="v">${fp(p.tp1)}</div></div>
      <div class="lv tp"><div class="k">${smp('Take profit 2', 'Target 2')} · ${p.rr2}R</div><div class="v">${fp(p.tp2)}</div></div></div>
      ${z ? `<div class="sz"><div class="sz-pct num">${z.risk_pct}%</div><div><div class="k">${smp('Money at risk on this trade', 'Suggested risk (win-rate sizing)')}</div><div class="sub" style="margin:2px 0 0">${esc(d.risk_reason || '')}${z.notes?.length ? ' · ' + esc(z.notes.join('; ')) : ''}</div><div class="sub" style="margin:4px 0 0"><b class="hi num">${money2(z.risk_amount)}</b> of your ${money2(z.equity)} balance · size <span class="num">${esc(z.size_text)}</span> · <b class="num">${levTxt(z.leverage)}</b></div></div></div>` : ''}
      <div class="plain" style="margin-top:10px"><b>${buy ? 'Buy' : 'Sell'}</b>: ${esc((d.reason || '').charAt(0).toLowerCase() + (d.reason || '').slice(1))}</div>
      ${d.note ? `<div class="sub" style="margin-top:6px">ℹ️ ${esc(d.note)}</div>` : ''}`;
  } else {
    body = `<div class="warn" style="margin-top:14px">⚪ <b>${smp('Nothing to do right now', 'NO TRADE')}</b> - ${esc(d.waiting || '')}</div>`;
  }
  const ru = (d.runner_ups || []).slice(0, Mode.simple() ? 2 : 4);
  const rus = ru.length ? `<div style="margin-top:14px"><div class="label" style="margin-bottom:6px">${smp('Other strategies for this market', 'Runner-ups')}</div>${ru.map(x => `<div class="sub" style="margin:3px 0"><b class="hi">${esc(x.name)}</b> · ${sgStat(x)} · ${x.action ? `<b class="${x.action === 'BUY' ? 'g' : 'r'}">${x.action} signal</b> (skipped: ${esc(x.note || '')})` : `<span class="m">${esc((x.note || 'no signal now').split(':')[0].slice(0, 70))}</span>`}</div>`).join('')}</div>` : '';
  return `<div class="panel" style="border-left:3px solid ${col}">${head}${body}${rus}
    <div class="sub" style="margin-top:10px">${smp('Uses the same rules as the live bot: only finished candles, costs included. Paper trading only.', 'Same gates as live trading: closed candles, learned blocks/regime, quality gate (cost ≤ 0.20R), live-quote re-anchor, risk caps, win-rate sizing. Held-out stats = validation + test, net of spread/slippage. Paper only.')}</div></div>`;
}
function topHTML(t) {
  const rows = (t.actionable || []).map(d => { const buy = d.call === 'BUY';
    return `<div class="inst" style="cursor:default;display:block"><div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap"><div><b>${nmH(d.symbol)}</b> <b class="${buy ? 'g' : 'r'}">${smp(buy ? 'Buy' : 'Sell', d.call)}</b> · <span class="hi">${esc(d.strategy.name)}</span></div><div class="sub" style="margin:0">${sgStat(d.strategy)}</div></div>
      <div class="sub" style="margin:3px 0 0">Entry <span class="num">${fp(d.plan.entry)}</span> · ${smp('Stop', 'SL')} <span class="num">${fp(d.plan.sl)}</span> · ${smp('Take profit', 'TP1')} <span class="num">${fp(d.plan.tp1)}</span> (${d.plan.rr1}R) · risk ${d.risk_pct}%</div></div>`; }).join('');
  const near = (t.near || []).map(d => `<div class="sub" style="margin:3px 0"><b class="hi">${nmH(d.symbol)}</b>: ${esc((d.waiting || '').slice(0, 150))}</div>`).join('');
  return `<div style="margin-top:22px;text-align:left"><div class="label" style="margin-bottom:8px">${smp('Best chances right now', 'Top setups now')} · ${t.n_actionable} of ${t.n_symbols} ${smp('markets', 'symbols')}</div>
    ${rows || `<div class="sub">${smp('No market has a good trade right now - the bot is waiting.', 'No watched symbol passes every gate right now.')}</div>`}
    ${near ? `<div class="label" style="margin:12px 0 4px">${smp('Spotted but skipped', 'Signalled, skipped by the bot')}</div>${near}` : ''}
    <div class="sub" style="margin-top:8px">${smp('Pick a market above and press Check for the full plan.', 'Finished candles · costs included · paper only')}</div></div>`;
}

/* Simple mode: one plain sentence for the call, levels in everyday words with € amounts */
function simpleCall(r) {
  const D = r.decision;
  if (D === 'NO TRADE') { const b = r.watch?.bias; return `<div class="plain">Not enough reasons line up to trade right now${b ? ` (it leans slightly towards ${b === 'LONG' ? 'buying' : 'selling'})` : ''}.</div>`; }
  const why = whyText((r.reasons || []).map(x => x.tag), D);
  return `<div class="plain"><b>${D === 'LONG' ? 'Buy' : 'Sell'}</b>${why ? ': ' + esc(why.charAt(0).toLowerCase() + why.slice(1)) : '.'}</div>`;
}
function simpleLevels(r, lv) {
  const ra = r.sizing?.risk_amount;
  return `<div class="lv en"><div class="k">Entry price ${tip(TIPS.entry)}</div><div class="v">${fp(lv.entry)}</div></div>
    <div class="lv sl"><div class="k">Stop loss ${tip(TIPS.stop)}</div><div class="v">${fp(lv.sl)}</div><div class="sub">${ra != null ? 'lose ' + money2(ra) : 'caps the loss'}</div></div>
    <div class="lv tp"><div class="k">Take profit 1 ${tip(TIPS.tp)}</div><div class="v">${fp(lv.tp1)}</div><div class="sub">${ra != null ? 'win ≈ ' + money2(ra * lv.rr1 / 2) + ' on half' : lv.rr1 + '× the risk'}</div></div>
    <div class="lv tp"><div class="k">Take profit 2</div><div class="v">${fp(lv.tp2)}</div><div class="sub">${ra != null ? 'win ≈ ' + money2(ra * (lv.rr1 + lv.rr2) / 2) + ' in total' : lv.rr2 + '× what you risk'}</div></div>`;
}

function szHTML(r) {
  const z = r.sizing; if (!z || !['LONG', 'SHORT'].includes(r.decision)) return '';
  if (z.skip) return `<div class="warn block" style="margin-top:12px">⛔ The bot would skip this: ${esc(z.reason)}</div>`;
  return `<div class="sz"><div class="sz-pct num">${z.risk_pct}%</div><div><div class="k">${smp('Money at risk on this trade', 'Risk per trade (win-rate sizing)')}</div><div class="sub" style="margin:2px 0 0">${esc(z.reason)}</div>${z.risk_amount != null ? `<div class="sub" style="margin:4px 0 0"><b class="hi num">${money2(z.risk_amount)}</b> at risk · size <span class="num">${z.size_text ? esc(z.size_text) : +Number(z.qty).toPrecision(4)}</span>${z.notional != null ? ` · notional <b class="num">${money(z.notional, false)}</b>` : ''}${z.leverage != null ? ` · <b class="num">${levTxt(z.leverage)}</b>` : ''} ${z.quote_ccy && z.quote_ccy !== z.currency ? `· ${esc(z.quote_ccy)}→${esc(z.currency)} ${Number(z.fx_mult).toPrecision(5)}` : ''}</div>` : ''}</div></div>`;
}

function ckTg() { return Object.assign({ imb: true, hvz: true, habs: true }, store.get('ckToggles', {})); }

function wrHTML(w, r) {
  const side = r.decision === 'NO TRADE' ? (r.watch?.bias || 'LONG') : r.decision;
  const head = `<div class="wr-h"><span>Historical win rate</span><span class="sub" style="margin:0">${esc(side.toLowerCase())} setups scoring ${w?.band ? w.band[0] + '-' + w.band[1] : '±10 of ' + r.confluence} · ${esc(r.tf)}</span></div>`;
  if (!w || w.status === 'unavailable') return `<div class="wr">${head}<div class="sub">Backtest unavailable for this instrument.</div></div>`;
  if (w.status === 'computing') return `<div class="wr">${head}<div class="sub"><span class="spin"></span>Replaying the rules over the available history (no lookahead)… ~30 s on first run, then cached 1 h.</div></div>`;
  if (!w.n) return `<div class="wr">${head}<div class="sub">No comparable past setups in this score band.</div></div>`;
  const pc = (x) => x == null ? '-' : Math.round(x) + '%';
  const sg = (x, d = 2) => (x >= 0 ? '+' : '') + Number(x).toFixed(d);
  const wc = w.win_rate >= 50 ? 'g' : w.win_rate >= 40 ? 'a' : 'r';
  return `<div class="wr">${head}
    <div class="wr-grid">
      <div><div class="k">${smp('How often it worked', 'Win rate')}</div><div class="v num ${wc}">${pc(w.win_rate)}</div><div class="sub">${smp('hit take profit 1 before the stop', 'TP1 before SL')}</div></div>
      <div><div class="k">${smp('Went all the way', 'Full TP2')}</div><div class="v num">${pc(w.tp2_rate)}</div><div class="sub">${smp('reached take profit 2', 'ran to target')}</div></div>
      <div><div class="k">Trades (n)</div><div class="v num">${w.n}</div><div class="sub">${w.period_from ? dmy(w.period_from) + ' → ' + dmy(w.period_to) : ''}</div></div>
      ${Mode.simple() ? '' : `<div><div class="k">Avg R</div><div class="v num ${w.avg_r >= 0 ? 'g' : 'r'}">${sg(w.avg_r)}R</div><div class="sub">per trade</div></div>`}
      <div><div class="k">${smp('Average result per trade', 'Expectancy')}</div><div class="v num ${w.expectancy_usd >= 0 ? 'g' : 'r'}">${money(w.expectancy_usd ?? 0)}</div><div class="sub">${smp('when risking ' + money2(w.risk_usd ?? 5), 'per trade at ' + money2(w.risk_usd ?? 5) + ' risk')}</div></div>
    </div>
    ${w.low_sample ? '<div class="warn" style="margin-top:10px">⚠️ Low sample (n &lt; ${App.cfg?.sizing?.low_sample_n ?? 20}) - treat this win rate as anecdotal.</div>' : ''}
    ${w.setup_stats ? `<div class="wr-setup">🎯 <b>${esc(w.setup_stats.setup)}</b> on its own: ${w.setup_stats.n ? `win <b class="num">${Math.round(w.setup_stats.win_rate)}%</b> · n ${w.setup_stats.n} · avg <span class="num">${sg(w.setup_stats.avg_r)}R</span>${w.setup_stats.low_sample ? ' · <span class="a">low sample</span>' : ''}` : 'no past occurrences in this history'}</div>` : ''}
    <div class="sub" style="margin-top:8px">Walk-forward replay of the same rules on ${esc(r.source || 'the feed')} history, paper-broker exits (SL first on ambiguous bars, 50% at TP1 then breakeven, trail, TP2). ${esc(w.note || '')} Past results do not predict future ones.</div></div>`;
}

async function pollWR(r) {
  const side = r.decision === 'NO TRADE' ? (r.watch?.bias || 'LONG') : r.decision;
  for (let k = 0; k < 40; k++) {
    await new Promise(res => setTimeout(res, 4000));
    const box = $('#wrBox'); if (!box || box.dataset.sym && box.dataset.sym !== r.symbol) return;
    const su = (r.setups || []).find(x => x.side === side.toLowerCase());
    const [w] = await load('/api/winrate', Object.assign({ symbol: r.symbol, tf: r.tf, direction: side, score: r.confluence, setup: su ? su.name : '' }, r.levels ? { entry: r.levels.entry, sl: r.levels.sl } : {}));
    if (!$('#wrBox')) return;
    if (w && w.status !== 'computing') { $('#wrBox').innerHTML = wrHTML(w, r); if (w.sizing) { r.sizing = w.sizing; $('#szBox').innerHTML = szHTML(r); } return; }
  }
}

/* ---- session summary card + floating live PnL widget (ATAS / NinjaTrader style) ---- */
function sessionCard(s) {
  if (!s) return '';
  const c = s.net > 0 ? 'glow-g' : s.net < 0 ? 'glow-r' : '';
  return `<div class="panel sess-card"><div class="label">Session summary · today (UTC)</div>
    <div class="sess-net num ${c}">${fmtMoney(s.net, { sign: true })}</div>
    <div class="sub" style="margin-top:2px">Net PnL (closed ${money2(s.closed_pnl)} · open ${money2(s.open_pnl)})</div>
    <div class="sess-grid">
      <div><div class="k">Trades</div><div class="v num">${s.trades}</div></div>
      <div><div class="k">Win rate</div><div class="v num">${s.win_rate == null ? '–' : Math.round(s.win_rate) + '%'}</div></div>
      <div><div class="k">W / L</div><div class="v num"><span class="g">${s.wins}</span> / <span class="r">${s.losses}</span></div></div>
    </div></div>`;
}
const PnlWidget = {
  async refresh() {
    const el = $('#pnlw'); if (!el || el.hidden) return;
    const [s] = await load('/api/session'); if (!s) return;
    const o = $('#pnlwOpen'), c = $('#pnlwClosed');
    if (s.currency) Cur.set(s.currency, s.currency_symbol);
    o.textContent = fmtMoney(s.in_trade ? s.open_pnl : 0, { sign: true });
    o.className = 'num ' + (!s.in_trade ? 'flat' : s.open_pnl > 0 ? 'g' : s.open_pnl < 0 ? 'r' : 'flat');
    c.textContent = fmtMoney(s.closed_pnl, { sign: true });
    c.className = 'num ' + (s.closed_pnl > 0 ? 'g' : s.closed_pnl < 0 ? 'r' : 'flat');
    el.title = s.in_trade ? `${s.open_positions} open paper position(s)` : 'Flat - no open paper positions';
  },
  show(on) { const el = $('#pnlw'); if (!el) return; el.hidden = !on || !store.get('pnlWidget', true); if (!el.hidden) this.refresh(); },
};

/* ================= LIVE CHART ================= */
Views.chart = async (v) => {
  let sym = store.get('chartSym', 'NQ=F'), tf = store.get('chartTf', '15m'); const tg = Object.assign({ fvg: true, ob: true, liq: true, vp: true, sess: true, struct: true, imb: true, hvz: true, habs: true }, store.get('chartToggles', {}));
  const names = { fvg: 'FVG', ob: 'Order blocks', liq: 'Liquidity', vp: 'Volume profile', sess: 'Killzones', struct: 'BOS / CHoCH', imb: 'Imbalance levels', hvz: 'HVN zones', habs: 'Heavy absorption' };
  v.innerHTML = `<div class="page-title">Live chart</div><div class="page-sub" id="chSub">Candles with ICT and estimated order-flow overlays.</div>
    <div class="panel" style="padding:12px">
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between;margin-bottom:10px">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><div class="search" style="height:38px;width:220px">${ICON_SEARCH}<input id="chq" value="${esc(nm(sym))}" list="chl" autocapitalize="off"></div>
          <datalist id="chl">${INSTRUMENTS.map(i => `<option value="${esc(nm(i.symbol))}">${esc(i.name)}</option>`).join('')}</datalist>
          <div class="seg" id="chtf">${['1m', '5m', '15m', '1h', '4h', '1d'].map(t => `<button data-tf="${t}" class="${t === tf ? 'on' : ''}">${t}</button>`).join('')}</div></div>
        <div class="toggles" id="chtg">${Object.keys(names).map(k => `<button class="chip ${tg[k] ? 'on' : ''}" data-k="${k}">${names[k]}</button>`).join('')}</div>
      </div>
      <div class="chart-box tall" id="lc"></div>
      <div id="chTr"></div>
      <div class="legend"><span><i style="background:rgba(${Theme.G},.9)"></i>Buy pressure surge</span><span><i style="background:rgba(${Theme.R},.9)"></i>Sell pressure surge</span><span><i style="background:var(--cyan);border-radius:50%"></i>Absorption</span><span>Bars below: estimated delta</span><span class="est">estimated</span></div>
    </div>`;
  const c = Charts.create($('#lc'));
  const go = async (fit = true) => {
    const [r, err] = await load('/api/chart', { symbol: sym, tf });
    if (!r || !r.ok) { $('#chSub').innerHTML = `<span class="r">${esc(nm(sym))}: data unavailable</span> ${esc(err || r?.detail || '')}`; return; }
    $('#chSub').innerHTML = `${nmH(r.symbol)} · ${esc(r.tf)} · last <b class="num">${fp(r.price)}</b> · ${esc(r.source)} <span style="color:var(--dim)">${esc(r.source_note || '')}</span>`;
    Charts.set(c, r, Object.assign({}, tg, { fit, levels: true }));
    const tr = r.trades || [];
    $('#chTr').innerHTML = tr.length ? `<div class="label" style="margin:12px 0 4px">Bot trades on ${nmH(r.symbol)}</div>` + tr.map(t => `<div class="lt-row"><div><b>${t.status === 'open' ? 'Open' : 'Closed'}</b> ${sidePill(t.side)} <span class="m num" style="font-size:11.5px">@ ${fp(t.entry)}${t.status === 'open' ? ' · SL ' + fp(t.sl) : ' → ' + fp(t.exit_price)} · ${dmy(t.status === 'open' ? t.opened_ts : t.closed_ts)}</span><b class="num right ${pnlClass(t.status === 'open' ? t.unrealized + t.realized : t.pnl_usd)}">${money(t.status === 'open' ? t.unrealized + t.realized : t.pnl_usd)}</b></div>${stakeRow(t.stake, { pnl: true })}</div>`).join('') : '';
  };
  go();
  $('#chq').addEventListener('change', e => { const typed = e.target.value.trim(); sym = (INSTRUMENTS.find(i => nm(i.symbol).toLowerCase() === typed.toLowerCase()) || {}).symbol || typed.toUpperCase(); e.target.value = nm(sym); store.set('chartSym', sym); go(); });
  $('#chtf').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; tf = b.dataset.tf; store.set('chartTf', tf); $$('#chtf button').forEach(x => x.classList.toggle('on', x === b)); go(); });
  $('#chtg').addEventListener('click', e => { const b = e.target.closest('.chip'); if (!b) return; tg[b.dataset.k] = !tg[b.dataset.k]; b.classList.toggle('on'); store.set('chartToggles', tg); c.opts[b.dataset.k] = tg[b.dataset.k]; c.redraw(); });
  App.timer(() => go(false), 60000);
};

/* ================= SIGNALS ================= */
Views.signals = async (v) => {
  v.innerHTML = `<div class="page-title">Signals</div><div class="page-sub">Every call the scanner made on the watchlist, taken or blocked.</div><div class="panel" id="sg"><div class="skeleton" style="height:300px"></div></div>`;
  const [r, err] = await load('/api/signals'); if (!r) { $('#sg').innerHTML = unavailable('Signals', err); return; }
  $('#sg').innerHTML = `<div class="rows"><div class="row head"><div>Symbol</div><div>Call</div><div>Confluence</div><div class="r-right">Levels</div><div class="r-right">Score · win rate</div></div>${r.signals.map(s => `
    <div class="row"><div><div class="sym">${nmH(s.symbol)}</div><div class="sub" style="margin:2px 0 0">${dmy(s.ts)} ${hm(s.ts)} · ${esc(s.tf)}</div></div><div>${sidePill(s.decision)}</div>
    <div class="tags">${tagsH(s.tags, s.setup, s.decision)}</div>
    <div class="r-right num mono" style="font-size:12px">${fp(s.price)}<div class="sub" style="margin:2px 0 0">SL ${fp(s.sl)} · TP ${fp(s.tp2)}</div></div>
    <div class="r-right"><b class="num" title="Confluence score (not a probability)">${Math.round(s.confluence ?? s.confidence ?? 0)}<span class="m" style="font-size:11px">/100</span></b>${s.win_rate != null ? `<div class="sub" style="margin:2px 0 0" title="Backtest win rate (TP1 before SL), n trades">win ${Math.round(s.win_rate)}% · n${s.bt_n}${s.bt_n < 20 ? ' <span class="a">low</span>' : ''}</div>` : ''}${s.risk_pct != null ? `<div class="sub" style="margin:2px 0 0" title="${esc(s.risk_reason || '')}">risk <b class="num">${+s.risk_pct.toFixed(1)}%</b></div>` : ''}<div class="sub" style="margin:2px 0 0">${s.acted ? '<span class="g">entered</span>' : '<span class="a">' + esc(deTicker(s.note || 'skipped')) + '</span>'}</div></div></div>${s.stake ? `<div class="row-note">${stakeRow(s.stake, { pnl: true })}</div>` : ''}`).join('') || '<div class="unavail">No signals yet - the scanner journals each one here.</div>'}</div>`;
};

/* ================= POSITIONS ================= */
Views.positions = async (v) => {
  v.innerHTML = `<div class="page-title">Positions</div><div class="page-sub">Open paper positions and what went into each. Manage from Telegram with <span class="mono">/close SYMBOL</span>, <span class="mono">/pause</span>.</div><div class="panel" id="ps"><div class="skeleton" style="height:200px"></div></div><div class="panel" id="pc" style="margin-top:14px"></div>`;
  const draw = async () => {
    const [r, err] = await load('/api/positions'); if (!r) { $('#ps').innerHTML = unavailable('Positions', err); $('#pc').innerHTML = ''; return; }
    const tot = r.positions.reduce((a, p) => a + p.unrealized, 0);
    const inRisk = r.positions.reduce((a, p) => a + (p.stake?.risk_eur || 0), 0), inNot = r.positions.reduce((a, p) => a + (p.stake?.notional_eur || 0), 0);
    $('#ps').innerHTML = `<h3>Open · ${r.positions.length} <span class="right num ${pnlClass(tot)}" style="font-weight:800">${money(tot)} ${smp('so far', 'unrealized')}</span></h3>` +
      (r.positions.length ? `<div class="sub" style="margin:-4px 0 6px">In the market: ${smp('money at risk', 'risk')} <b class="num hi">${money2(inRisk)}</b> · ${smp('trade size (with leverage)', 'notional')} <b class="num">${money(inNot, false)}</b></div>` : '') + (r.positions.map(p => `
    <div class="pos"><div><b style="font-size:15px">${nmH(p.symbol)}</b> ${sidePill(p.side)} ${p.tp1_hit ? `<span class="tag">${smp('First target hit · stop moved to entry', 'TP1 hit · SL at BE')}</span>` : ''}<div class="sub">${esc(p.tf)} · opened ${ago(p.opened_ts)}${Mode.simple() ? '' : ' · ' + (p.tags || []).map(t => esc(t)).join(' · ')}</div>${Mode.simple() ? whyH(p.tags, p.side) : ''}</div>
      <div><span class="k">${smp('Entry price', 'Entry')}</span><span class="num mono">${fp(p.entry)}</span></div><div><span class="k">${smp('Price now', 'Last')}</span><span class="num mono">${fp(p.last_price)}</span></div>
      <div><span class="k">${smp('Stop loss ' + tip(TIPS.stop), 'Stop')}</span><span class="num mono r">${fp(p.sl)}</span></div><div><span class="k">${smp('Take profit ' + tip(TIPS.tp), 'Targets')}</span><span class="num mono g">${fp(p.tp1)} / ${fp(p.tp2)}</span></div>
      <div style="text-align:right"><span class="k">${smp('Profit / loss', 'P&amp;L')}</span><b class="num ${pnlClass(p.unrealized + p.realized)}" style="font-size:17px">${money(p.unrealized + p.realized)}</b>${p.stake?.pnl_pct_of_risk != null ? `<div class="sub num" style="margin:2px 0 0">${p.stake.pnl_pct_of_risk > 0 ? '+' : ''}${+p.stake.pnl_pct_of_risk}% of risk</div>` : ''}</div>
      <div class="pos-stake">${stakeRow(p.stake)}</div></div>`).join('') || '<div class="empty" style="min-height:160px"><div><div class="big-ic">◌</div>Flat. The bot enters only when confluence passes.</div></div>');
    const cl = r.closed || [];
    $('#pc').innerHTML = `<h3>Recently closed · ${cl.length}</h3>` + (cl.map(t => `
    <div class="pos closed"><div><b style="font-size:15px">${nmH(t.symbol)}</b> ${sidePill(t.side)}<div class="sub">${esc(t.tf || '')} · ${esc(t.exit_reason || 'closed')} · ${dmy(t.closed_ts)} ${hm(t.closed_ts)}</div></div>
      <div><span class="k">Entry</span><span class="num mono">${fp(t.entry)}</span></div><div><span class="k">${smp('Exit price', 'Exit')}</span><span class="num mono">${fp(t.exit_price)}</span></div>
      <div><span class="k">${smp('Money risked', 'R')}</span><span class="num">${Mode.simple() ? money2(t.stake?.risk_eur ?? t.risk_usd) : t.r_multiple != null ? (t.r_multiple >= 0 ? '+' : '') + Number(t.r_multiple).toFixed(2) + 'R' : '–'}</span></div><div><span class="k">% of risk</span><span class="num ${pnlClass(t.stake?.pnl_pct_of_risk)}">${t.stake?.pnl_pct_of_risk != null ? (t.stake.pnl_pct_of_risk > 0 ? '+' : '') + t.stake.pnl_pct_of_risk + '%' : '–'}</span></div>
      <div style="text-align:right"><span class="k">${smp('Profit / loss', 'P&amp;L')}</span><b class="num ${pnlClass(t.pnl_usd)}" style="font-size:17px">${money(t.pnl_usd)}</b></div>
      <div class="pos-stake">${stakeRow(t.stake)}</div></div>`).join('') || '<div class="unavail">No closed trades yet.</div>');
  };
  draw(); App.timer(draw, 30000);
};


/* ================= NEWS & CALENDAR ================= */
Views.news = async (v) => {
  v.innerHTML = `<div class="page-title">News &amp; Calendar</div><div class="page-sub">Events and headlines mapped to the instruments they move. The bot stands aside around high-impact releases.</div>
  <div class="grid cols-2"><div class="panel" id="cal"><h3>Economic calendar · this week</h3><div class="skeleton" style="height:300px"></div></div><div class="panel" id="nw"><h3>Headlines</h3><div class="skeleton" style="height:300px"></div></div></div>`;
  let imp = store.get('impFilter', 'High');
  const drawCal = async () => {
    const [c, err] = await load('/api/calendar');
    if (!c || !c.ok) { $('#cal').innerHTML = '<h3>Economic calendar</h3>' + unavailable('Calendar', err || c?.error); return; }
    const evs = c.events.filter(e => e.ts > Date.now() / 1000 - 86400).filter(e => imp === 'All' || e.impact === imp || (imp === 'Medium' && e.impact === 'High'));
    let html = `<h3>Economic calendar · this week <span class="right">${esc(c.source)}${c.stale ? ' · cached' : ''}</span></h3><div class="filters">${['High', 'Medium', 'All'].map(x => `<button class="chip ${x === imp ? 'on' : ''}" data-i="${x}">${x === 'Medium' ? 'Medium+' : x}</button>`).join('')}</div>`;
    let day = ''; const now = Date.now() / 1000;
    evs.forEach(e => { const dd = new Date(e.ts * 1000).toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' }); if (dd !== day) { day = dd; html += `<div class="day-h">${dd}</div>`; }
      html += `<div class="ev ${e.ts < now ? 'past' : ''}"><span class="num m">${hm(e.ts)}<br><span style="font-size:10.5px">${inTime(e.ts)}</span></span><span class="ccy">${esc(e.ccy)}</span><span><i class="imp ${esc(e.impact)}"></i>${esc(e.title)}</span><span class="m num" style="font-size:11.5px;text-align:right">${e.forecast ? 'f ' + esc(e.forecast) : ''}<br>${e.previous ? 'p ' + esc(e.previous) : ''}</span></div>`; });
    $('#cal').innerHTML = html + (evs.length ? '' : '<div class="unavail">No events</div>');
    $$('#cal .chip').forEach(b => b.onclick = () => { imp = b.dataset.i; store.set('impFilter', imp); drawCal(); });
  };
  const drawNews = async () => {
    const [n, err] = await load('/api/news');
    if (!n || !n.items?.length) { $('#nw').innerHTML = '<h3>Headlines</h3>' + unavailable('News', err || n?.error); return; }
    $('#nw').innerHTML = `<h3>Headlines <span class="right">${n.stale ? 'cached · ' : ''}${n.items.length} items</span></h3>` + n.items.slice(0, 40).map(i => `
      <a class="news-item" href="${esc(i.link)}" target="_blank" rel="noopener"><div class="t">${i.tone === 'up' ? '<span class="g">▲</span> ' : i.tone === 'down' ? '<span class="r">▼</span> ' : ''}${esc(i.title)}</div>
      <div class="meta"><span>${esc(i.source)}</span><span>·</span><span>${ago(i.ts)}</span>${(i.symbols || []).slice(0, 4).map(s => `<span class="tag mk">${nmH(s)}</span>`).join('')}</div>${i.why ? `<div class="news-why">${smp('Why it matters: ', '')}${esc(i.why)}</div>` : ''}</a>`).join('') + '<div class="sub" style="margin-top:10px">▲▼ = simple keyword tone, not a sentiment model.</div>';
  };
  drawCal(); drawNews();
};

/* ================= JOURNAL ================= */
Views.journal = async (v) => {
  v.innerHTML = `<div class="page-title">Journal</div><div class="page-sub">Every paper trade with the reasons it was taken.</div><div class="panel" id="jr"><div class="skeleton" style="height:300px"></div></div>`;
  const [r, err] = await load('/api/journal'); if (!r) { $('#jr').innerHTML = unavailable('Journal', err); return; }
  let side = 'All', res = 'All', sym = 'All';
  const syms = ['All', ...new Set(r.trades.map(t => t.symbol))];
  const draw = () => {
    const ts = r.trades.filter(t => (side === 'All' || t.side === side) && (sym === 'All' || t.symbol === sym) && (res === 'All' || (res === 'Wins' ? t.pnl_usd > 0 : res === 'Losses' ? t.pnl_usd < 0 : t.status === 'open')));
    const tot = ts.reduce((a, t) => a + (t.pnl_usd || 0), 0);
    $('#jr').innerHTML = `<div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:6px">
      <div class="filters" style="margin:0">${['All', 'LONG', 'SHORT'].map(x => `<button class="chip ${x === side ? 'on' : ''}" data-f="side" data-v="${x}">${x === 'All' ? 'All sides' : esc(smp(sideWord(x) + 's', x))}</button>`).join('')}
        ${['All', 'Wins', 'Losses', 'Open'].map(x => `<button class="chip ${x === res ? 'on' : ''}" data-f="res" data-v="${x}">${x === 'All' ? 'All results' : x}</button>`).join('')}
        <select class="chip" id="jsym">${syms.map(s => `<option value="${esc(s)}" ${s === sym ? 'selected' : ''}>${esc(s === 'All' ? 'All markets' : nm(s))}</option>`).join('')}</select></div>
      <div class="num ${pnlClass(tot)}" style="font-weight:800">${ts.length} trades · ${money(tot)}</div></div>
      <div class="rows"><div class="row head"><div>Symbol</div><div>Side</div><div>Confluence</div><div class="r-right">Time</div><div class="r-right">P&amp;L</div></div>
      ${ts.map(t => `<div class="row" title="${esc((t.reasons || []).join('\n'))}"><div><div class="sym">${nmH(t.symbol)}</div><div class="sub" style="margin:2px 0 0">${esc(t.exit_reason || t.status)}</div></div><div>${sidePill(t.side)}</div>
        <div class="tags">${tagsH(t.tags, t.setup, t.side)}</div>
        <div class="r-right m num" style="font-size:12px">${dmy(t.opened_ts)}<div>${hm(t.opened_ts)}</div></div>
        <div class="r-right"><b class="num ${pnlClass(t.pnl_usd)}">${money(t.pnl_usd)}</b><div class="sub num" style="margin:2px 0 0">${Mode.simple() ? (t.status === 'open' ? 'still open' : 'risked ' + money2(t.risk_usd)) : t.r_multiple != null ? (t.r_multiple >= 0 ? '+' : '') + Number(t.r_multiple).toFixed(2) + 'R' : 'open'}</div>${t.risk_pct != null ? `<div class="sub" style="margin:2px 0 0" title="${esc(t.risk_reason || '')}">risk ${+Number(t.risk_pct).toFixed(1)}%</div>` : ''}</div></div>
        ${t.stake || t.risk_reason ? `<div class="row-note">${stakeRow(t.stake, { pnl: t.status === 'closed' })}${t.risk_reason ? `<div>💰 ${esc(deTicker(t.risk_reason))}</div>` : ''}</div>` : ''}`).join('') || '<div class="unavail">No trades yet.</div>'}</div>`;
    $$('#jr .chip[data-f]').forEach(b => b.onclick = () => { if (b.dataset.f === 'side') side = b.dataset.v; else res = b.dataset.v; draw(); });
    $('#jsym').onchange = e => { sym = e.target.value; draw(); };
  };
  draw();
};

/* ================= PERFORMANCE ================= */
Views.performance = async (v) => {
  v.innerHTML = `<div class="page-title">Performance</div><div class="page-sub">Paper account since start. Deposits are not counted as profit.</div><div id="pf"><div class="skeleton" style="height:520px"></div></div>`;
  const [p, err] = await load('/api/performance'); if (!p) { $('#pf').innerHTML = `<div class="panel">${unavailable('Performance', err)}</div>`; return; }
  const pf = p.profit_factor; const good = pf != null && pf >= 1;
  const ret = p.start_balance ? (p.net / p.start_balance * 100) : 0;
  let series = p.equity_curve?.length ? p.equity_curve : (p.equity_snapshots?.length >= 2 ? p.equity_snapshots : []);
  const flat = !series.length; const nowS = Math.floor(Date.now() / 1000);
  if (flat) series = [{ time: nowS - 7 * 86400, value: p.balance ?? p.start_balance }, { time: nowS, value: p.balance ?? p.start_balance }];
  $('#pf').innerHTML = `
    <div class="grid cols-4">
      <div class="panel stat"><div class="label">Net return</div><div class="v num ${p.net > 0 ? 'glow-g' : p.net < 0 ? 'glow-r' : ''}">${money(p.net)}</div><div class="sub">${ret >= 0 ? '+' : ''}${ret.toFixed(2)}%${Mode.simple() ? '' : ` · avg ${p.avg_r >= 0 ? '+' : ''}${p.avg_r}R`}</div></div>
      <div class="panel stat"><div class="label">Win rate</div><div style="display:flex;align-items:center;gap:12px"><div class="v num">${p.win_rate}%</div><div class="gauge" style="width:84px;height:48px">${FX.gauge(p.win_rate, p.win_rate >= 50 ? Theme.g : Theme.r).replace('<svg ', '<svg style="width:84px;height:48px" ')}</div></div><div class="sub">${p.wins}W · ${p.losses}L of ${p.trades}</div></div>
      <div class="panel stat"><div class="label">${smp('Won per €1 lost ' + tip('Profit factor: money won divided by money lost. Above 1 means the wins outweigh the losses.'), 'Profit factor')}</div><div class="v num">${pf ?? '–'}</div><div>${p.trades ? (good ? `<span class="badge-ok">${smp('Profitable', 'PROFITABLE')}</span>` : `<span class="badge-bad">${smp('Below 1.0', 'BELOW 1.0')}</span>`) : ''} <span class="sub">Max drawdown ${money2(p.max_drawdown)}</span></div></div>
      <div class="panel stat"><div class="label">Average trade</div><div class="v num"><span class="g">${money(p.avg_win)}</span> <span class="m" style="font-size:16px">/</span> <span class="r">${money(p.avg_loss)}</span></div><div class="sub">avg win / avg loss</div></div>
    </div>
    <div class="panel" style="margin-top:16px"><h3>Deposits <span class="right num">${money2(p.deposited || 0)}</span></h3>
      <div class="sub" style="margin:0 0 10px">Top-ups and withdrawals are cash movements, not P&amp;L. Net return above is trades only.</div>
      ${topupBar()}
      ${(p.deposits || []).length ? `<div class="rows" style="margin-top:10px">${p.deposits.slice().reverse().slice(0, 8).map(x => `<div class="ev" style="grid-template-columns:90px 1fr 90px"><span class="m num">${dmy(x.ts)} ${hm(x.ts)}</span><span>${x.kind === 'withdraw' ? 'Withdrawal' : 'Top-up'}</span><b class="num ${x.amount >= 0 ? 'g' : 'r'}" style="text-align:right">${money2(x.amount)}</b></div>`).join('')}</div>` : ''}</div>
    <div class="panel perf-hero" style="margin-top:16px"><canvas id="eqc"></canvas>
      <div class="ph-top"><div><div class="label" style="margin:0 0 6px">Equity curve</div><div class="gap-line">${p.reset ? `<span class="a">Fresh start: reset to ${money2(p.reset.balance)} on ${new Date(p.reset.ts * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}</span> (was ${money2(p.reset.from_balance)}) · win rate &amp; stats keep all ${p.all_time?.trades ?? p.trades} trades · ` : ''}${flat ? '<span class="a">No closed paper trades yet</span> · line shows realized balance · ' : ''}<b>${money(p.net)}</b> over the period · max drawdown <span class="r">${money2(p.max_drawdown)}</span> (${p.max_drawdown_pct}%)</div></div>
      <div class="legend" style="margin:0"><span><i style="background:var(--green)"></i>Equity</span><span><i style="background:transparent;border-top:2px dashed #6E8BFF;height:0"></i>Start balance</span></div></div></div>
    <div class="grid cols-2" style="margin-top:16px">
      <div class="panel"><h3>By instrument</h3><div class="rows">${Object.entries(p.by_symbol || {}).sort((a, b) => b[1].pnl - a[1].pnl).map(([s, b]) => `<div class="ev" style="grid-template-columns:1fr 70px 70px 90px"><b>${nmH(s)}</b><span class="m num">${b.n} trades</span><span class="m num">${b.win_rate}%</span><b class="num ${pnlClass(b.pnl)}" style="text-align:right">${money(b.pnl)}</b></div>`).join('') || '<div class="unavail">No trades yet</div>'}</div></div>
      ${Mode.simple() ? '' : `<div class="panel"><h3>Hour by weekday <span class="right">UTC</span></h3>${heatmap(p.heatmap)}</div>`}
    </div>${Mode.simple() ? fold('Hour by weekday (UTC)', heatmap(p.heatmap)) : ''}`;
  FX.equity($('#eqc'), series, { base: p.start_balance, empty: 'No closed paper trades yet - the curve fills as the bot trades.' });
  bindTopup();
};

/* ================= LEARNING ================= */
const fmtR = v => v == null ? '–' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) + 'R';
const wrTxt = v => v == null ? '–' : Math.round(v) + '%';
function newsTestH(n) {
  if (!n || !n.modes) return '';
  const seg = (lab, x) => `<div class="lr-c"><div class="k">${lab}</div><b class="${pnlClass(x?.exp_r)}">${fmtR(x?.exp_r)}</b><div class="sub">${wrTxt(x?.win_rate)} win · n ${x?.n ?? 0}${x?.t != null ? ' · t ' + x.t : ''}</div></div>`;
  const nm = { follow: 'Follow the surprise', fade: 'Fade the spike' };
  const ds = { follow: 'Enter in the direction the actual-vs-forecast surprise implies, a few minutes after the release.', fade: 'Enter against a large release spike, aiming back at the pre-release price.' };
  const P = p => p ? `${p.delay} min after · hold ≤ ${p.hold} min${p.mode === 'follow' ? ` · surprise ≥ ${p.zmin}σ${p.wide ? ' · wide stop' : ''}` : ` · spike ≥ ${p.spike}× normal range`}` : '';
  const rows = Object.entries(n.modes).map(([k, m]) => `<div class="lr-row"><div class="lr-n"><b>${esc(nm[k] || k)}</b> ${m.passed ? '<span class="badge-ok">PASSED</span>' : '<span class="badge-bad">OFF · failed</span>'}<div class="sub">${esc(ds[k] || '')}<br>Best on learn data: ${esc(P(m.params))}. ${m.learn_configs_positive ?? 0}/${m.learn_configs_eligible ?? 0} settings profitable after costs on learn data${m.test_configs_positive != null ? `, ${m.test_configs_positive}/${m.grid_size} on test` : ''}.${m.gross_no_costs ? ` Before costs, test ${fmtR(m.gross_no_costs.test?.exp_r)}.` : ''}</div></div>
      ${seg('Learn', m.learn)}${seg('Validation', m.validate)}${seg('Test', m.test)}</div>`).join('');
  const re = n.reaction || {}; const rr = Object.entries(re).map(([s, x]) => `<span class="tag">${esc(s)} ${x.right_first_minute_pct}% → ${x.right_2_to_32min_pct}%</span>`).join('');
  const seg2 = n.segments || {};
  return `<div class="panel" style="margin-top:16px"><h3>News trading test <span class="right">${Object.values(n.modes).some(m => m.passed) ? 'passed' : 'not enabled'}</span></h3>
    <div class="sub" style="margin-bottom:6px">${(n.events?.learn ?? 0) + (n.events?.validate ?? 0) + (n.events?.test ?? 0)} US high-impact releases with actual vs forecast (learn ${esc((seg2.learn || [])[0] || '')}…, validation ${esc((seg2.validate || [])[0] || '')}…, test ${esc((seg2.test || [])[0] || '')} to ${esc((seg2.test || [])[1] || '')}) on 1-minute EURUSD, GBPUSD, USDJPY, gold, S&amp;P 500 and Nasdaq. Costs: spread widened up to 6× at the release plus slippage; stops that gap fill at the next price. Results in R (1R = amount risked).</div>
    <div class="rows">${rows}</div>
    <div class="sub" style="margin-top:8px">Surprise direction right in the first minute → 2–32 min after: ${rr}</div>
    <div class="sub" style="margin-top:6px">The reaction is real but almost all of it happens in the first minute, before a retail order can get in at a normal spread; from minute 2 on it is close to a coin flip. ${Object.values(n.modes).some(m => m.passed) ? 'A variant passed validation and test after costs; it still starts small and switches itself off if live paper results degrade.' : 'Neither variant made money after costs on data it was not tuned on, so news trading stays off and the news blackout stays on.'} Sources: Forex Factory calendar history (community snapshot, to 7 Apr 2025), HistData.com 1-minute bars. Past results do not guarantee future results.</div></div>`;
}
function regimeH(r, names) {
  const rg = r.regime; if (!rg || !rg.strategies) return '';
  const stale = Date.now() / 1000 - (rg.computed || 0) > 3 * 86400;
  const st = rg.strategies; const lt = r.strategies || {};
  const eff = k => { const e = st[k]; if (stale) return lt[k]?.enabled ? 'on' : 'off'; return e.state; };
  const rank = { paused: 1, on: 0, off: 2 };
  const ks = Object.keys(st).sort((a, b) => (rank[eff(a)] - rank[eff(b)]) || ((st[b].check?.exp_r ?? -9) - (st[a].check?.exp_r ?? -9)));
  const f = x => x && x.n ? `${wrTxt(x.win_rate)} win · ${fmtR(x.exp_r)} · n ${x.n}` : 'no trades';
  const badge = s => s === 'on' ? '<span class="badge-ok">TRADING</span>' : s === 'paused' ? '<span class="badge-bad">PAUSED</span>' : '<span class="m">off</span>';
  const onN = ks.filter(k => eff(k) === 'on').length;
  const days = (rg.check_days || []).length, pdays = (rg.pick_days || []).length;
  return `<div class="panel" style="margin-top:16px"><h3>${smp('Trading right now', 'Right now (market regime)')} <span class="right">${onN} on · checked ${dmy(rg.computed)} ${hm(rg.computed)}</span></h3>
    <div class="sub" style="margin-bottom:6px">${stale ? '<span class="a">This check is more than 3 days old, so the long-term settings apply until the next nightly run.</span> ' : ''}${smp(`Judged on the newest market days only: a strategy has to make money in the ${pdays} days before and again in the last ${days} trading days, after costs. Small samples - re-checked every night.`, `Recent walk-forward on ${rg.timeframe}: pick on ${pdays} trading days (${(rg.pick_days || [])[0] || ''}…), confirm out-of-sample on the newest ${days} (${(rg.check_days || [])[0] || ''}…), ${esc(rg.costs || '')}; trend = ${esc(rg.trend || '')}. Off strategies need ≥ ${rg.limits?.min_check_n} recent trades and > ${fmtR(rg.limits?.min_check_exp)}; live ones pause when both windows lose (≥ ${rg.limits?.pause_min_n} trades each).`)}</div>
    <div class="rows">${ks.map(k => { const e = st[k]; const s = eff(k); const sc = (e.scopes || [])[0];
      return `<div class="lr-row"><div class="lr-n"><b>${esc(names[k] || e.name || k)}</b> ${badge(s)}<div class="sub">${esc(deTicker(e.reason || ''))}</div></div>
      <div class="lr-c"><div class="k">${smp('Last ' + days + ' days', 'Check (OOS)')}</div><b class="${pnlClass((sc ? sc.check : e.check)?.exp_r)}">${fmtR((sc ? sc.check : e.check)?.exp_r)}</b><div class="sub">${f(sc ? sc.check : e.check)}</div></div>
      <div class="lr-c"><div class="k">${smp(pdays + ' days before', 'Pick window')}</div><b class="${pnlClass((sc ? sc.pick : e.pick)?.exp_r)}">${fmtR((sc ? sc.pick : e.pick)?.exp_r)}</b><div class="sub">${f(sc ? sc.pick : e.pick)}</div></div></div>`; }).join('')}</div></div>`;
}

Views.learning = async (v) => {
  v.innerHTML = `<div class="page-title">Learning</div><div class="page-sub">The bot studies every backtest and paper trade, blocks what keeps losing and only trades strategies that showed an edge on data they were not tuned on.</div><div id="lrn"><div class="skeleton" style="height:520px"></div></div>`;
  const [d, err] = await load('/api/learning'); if (!d) { $('#lrn').innerHTML = `<div class="panel">${unavailable('Learning', err)}</div>`; return; }
  if (d.currency) Cur.set(d.currency, d.currency_symbol);
  const r = d.rules || {}; const st = r.strategies || {}; const names = d.names || {}; const desc = d.descriptions || {};
  const eur = d.eur_per_r; const e = x => (x == null || eur == null) ? '' : `<div class="sub">≈ ${money(x * eur)} / trade</div>`;
  const sm = r.summary || {}; const b = sm.before || {}, a = sm.after || {};
  const running = d.status?.state === 'running';
  const cmp = (lab, x, y, f, better) => { const up = x != null && y != null && (better ? y > x : y < x); return `<div><div class="k">${lab}</div><div class="v ${y == null || x == null ? '' : y > x ? 'g' : y < x ? 'r' : ''}">${f(y)}</div><div class="sub">before ${f(x)}</div></div>`; };
  const days = sm.test_from && sm.period ? Math.max(1, Math.round((sm.period[1] - sm.test_from) / 86400)) : null;
  const order = Object.keys(st).sort((p, q) => (st[q].enabled - st[p].enabled) || ((st[q].stats?.val?.exp_r ?? -9) - (st[p].stats?.val?.exp_r ?? -9)));
  const sRow = k => { const x = st[k], vv = x.stats?.val || {}, tt = x.stats?.test || {}, lv = r.live?.strategies?.[k];
    return `<div class="lr-row"><div class="lr-n"><b>${esc(names[k] || k)}</b> ${x.enabled ? '<span class="badge-ok">ON</span>' : '<span class="badge-bad">OFF</span>'}<div class="sub">${esc(desc[k] || (k === 'core' ? 'The main confluence score (structure, liquidity, order-flow estimate, killzone).' : ''))}</div><div class="sub">${esc(x.reason || '')}</div></div>
      <div class="lr-c"><div class="k">Validation</div><b class="${pnlClass(vv.exp_r)}">${fmtR(vv.exp_r)}</b>${e(vv.exp_r)}<div class="sub">${wrTxt(vv.win_rate)} win · n ${vv.n ?? 0}</div></div>
      <div class="lr-c"><div class="k">Test</div><b class="${pnlClass(tt.exp_r)}">${fmtR(tt.exp_r)}</b>${e(tt.exp_r)}<div class="sub">${wrTxt(tt.win_rate)} win · n ${tt.n ?? 0}</div></div>
      <div class="lr-c"><div class="k">Live paper</div>${lv ? `<b class="${pnlClass(lv.pnl)}">${money(lv.pnl)}</b><div class="sub">${wrTxt(lv.win_rate)} win · n ${lv.n}</div>` : '<span class="m">no trades</span>'}</div></div>`; };
  const ch = (r.changes || []);
  const blocks = r.blocks || [];
  const syms = Object.keys(r.symbols || {}).sort();
  const selSym = store.get('lrnSym', syms[0]);
  const rankH = s => { const x = (r.symbols || {})[s]; if (!x) return '<div class="unavail">No data</div>';
    return x.ranking.map((z, i) => { const blk = (x.blocked || []).includes(z.strategy); return `<div class="ev lr-rank"><span class="m num">#${i + 1}</span><b>${esc(z.name)}</b><span class="num ${pnlClass(z.exp_r)}">${fmtR(z.exp_r)}</span><span class="m num">n ${z.n}</span><span>${!z.enabled ? '<span class="m">off</span>' : blk ? '<span class="r">blocked here</span>' : (z.exp_r ?? 0) > 0 ? '<span class="g">trades</span>' : '<span class="m">trades*</span>'}</span></div>`; }).join(''); };
  $('#lrn').innerHTML = `
    <div class="panel"><div class="lr-top"><div><div class="label" style="margin:0">Rules version ${r.version ?? 0}${r.created ? ' · ' + dmy(r.created) + ' ' + hm(r.created) : ''}</div>
      <div class="sub">${esc(r.note || '')}${d.status?.state ? ' · last run: ' + esc(d.status.state) + (d.status.step ? ' (' + esc(d.status.step) + ')' : '') : ''}. Runs every night automatically.</div></div>
      ${API.demo ? '' : `<button class="btn pri" id="lrnRun" ${running || d.requested ? 'disabled' : ''}>${running ? 'Learning…' : d.requested ? 'Queued…' : 'Learn now'}</button>`}</div></div>
${regimeH(r, names)}
    <div class="panel" style="margin-top:16px"><div class="wr-h"><span>Before vs after learning</span><span class="sub" style="font-weight:400">${days ? `newest ~${days} days, never used to make any decision` : 'not learned yet'}</span></div>
      <div class="wr-grid">${cmp('Win rate', b.win_rate, a.win_rate, wrTxt, true)}${cmp('Avg per trade', b.exp_r, a.exp_r, fmtR, true)}
        <div><div class="k">≈ per trade</div><div class="v ${pnlClass(a.exp_r)}">${eur != null && a.exp_r != null ? money(a.exp_r * eur) : '–'}</div><div class="sub">before ${eur != null && b.exp_r != null ? money(b.exp_r * eur) : '–'}</div></div>
        <div><div class="k">Trades</div><div class="v">${a.n ?? '–'}</div><div class="sub">before ${b.n ?? '–'}</div></div>
        <div><div class="k">Total</div><div class="v ${pnlClass(a.total_r)}">${fmtR(a.total_r)}</div><div class="sub">before ${fmtR(b.total_r)}</div></div></div>
      <div class="sub" style="margin-top:8px">Data is split by time: oldest half to learn, next quarter to accept or reject each change, newest quarter (above) only to check it. 1R = the amount risked on a trade${eur != null ? ` (≈ ${money2(eur)} at the base risk of ${d.base_risk_pct}% of the balance)` : ''}. Win rate only counts trades that ended in profit. Past results do not guarantee future ones.</div></div>
    <div class="panel" style="margin-top:16px"><h3>Strategies <span class="right">${order.filter(k => st[k].enabled).length} on · ${order.filter(k => !st[k].enabled).length} off</span></h3>
      <div class="sub" style="margin-bottom:6px">A strategy is switched on only if it made money in the validation period with enough trades, and switched off when it clearly loses. Numbers are after the learned blocks.</div>
      <div class="rows">${order.map(sRow).join('') || '<div class="unavail">Nothing learned yet</div>'}</div></div>
${newsTestH(d.news)}
    <div class="grid cols-2" style="margin-top:16px">
      <div class="panel"><h3>Blocked combinations <span class="right">${blocks.length}</span></h3><div class="sub">Situations that lost in the learning data and kept losing in the validation data. The bot skips them.</div>
        <div class="rows">${blocks.map(x => `<div class="lr-b"><span class="r">⛔</span><div>${esc(deTicker(x.text))}</div></div>`).join('') || '<div class="unavail">No blocks</div>'}</div></div>
      <div class="panel"><h3>Changes in this version <span class="right">${ch.length}</span></h3><div class="sub">At most one setting step per strategy and a few new blocks per night, so one bad night cannot swing everything.</div>
        <div class="rows">${ch.map(x => `<div class="lr-b"><span>${{ param: '🔧', block: '⛔', unblock: '✅', enable: '🟢', disable: '🔴', rollback: '↩️' }[x.kind] || '•'}</span><div>${esc(x.text)}${x.kind === 'param' ? `<div class="sub">validation win ${wrTxt(x.val_before?.win_rate)} → ${wrTxt(x.val_after?.win_rate)}${eur != null ? ` · per trade ${money(x.val_before?.exp_r * eur)} → ${money(x.val_after?.exp_r * eur)}` : ''}</div>` : ''}</div></div>`).join('') || '<div class="unavail">No change passed validation</div>'}</div></div>
    </div>
    <div class="grid cols-2" style="margin-top:16px">
      <div class="panel"><h3>Best strategies per instrument</h3><select id="lrnSym" class="lr-sel">${syms.map(s => `<option value="${esc(s)}" ${s === selSym ? 'selected' : ''}>${esc(nm(s))}</option>`).join('')}</select><div class="rows" id="lrnRank">${rankH(syms.includes(selSym) ? selSym : syms[0])}</div><div class="sub" style="margin-top:6px">Ranked by average result per trade on that instrument (learning + validation data). A strategy that loses on an instrument is blocked there.</div></div>
      <div class="panel"><h3>Where live paper losses came from</h3><div class="sub">From ${r.live?.n ?? 0} closed paper trades (small sample: shown for insight, decisions use the larger backtest).</div>
        <div class="rows">${(r.live?.loss_buckets || []).map(x => `<div class="ev" style="grid-template-columns:1fr 70px 80px"><span>${esc(x.label)}</span><span class="m num">${x.n} trades · ${wrTxt(x.win_rate)}</span><b class="num r" style="text-align:right">${money(x.pnl)}</b></div>`).join('') || '<div class="unavail">No losing pattern yet</div>'}</div></div>
    </div>
    <div class="panel" style="margin-top:16px"><h3>History</h3><div class="sub">Every version is kept. Roll back if a new version behaves worse.</div>
      <div class="rows">${(d.history || []).map(x => `<div class="ev" style="grid-template-columns:60px 1fr 90px 92px"><b>v${x.version}</b><span class="m">${dmy(x.created)} ${hm(x.created)} · ${esc(x.note)}</span><span class="num ${pnlClass(x.after?.exp_r)}">${fmtR(x.after?.exp_r)}</span>${x.version === r.version || API.demo ? '<span class="m" style="text-align:right">' + (x.version === r.version ? 'current' : '') + '</span>' : `<button class="btn" data-rb="${x.version}">Roll back</button>`}</div>`).join('') || '<div class="unavail">No versions yet</div>'}</div></div>`;
  const sel = $('#lrnSym'); if (sel) sel.onchange = () => { store.set('lrnSym', sel.value); $('#lrnRank').innerHTML = rankH(sel.value); };
  const run = $('#lrnRun'); if (run) run.onclick = async () => { run.disabled = true; run.textContent = 'Queued…'; try { await API.get('/api/learning/run', { confirm: 1 }); toast('Learning started - results in about a minute'); setTimeout(() => App.tab === 'learning' && Views.learning(v), 70000); } catch (e) { toast('Could not start: ' + (e.message || e)); run.disabled = false; run.textContent = 'Learn now'; } };
  $$('[data-rb]').forEach(btn => btn.onclick = async () => { if (!confirm(`Roll back to rules version ${btn.dataset.rb}?`)) return; try { await API.get('/api/learning/rollback', { version: btn.dataset.rb, confirm: 1 }); toast('Rolled back'); Views.learning(v); } catch (e) { toast('Rollback failed: ' + (e.message || e)); } });
};

/* ================= SETTINGS ================= */
Views.settings = async (v) => {
  const cur = store.get('bg', 'auto');
  v.innerHTML = `<div class="page-title">Settings</div><div class="page-sub">Display only. Trading settings live in config.yaml on the server.</div>
  <div class="panel" style="margin-bottom:16px" id="modeP"><h3>Display mode</h3>
    <div class="mode-row"><div class="seg" id="modeSeg"><button data-m="simple" class="${Mode.simple() ? 'on' : ''}">Simple</button><button data-m="pro" class="${Mode.simple() ? '' : 'on'}">Pro</button></div>
      <div class="sub" style="margin:0">${Mode.simple() ? 'Plain English: Buy / Sell, money at risk in €, a short "why this trade" instead of trading codes, and heavy charts folded away.' : 'Full trading terms: LONG / SHORT, R-multiples, ICT tags (BOS, FVG, order blocks), all panels open.'}</div></div>
    <label class="mode-row" style="margin-top:12px;cursor:pointer"><input type="checkbox" id="quoteT" ${Quotes.on() ? 'checked' : ''}> <span>Motivational quote on the dashboard <span class="m">(matches the theme)</span></span></label></div>
  <div class="panel" style="margin-bottom:16px"><h3>Theme <span class="right">palette + matching background, saved in this browser</span></h3>
    <div class="themes" id="themes">${Object.entries(Theme.THEMES).map(([k, t]) => { const bg = App.BGS.find(b => b.id === t.scenes[0]); return `<button class="theme-card ${t.light ? 'is-light' : ''} ${Theme.cur.theme === k && Theme.cur.palette !== 'custom' ? 'on' : Theme.cur.theme === k ? 'on custom' : ''}" data-th="${k}" style="--tg:${t.g};--tr:${t.r};--tc:${t.c};--tp:${Theme.rgb(t.panel)};--ta:${t.a}">
      <span class="tc-img" style="background-image:url(${bg?.src || ''})"></span>
      <span class="tc-glass"><i style="background:${t.g}"></i><i style="background:${t.r}"></i><i style="background:${t.c}"></i><svg viewBox="0 0 100 30" preserveAspectRatio="none"><path d="M0 26 C15 24 20 14 32 17 S50 8 62 12 80 2 100 4" fill="none" stroke="${t.g}" stroke-width="2.2"/></svg></span>
      <span class="tc-name">${esc(t.name)}<small>${esc(t.sub)}</small></span></button>`; }).join('')}</div>
    ${Theme.cur.palette === 'custom' ? '<div class="sub" style="margin-top:10px">Custom colours are on top of the selected theme. Pick a theme again to reset them.</div>' : ''}</div>
  <div class="grid cols-2">
    <div class="panel"><h3>Background</h3><div class="bg-opts" id="bgo">${App.BGS.map(b => `<div class="bg-opt ${b.id === cur ? 'on' : ''}" data-b="${b.id}" style="${b.src ? `background-image:url(${b.src})` : ''}">${b.art ? `<canvas data-art="${b.art}"></canvas>` : ''}${b.id === 'auto' ? '<canvas data-art="flow"></canvas>' : ''}<span>${esc(b.name)}</span></div>`).join('')}</div>
      <div class="sub" style="margin-top:12px">"Cinematic" follows the theme and changes the scene per tab. Photos: The Metropolitan Museum of Art, Open Access (CC0).</div></div>
    <div class="panel"><h3>Display</h3>
      <div class="set-row"><span>Live PnL widget (Dashboard, Live chart)</span><button class="switch ${store.get('pnlWidget', true) ? 'on' : ''}" data-s="pnlWidget"></button></div>
      <div class="set-row"><span>Floating particles</span><button class="switch ${store.get('particles', true) ? 'on' : ''}" data-s="particles"></button></div>
      <div class="set-row"><span>Particle density <b class="num" id="pdV">${store.get('pdensity', 100)}%</b></span><input type="range" min="25" max="200" step="25" value="${store.get('pdensity', 100)}" id="pd" style="width:160px"></div>
      <div class="set-row"><span>Splash screen</span><button class="switch ${store.get('splash', true) ? 'on' : ''}" data-s="splash"></button></div>
      <div class="set-row"><span>Background dim</span><input type="range" min="0" max="80" value="${store.get('dim', 25)}" id="dim" style="width:160px"></div>
      <div class="set-row"><span>Greeting name</span><input class="txt" style="width:160px;height:36px" id="nm" value="${esc(store.get('name', 'Emis'))}"></div>
      <h3 style="margin-top:20px">Connection</h3>
      <div class="set-row"><span>${API.demo ? '<span class="a">DEMO mode</span> - sample data' : '<span class="g">Connected</span> to your FlowDesk API'}</span>${API.demo ? '' : '<button class="btn" id="disc">Use demo</button>'}</div>
      <div class="sub">To connect, open the desk link FlowDesk sends in Telegram (/desk). It carries the API address and your desk key; the key stays in this browser.</div>
    </div></div>
    <div class="panel" style="margin-top:16px" id="rulesP"><h3>Trading rules <span class="right">live from the server config</span></h3><div class="skeleton" style="height:120px"></div></div>
    <div class="panel" style="margin-top:16px"><h3>Colours <span class="right">applies live to every tab, chart and particle</span></h3>
      <div class="pal" id="pal">${Object.entries(Theme.PALETTES).map(([k, p]) => `<button data-p="${k}" class="${Theme.cur.palette === k || (!Theme.cur.palette && k === 'neon') ? 'on' : ''}"><div class="sw"><i style="background:${p.g};box-shadow:0 0 8px ${p.g}"></i><i style="background:${p.r}"></i><i style="background:${p.c}"></i><i style="background:${p.panel};border:1px solid #333"></i></div>${esc(p.name)}</button>`).join('')}</div>
      <div class="grid cols-2" style="margin-top:12px;gap:0 24px">
        <div class="set-row"><span>Long / profit</span><input type="color" data-t="g" value="${Theme.cur.g}"></div>
        <div class="set-row"><span>Short / loss</span><input type="color" data-t="r" value="${Theme.cur.r}"></div>
        <div class="set-row"><span>Lines / accent</span><input type="color" data-t="c" value="${Theme.cur.c}"></div>
        <div class="set-row"><span>Panel tint</span><input type="color" data-t="panel" value="${Theme.cur.panel}"></div>
        <div class="set-row"><span>Panel opacity <b class="num" id="aV">${Math.round(Theme.cur.a * 100)}%</b></span><input type="range" min="15" max="90" value="${Math.round(Theme.cur.a * 100)}" data-r="a" style="width:160px"></div>
        <div class="set-row"><span>Glow intensity <b class="num" id="glowV">${Math.round(Theme.cur.glow * 100)}%</b></span><input type="range" min="0" max="200" value="${Math.round(Theme.cur.glow * 100)}" data-r="glow" style="width:160px"></div>
      </div>
      <div style="display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap"><span class="pill long">▲ LONG</span><span class="pill short">▼ SHORT</span><span class="glow-g big num">${money(12.4)}</span><span class="glow-r big num">${money(-3.1)}</span><button class="btn" id="resetTheme" style="margin-left:auto">Reset to theme colours</button></div>
    </div>`;
  $$('#bgo canvas').forEach(c => FX.drawArt(c, c.dataset.art, 300, 184));
  App.loadCfg().then(c => { const el = $('#rulesP'); if (!el) return; if (!c || !c.ok) { el.innerHTML = '<h3>Trading rules</h3>' + (API.demo ? '<div class="sub">Demo mode - connect your bot to see its live rules.</div>' : unavailable('Server config')); return; }
    const z = c.sizing || {}, b = c.broker || {}, row = (k, val) => `<div class="set-row"><span>${esc(k)}</span><b class="num">${esc(val)}</b></div>`;
    const tiers = (z.tiers || []).map(([w, r], i, a) => row(i === a.length - 1 ? `Backtest win rate below ${a[i - 1]?.[0] ?? w}%` : `Backtest win rate ≥ ${w}%`, r + '% risk')).join('');
    const strat = Object.values(c.learning?.strategies || {}).map(x => `<span class="tag" style="${x.enabled ? '' : 'opacity:.55'}">${x.enabled ? '🟢' : '⚪'} ${esc(x.name)}</span>`).join(' ');
    el.innerHTML = `<h3>Trading rules <span class="right">live from the server config</span></h3><div class="grid cols-2" style="gap:0 24px"><div>
      <div class="label" style="margin:4px 0">Risk per trade (paper)</div>${tiers}${row('Negative expectancy', z.negative_risk_pct + '% risk')}${row(`Low sample (< ${z.low_sample_n} trades) / not ready`, z.base_risk_pct + '% risk')}${row(`Skip if expectancy ≤ ${z.skip_expectancy_r}R with ${z.skip_min_n}+ trades`, 'no trade')}</div><div>
      <div class="label" style="margin:4px 0">Limits</div>${row('Total open risk cap', b.max_open_risk_pct + '% of equity')}${b.max_same_direction_risk_pct ? row('All buys / all sells together', '≤ ' + b.max_same_direction_risk_pct + '% of equity') : ''}${b.max_same_direction_per_group ? row('Same-way bets on things that move together', 'max ' + b.max_same_direction_per_group + ' (indices + crypto, yen pairs, dollar pairs)') : ''}${row('Daily loss limit', '-' + b.daily_loss_limit_pct + '% of the day\'s balance')}${row('Max open positions', b.max_positions)}${row('Per symbol', b.max_per_symbol + ' (different setups)')}${row('Min confluence', (c.strategy?.min_score ?? '–') + '/100')}${row('News blackout', (c.events?.block_minutes_before ?? '–') + ' min before high impact')}</div></div>
      <div class="label" style="margin:12px 0 6px">Strategies (learning v${c.learning?.version ?? 0})</div><div>${strat || '<span class="m">–</span>'}</div>`; });
  $('#bgo').onclick = e => { const o = e.target.closest('.bg-opt'); if (!o) return; store.set('bg', o.dataset.b); $$('#bgo .bg-opt').forEach(x => x.classList.toggle('on', x === o)); App.applyBg('settings'); };
  $$('.switch').forEach(s => s.onclick = () => { const k = s.dataset.s; const nv = !store.get(k, true); store.set(k, nv); s.classList.toggle('on', nv); });
  $('#pd').oninput = e => { store.set('pdensity', +e.target.value); $('#pdV').textContent = e.target.value + '%'; };
  $('#pd').onchange = () => FX.ambient?.resize();
  $('#modeSeg').onclick = e => { const b = e.target.closest('[data-m]'); if (!b) return; Mode.set(b.dataset.m); Views.settings(v); };
  $('#quoteT').onchange = e => Quotes.set(e.target.checked);
  $('#themes').onclick = e => { const b = e.target.closest('[data-th]'); if (!b) return; Theme.setTheme(b.dataset.th); App.applyDim(); Views.settings(v); refresh(); };
  $('#dim').oninput = e => { store.set('dim', +e.target.value); App.applyDim(); };
  $('#nm').onchange = e => store.set('name', e.target.value.trim() || 'Emis');
  const d = $('#disc'); if (d) d.onclick = () => { API.disconnect(); location.reload(); };
  const refresh = () => { App.applyBg('settings'); $$('#bgo canvas').forEach(c => FX.drawArt(c, c.dataset.art, 300, 184)); };
  $('#pal').onclick = e => { const b = e.target.closest('button[data-p]'); if (!b) return; const nx = Object.assign({}, Theme.PALETTES[b.dataset.p], { palette: b.dataset.p }); delete nx.name; if (Theme.light) Object.assign(nx, { light: false, theme: 'neon' }); Theme.save(nx); App.applyDim(); Views.settings(v); refresh(); };
  $$('input[type=color][data-t]').forEach(i => i.oninput = () => { Theme.save({ [i.dataset.t]: i.value, palette: 'custom' }); $$('#pal button').forEach(x => x.classList.remove('on')); });
  $$('input[type=color][data-t]').forEach(i => i.onchange = refresh);
  $$('input[type=range][data-r]').forEach(i => i.oninput = () => { const k = i.dataset.r; Theme.save({ [k]: +i.value / 100, palette: 'custom' }); $(k === 'a' ? '#aV' : '#glowV').textContent = i.value + '%'; });
  $('#resetTheme').onclick = () => { const th = Theme.cur.theme || 'neon'; Theme.setTheme(th); App.applyDim(); Views.settings(v); refresh(); };
};

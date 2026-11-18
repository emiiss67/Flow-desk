/* Tab views */
const Views = {};
const ICON_SEARCH = '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>';
const sidePill = s => `<span class="pill ${s === 'LONG' ? 'long' : s === 'SHORT' ? 'short' : 'none'}">${s === 'LONG' ? '▲' : s === 'SHORT' ? '▼' : '•'} ${esc(s)}</span>`;
const unavailable = (what, err) => `<div class="unavail">${esc(what)}: data unavailable${err ? `<br><span style="font-size:11.5px;color:var(--dim)">${esc(err)}</span>` : ''}</div>`;
const greeting = () => { const h = new Date().getHours(); return h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'; };
async function load(path, params) { try { return [await API.get(path, params), null]; } catch (e) { return [null, e.message || String(e)]; } }

/* ================= DASHBOARD ================= */
Views.dashboard = async (v) => {
  v.innerHTML = `<div class="greet"><div><h1>${greeting()}, ${esc(store.get('name', 'Emis'))}.</h1>
    <div class="sub">${new Date().toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })} · <span id="mkt"></span></div></div>
    <div class="seg" id="dashRange"><button class="on">30D</button></div></div>
    <div class="grid cols-main" style="margin-top:8px"><div id="dMain"><div class="skeleton" style="height:420px"></div></div><div id="dSide"></div></div>`;
  const [d, err] = await load('/api/dashboard');
  if (!d) { $('#dMain').innerHTML = `<div class="panel">${unavailable('Dashboard', err)}</div>`; return; }
  const kz = (() => { const ny = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' })); const t = ny.getHours() + ny.getMinutes() / 60, wd = ny.getDay();
    if (wd === 6 || (wd === 0 && t < 18) || (wd === 5 && t >= 17)) return 'Markets closed (weekend)'; if (t >= 2 && t < 5) return 'London killzone active'; if (t >= 7 && t < 10) return 'New York killzone active'; if (t >= 20) return 'Asia session'; return 'Markets open'; })();
  $('#mkt').textContent = kz;
  const net30 = d.daily_30.reduce((a, b) => a + b.pnl, 0);
  const st = d.status; const stCls = st === 'running' ? '' : st === 'paused' ? 'pause' : 'off';
  const lt = d.last_trades || []; const mx = Math.max(1, ...lt.map(t => Math.abs(t.pnl)));
  const dm = Math.max(1, ...d.daily_30.map(x => Math.abs(x.pnl)));
  const streakDash = Array.from({ length: 14 }, (_, i) => { const t = lt[lt.length - 14 + i]; return `<i class="${t ? (t.pnl > 0 ? 'w' : 'l') : ''}"></i>`; }).join('');
  $('#dMain').innerHTML = `
    <div class="hero"><div class="label">Net P&amp;L · 30 days</div><div class="huge num ${net30 > 0 ? 'glow-g' : net30 < 0 ? 'glow-r' : ''}">${money(net30)}</div>
      <div class="sub">Paper balance <b class="num" style="color:#fff">${money2(d.balance)}</b> · equity <span class="num">${money2(d.equity)}</span></div></div>
    <div class="grid cols-4" style="margin-top:26px">
      <div class="panel stat"><div class="label">Status today</div><div class="v"><span class="dot-live ${stCls}"></span>${st === 'running' ? 'Clean' : st === 'paused' ? 'Paused' : 'Offline'}</div><div class="sub">${d.daily_limit_hit ? '<span class="r">Daily loss limit hit</span>' : 'Bot ' + esc(st) + (d.heartbeat ? ' · scan ' + ago(d.heartbeat) : '')}</div></div>
      <div class="panel stat"><div class="label">Net result · today</div><div class="v num ${pnlClass(d.today_pnl)}">${money(d.today_pnl)}</div><div class="sub">Realized, paper</div></div>
      <div class="panel stat"><div class="label">Win rate</div><div class="v num">${d.win_rate}%</div><div class="sub">${d.trades} closed trades · PF ${d.profit_factor ?? '–'}</div></div>
      <div class="panel stat"><div class="label">Risk blocks · 24h</div><div class="v num">${d.blocked_24h}</div><div class="sub">${d.signals_24h} signals · ${d.entries_24h} entries</div></div>
    </div>
    <div class="grid cols-3" style="margin-top:16px">
      <div class="panel"><h3>Win streak</h3><div class="big num">${d.streak}</div><div class="sub">wins in a row · best ${d.best_streak}</div><div class="streak">${streakDash}</div></div>
      <div class="panel"><h3>Last 14 trades</h3><div class="bars-mid"><div class="axis"></div><div class="cols">${lt.length ? lt.map(t => `<div class="col" title="${esc(t.symbol)} ${money(t.pnl)}"><i class="${t.pnl > 0 ? 'p' : 'n'}" style="height:${Math.max(3, Math.abs(t.pnl) / mx * 48)}%"></i></div>`).join('') : '<div class="m" style="margin:auto;font-size:13px">No trades yet</div>'}</div></div></div>
      <div class="panel"><h3>P&amp;L · 30 days <span class="right num ${pnlClass(net30)}">${money(net30)}</span></h3><div class="bars">${d.daily_30.map(x => `<div class="b ${x.pnl > 0 ? 'p' : x.pnl < 0 ? 'n' : 'z'}" title="${x.date} ${money(x.pnl)}" style="height:${x.pnl ? Math.max(6, Math.abs(x.pnl) / dm * 100) : 3}%"></div>`).join('')}</div></div>
    </div>
    <div class="panel" style="margin-top:16px"><h3>When it works · hour by weekday <span class="right">UTC hours · entries</span></h3>${heatmap(d.heatmap)}</div>`;
  const ev = d.upcoming_events || [];
  $('#dSide').innerHTML = `
    <div class="panel"><h3>Today's plan</h3><ul class="plan">${d.plan.map(p => `<li><span class="ck">✓</span>${esc(p)}</li>`).join('')}</ul></div>
    <div class="panel" style="margin-top:16px"><h3>Open positions <span class="right">${d.open_positions.length}</span></h3>${d.open_positions.length ? d.open_positions.map(p => `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid var(--line)"><div><b>${esc(p.symbol)}</b> ${sidePill(p.side)}<div class="sub">@ ${fp(p.entry)} · SL ${fp(p.sl)}</div></div><div class="num ${pnlClass(p.unrealized)}" style="font-weight:800">${money(p.unrealized)}</div></div>`).join('') : '<div class="m" style="font-size:13px">Flat. Waiting for confluence.</div>'}</div>
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
      <div class="search">${ICON_SEARCH}<input id="q" placeholder="Search or type any Yahoo ticker (e.g. AAPL, EURNOK=X)" autocomplete="off" autocapitalize="characters" spellcheck="false"></div>
      <div class="inst-list" id="ilist"></div>
      <div class="selected-inst"><div><div class="label" style="margin:0 0 4px">Selected</div><div class="n" id="selSym">${esc(sel)}</div></div><div class="seg" id="tfs">${['5m', '15m', '1h', '4h', '1d'].map(t => `<button data-tf="${t}" class="${t === tf ? 'on' : ''}">${t}</button>`).join('')}</div></div>
      <button class="check-btn" id="go">Check</button>
      <div class="sub" style="text-align:center;margin-top:10px">Analysis only · never places a trade</div>
    </div></div>
    <div id="res"><div class="panel empty"><div><div class="big-ic">◎</div><div style="font-weight:600;color:#fff;margin-bottom:6px">Ready when you are</div>Select an instrument and press <b>Check</b>.</div></div></div>
  </div>`;
  let items = INSTRUMENTS; let selected = sel; let tfSel = tf;
  load('/api/instruments').then(([r]) => { if (r?.items?.length) { items = r.items; draw(); } });
  const draw = () => {
    const q = $('#q').value.trim().toLowerCase();
    const list = items.filter(i => (cat === 'All' || i.category === cat) && (!q || i.symbol.toLowerCase().includes(q) || i.name.toLowerCase().includes(q)));
    let html = list.map(i => `<div class="inst ${i.symbol === selected ? 'on' : ''}" data-s="${esc(i.symbol)}"><b>${esc(i.symbol)}</b><span>${esc(i.name)}</span></div>`).join('');
    if (q && !list.some(i => i.symbol.toLowerCase() === q)) html = `<div class="inst" data-s="${esc($('#q').value.trim().toUpperCase())}"><b>${esc($('#q').value.trim().toUpperCase())}</b><span>Use as Yahoo ticker →</span></div>` + html;
    $('#ilist').innerHTML = html || '<div class="m" style="padding:10px;font-size:13px">No match</div>';
  };
  draw();
  $('#q').addEventListener('input', draw);
  $('#q').addEventListener('keydown', e => { if (e.key === 'Enter') { const f = $('#ilist .inst'); if (f) f.click(); run(); } });
  $('#cats').addEventListener('click', e => { const b = e.target.closest('.chip'); if (!b) return; cat = b.dataset.c; store.set('checkCat', cat); $$('#cats .chip').forEach(x => x.classList.toggle('on', x === b)); draw(); });
  $('#ilist').addEventListener('click', e => { const it = e.target.closest('.inst'); if (!it) return; selected = it.dataset.s; store.set('checkSym', selected); $('#selSym').textContent = selected; draw(); });
  $('#tfs').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; tfSel = b.dataset.tf; store.set('checkTf', tfSel); $$('#tfs button').forEach(x => x.classList.toggle('on', x === b)); });
  const run = async () => {
    const btn = $('#go'); btn.disabled = true; btn.innerHTML = '<span class="spin"></span>Reading the flow…';
    $('#res').innerHTML = '<div class="panel"><div class="skeleton" style="height:120px"></div><div class="skeleton" style="height:330px;margin-top:14px"></div></div>';
    const [r, err] = await load('/api/check', { symbol: selected, tf: tfSel });
    btn.disabled = false; btn.textContent = 'Check';
    if (!r || !r.ok) { $('#res').innerHTML = `<div class="panel">${unavailable(selected, err || r?.detail)}</div>`; return; }
    renderResult(r);
  };
  $('#go').addEventListener('click', run);
  if (store.get('autoCheck', false) || App.demoAuto) { App.demoAuto = false; run(); }
};

function renderResult(r) {
  const D = r.decision; const cls = D === 'LONG' ? 'long' : D === 'SHORT' ? 'short' : 'none';
  const col = D === 'LONG' ? Theme.g : D === 'SHORT' ? Theme.r : '#9CA3AF'; const lv = r.levels;
  const risk = lv ? Math.abs(lv.entry - lv.sl) : null;
  $('#res').innerHTML = `
    <div class="panel">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">
        <div><div class="label" style="margin-bottom:6px">${esc(r.name)} · ${esc(r.tf)} · ${esc(r.category || '')}</div>
          <div class="verdict"><div class="call ${cls}">${D === 'NO TRADE' ? 'NO TRADE' : D}</div>
          <div class="gauge" title="Confluence score: how many independent reasons line up, weighted. It is a score out of 100, not a probability of winning.">${FX.gauge(r.confluence, col)}<div class="gv num" style="color:${col}">${r.confluence}</div><div class="gl">confluence /100</div></div></div>
          <div class="sub" style="margin-top:8px">Confluence score (0-100) · not a probability of winning</div></div>
        <div style="text-align:right"><div class="label" style="margin-bottom:6px">Last price</div><div class="big num mono">${fp(r.price)}</div><div class="sub">L ${r.scores.long} · S ${r.scores.short} · ATR ${fp(r.atr)}</div></div>
      </div>
      ${lv ? `<div class="levels">
        <div class="lv en"><div class="k">Entry</div><div class="v">${fp(lv.entry)}</div></div>
        <div class="lv sl"><div class="k">Stop loss</div><div class="v">${fp(lv.sl)}</div><div class="sub">${esc(lv.sl_basis)} · ${fp(risk)}</div></div>
        <div class="lv tp"><div class="k">TP1 · ${lv.rr1}R</div><div class="v">${fp(lv.tp1)}</div><div class="sub">${esc(lv.tp1_basis)}</div></div>
        <div class="lv tp"><div class="k">TP2 · ${lv.rr2}R</div><div class="v">${fp(lv.tp2)}</div><div class="sub">${esc(lv.tp2_basis)}</div></div>
        <div class="lv"><div class="k">Risk : reward</div><div class="v">1 : ${lv.rr2}</div><div class="sub">50% off at TP1</div></div></div>`
      : `<div class="warn" style="margin-top:16px">⚪ ${esc(r.watch?.note || 'Not enough confluence')}${r.watch ? ` · lean ${esc(r.watch.bias.toLowerCase())}, ref SL ${fp(r.watch.sl)} / TP ${fp(r.watch.tp1)}` : ''}</div>`}
      <div id="wrBox">${wrHTML(r.winrate, r)}</div>
      ${r.blackout ? `<div class="warn block">⛔ High-impact ${esc(r.blackout.ccy)} event "${esc(r.blackout.title)}" too close - standing aside.</div>` : ''}
      ${(r.warnings || []).map(w => `<div class="warn">⚠️ ${esc(w.text)}</div>`).join('')}
    </div>
    <div class="panel" style="margin-top:16px;padding:12px"><div class="chart-box" id="ckChart"></div>
      <div class="legend"><span><i style="background:rgba(${Theme.G},.35)"></i>Bull FVG</span><span><i style="background:rgba(${Theme.R},.35)"></i>Bear FVG</span><span><i style="background:rgba(${Theme.C},.45)"></i>Bull OB</span><span><i style="background:rgba(245,181,68,.45)"></i>Bear OB · POC</span><span><i style="background:rgba(110,139,255,.4)"></i>Killzones</span><span>$$$ liquidity</span></div></div>
    <div class="grid cols-2" style="margin-top:16px">
      <div class="panel"><h3>Why ${D === 'NO TRADE' ? '(strongest side)' : esc(D.toLowerCase())}</h3><ul class="reasons">${r.reasons.map(x => `<li><span class="pt">+${x.points}</span><div>${esc(x.text)}<div><span class="tag">${esc(x.tag)}</span></div></div></li>`).join('') || '<li class="m">No confluence found</li>'}</ul></div>
      <div class="panel"><h3>Against it</h3><ul class="reasons against">${(r.against || []).map(x => `<li><span class="pt">-${x.points}</span><div>${esc(x.text)}<div><span class="tag">${esc(x.tag)}</span></div></div></li>`).join('') || '<li class="m" style="font-size:13px">Nothing meaningful against it.</li>'}</ul>
        ${(r.headlines || []).length ? `<h3 style="margin-top:16px">Related headlines</h3>${r.headlines.map(n => `<a class="news-item" href="${esc(n.link)}" target="_blank" rel="noopener"><div class="t">${esc(n.title)}</div><div class="meta">${esc(n.source)} · ${ago(n.ts)}</div></a>`).join('')}` : ''}
        <div class="sub" style="margin-top:14px">Source: ${esc(r.source)}. ${esc(r.source_note || '')} Order flow: <span class="est">estimated</span> (${esc(r.volume_source || 'OHLCV')}).</div></div>
    </div>`;
  const c = Charts.create($('#ckChart')); Charts.set(c, r);
  if (r.winrate && r.winrate.status === 'computing') pollWR(r);
}

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
      <div><div class="k">Win rate</div><div class="v num ${wc}">${pc(w.win_rate)}</div><div class="sub">TP1 before SL</div></div>
      <div><div class="k">Full TP2</div><div class="v num">${pc(w.tp2_rate)}</div><div class="sub">ran to target</div></div>
      <div><div class="k">Trades (n)</div><div class="v num">${w.n}</div><div class="sub">${w.period_from ? dmy(w.period_from) + ' → ' + dmy(w.period_to) : ''}</div></div>
      <div><div class="k">Avg R</div><div class="v num ${w.avg_r >= 0 ? 'g' : 'r'}">${sg(w.avg_r)}R</div><div class="sub">per trade</div></div>
      <div><div class="k">Expectancy</div><div class="v num ${w.expectancy_usd >= 0 ? 'g' : 'r'}">${sg(w.expectancy_usd ?? 0)}</div><div class="sub">USD/trade at ${money(w.risk_usd ?? 0.5)} risk</div></div>
    </div>
    ${w.low_sample ? '<div class="warn" style="margin-top:10px">⚠️ Low sample (n &lt; 20) - treat this win rate as anecdotal.</div>' : ''}
    <div class="sub" style="margin-top:8px">Walk-forward replay of the same rules on ${esc(r.source || 'the feed')} history, paper-broker exits (SL first on ambiguous bars, 50% at TP1 then breakeven, trail, TP2). ${esc(w.note || '')} Past results do not predict future ones.</div></div>`;
}

async function pollWR(r) {
  const side = r.decision === 'NO TRADE' ? (r.watch?.bias || 'LONG') : r.decision;
  for (let k = 0; k < 40; k++) {
    await new Promise(res => setTimeout(res, 4000));
    const box = $('#wrBox'); if (!box || box.dataset.sym && box.dataset.sym !== r.symbol) return;
    const [w] = await load('/api/winrate', { symbol: r.symbol, tf: r.tf, direction: side, score: r.confluence });
    if (!$('#wrBox')) return;
    if (w && w.status !== 'computing') { $('#wrBox').innerHTML = wrHTML(w, r); return; }
  }
}

/* ================= LIVE CHART ================= */
Views.chart = async (v) => {
  let sym = store.get('chartSym', 'NQ=F'), tf = store.get('chartTf', '15m'); const tg = store.get('chartToggles', { fvg: true, ob: true, liq: true, vp: true, sess: true, struct: true });
  const names = { fvg: 'FVG', ob: 'Order blocks', liq: 'Liquidity', vp: 'Volume profile', sess: 'Killzones', struct: 'BOS / CHoCH' };
  v.innerHTML = `<div class="page-title">Live chart</div><div class="page-sub" id="chSub">Candles with ICT and estimated order-flow overlays.</div>
    <div class="panel" style="padding:12px">
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between;margin-bottom:10px">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><div class="search" style="height:38px;width:220px">${ICON_SEARCH}<input id="chq" value="${esc(sym)}" list="chl" autocapitalize="characters"></div>
          <datalist id="chl">${INSTRUMENTS.map(i => `<option value="${esc(i.symbol)}">${esc(i.name)}</option>`).join('')}</datalist>
          <div class="seg" id="chtf">${['1m', '5m', '15m', '1h', '4h', '1d'].map(t => `<button data-tf="${t}" class="${t === tf ? 'on' : ''}">${t}</button>`).join('')}</div></div>
        <div class="toggles" id="chtg">${Object.keys(names).map(k => `<button class="chip ${tg[k] ? 'on' : ''}" data-k="${k}">${names[k]}</button>`).join('')}</div>
      </div>
      <div class="chart-box tall" id="lc"></div>
      <div class="legend"><span><i style="background:rgba(${Theme.G},.9)"></i>Buy pressure surge</span><span><i style="background:rgba(${Theme.R},.9)"></i>Sell pressure surge</span><span><i style="background:var(--cyan);border-radius:50%"></i>Absorption</span><span>Bars below: estimated delta</span><span class="est">estimated</span></div>
    </div>`;
  const c = Charts.create($('#lc'));
  const go = async (fit = true) => {
    const [r, err] = await load('/api/chart', { symbol: sym, tf });
    if (!r || !r.ok) { $('#chSub').innerHTML = `<span class="r">${esc(sym)}: data unavailable</span> ${esc(err || r?.detail || '')}`; return; }
    $('#chSub').innerHTML = `${esc(r.name)} · ${esc(r.tf)} · last <b class="num">${fp(r.price)}</b> · ${esc(r.source)} <span style="color:var(--dim)">${esc(r.source_note || '')}</span>`;
    Charts.set(c, r, Object.assign({}, tg, { fit, levels: true }));
  };
  go();
  $('#chq').addEventListener('change', e => { sym = e.target.value.trim().toUpperCase(); store.set('chartSym', sym); go(); });
  $('#chtf').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; tf = b.dataset.tf; store.set('chartTf', tf); $$('#chtf button').forEach(x => x.classList.toggle('on', x === b)); go(); });
  $('#chtg').addEventListener('click', e => { const b = e.target.closest('.chip'); if (!b) return; tg[b.dataset.k] = !tg[b.dataset.k]; b.classList.toggle('on'); store.set('chartToggles', tg); c.opts[b.dataset.k] = tg[b.dataset.k]; c.redraw(); });
  App.timer(() => go(false), 60000);
};

/* ================= SIGNALS ================= */
Views.signals = async (v) => {
  v.innerHTML = `<div class="page-title">Signals</div><div class="page-sub">Every call the scanner made on the watchlist, taken or blocked.</div><div class="panel" id="sg"><div class="skeleton" style="height:300px"></div></div>`;
  const [r, err] = await load('/api/signals'); if (!r) { $('#sg').innerHTML = unavailable('Signals', err); return; }
  $('#sg').innerHTML = `<div class="rows"><div class="row head"><div>Symbol</div><div>Call</div><div>Confluence</div><div class="r-right">Levels</div><div class="r-right">Score · win rate</div></div>${r.signals.map(s => `
    <div class="row"><div><div class="sym">${esc(s.symbol)}</div><div class="sub" style="margin:2px 0 0">${dmy(s.ts)} ${hm(s.ts)} · ${esc(s.tf)}</div></div><div>${sidePill(s.decision)}</div>
    <div class="tags">${(s.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div>
    <div class="r-right num mono" style="font-size:12px">${fp(s.price)}<div class="sub" style="margin:2px 0 0">SL ${fp(s.sl)} · TP ${fp(s.tp2)}</div></div>
    <div class="r-right"><b class="num" title="Confluence score (not a probability)">${Math.round(s.confluence ?? s.confidence ?? 0)}<span class="m" style="font-size:11px">/100</span></b>${s.win_rate != null ? `<div class="sub" style="margin:2px 0 0" title="Backtest win rate (TP1 before SL), n trades">win ${Math.round(s.win_rate)}% · n${s.bt_n}${s.bt_n < 20 ? ' <span class="a">low</span>' : ''}</div>` : ''}<div class="sub" style="margin:2px 0 0">${s.acted ? '<span class="g">entered</span>' : '<span class="a">' + esc(s.note || 'skipped') + '</span>'}</div></div></div>`).join('') || '<div class="unavail">No signals yet - the scanner journals each one here.</div>'}</div>`;
};

/* ================= POSITIONS ================= */
Views.positions = async (v) => {
  v.innerHTML = `<div class="page-title">Positions</div><div class="page-sub">Open paper positions. Manage from Telegram with <span class="mono">/close SYMBOL</span>, <span class="mono">/pause</span>.</div><div class="panel" id="ps"><div class="skeleton" style="height:200px"></div></div>`;
  const draw = async () => {
    const [r, err] = await load('/api/positions'); if (!r) { $('#ps').innerHTML = unavailable('Positions', err); return; }
    const tot = r.positions.reduce((a, p) => a + p.unrealized, 0);
    $('#ps').innerHTML = `<h3>Open · ${r.positions.length} <span class="right num ${pnlClass(tot)}" style="font-weight:800">${money(tot)} unrealized</span></h3>` + (r.positions.map(p => `
    <div class="pos"><div><b style="font-size:15px">${esc(p.symbol)}</b> ${sidePill(p.side)} ${p.tp1_hit ? '<span class="tag">TP1 hit · SL at BE</span>' : ''}<div class="sub">${esc(p.tf)} · opened ${ago(p.opened_ts)} · ${(p.tags || []).map(t => esc(t)).join(' · ')}</div></div>
      <div><span class="k">Entry</span><span class="num mono">${fp(p.entry)}</span></div><div><span class="k">Last</span><span class="num mono">${fp(p.last_price)}</span></div>
      <div><span class="k">Stop</span><span class="num mono r">${fp(p.sl)}</span></div><div><span class="k">Targets</span><span class="num mono g">${fp(p.tp1)} / ${fp(p.tp2)}</span></div>
      <div style="text-align:right"><span class="k">P&amp;L</span><b class="num ${pnlClass(p.unrealized + p.realized)}" style="font-size:17px">${money(p.unrealized + p.realized)}</b></div></div>`).join('') || '<div class="empty" style="min-height:160px"><div><div class="big-ic">◌</div>Flat. The bot enters only when confluence passes.</div></div>');
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
      <div class="meta"><span>${esc(i.source)}</span><span>·</span><span>${ago(i.ts)}</span>${(i.symbols || []).slice(0, 4).map(s => `<span class="tag">${esc(s)}</span>`).join('')}</div></a>`).join('') + '<div class="sub" style="margin-top:10px">▲▼ = simple keyword tone, not a sentiment model.</div>';
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
      <div class="filters" style="margin:0">${['All', 'LONG', 'SHORT'].map(x => `<button class="chip ${x === side ? 'on' : ''}" data-f="side" data-v="${x}">${x === 'All' ? 'All sides' : x}</button>`).join('')}
        ${['All', 'Wins', 'Losses', 'Open'].map(x => `<button class="chip ${x === res ? 'on' : ''}" data-f="res" data-v="${x}">${x === 'All' ? 'All results' : x}</button>`).join('')}
        <select class="chip" id="jsym">${syms.map(s => `<option ${s === sym ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></div>
      <div class="num ${pnlClass(tot)}" style="font-weight:800">${ts.length} trades · ${money(tot)}</div></div>
      <div class="rows"><div class="row head"><div>Symbol</div><div>Side</div><div>Confluence</div><div class="r-right">Time</div><div class="r-right">P&amp;L</div></div>
      ${ts.map(t => `<div class="row" title="${esc((t.reasons || []).join('\n'))}"><div><div class="sym">${esc(t.symbol)}</div><div class="sub" style="margin:2px 0 0">${esc(t.exit_reason || t.status)}</div></div><div>${sidePill(t.side)}</div>
        <div class="tags">${(t.tags || []).map(x => `<span class="tag">${esc(x)}</span>`).join('')}</div>
        <div class="r-right m num" style="font-size:12px">${dmy(t.opened_ts)}<div>${hm(t.opened_ts)}</div></div>
        <div class="r-right"><b class="num ${pnlClass(t.pnl_usd)}">${money(t.pnl_usd)}</b><div class="sub num" style="margin:2px 0 0">${t.r_multiple != null ? (t.r_multiple >= 0 ? '+' : '') + Number(t.r_multiple).toFixed(2) + 'R' : 'open'}</div></div></div>`).join('') || '<div class="unavail">No trades yet.</div>'}</div>`;
    $$('#jr .chip[data-f]').forEach(b => b.onclick = () => { if (b.dataset.f === 'side') side = b.dataset.v; else res = b.dataset.v; draw(); });
    $('#jsym').onchange = e => { sym = e.target.value; draw(); };
  };
  draw();
};

/* ================= PERFORMANCE ================= */
Views.performance = async (v) => {
  v.innerHTML = `<div class="page-title">Performance</div><div class="page-sub">Paper account since start.</div><div id="pf"><div class="skeleton" style="height:520px"></div></div>`;
  const [p, err] = await load('/api/performance'); if (!p) { $('#pf').innerHTML = `<div class="panel">${unavailable('Performance', err)}</div>`; return; }
  const pf = p.profit_factor; const good = pf != null && pf >= 1;
  const ret = p.start_balance ? (p.net / p.start_balance * 100) : 0;
  let series = p.equity_curve?.length ? p.equity_curve : (p.equity_snapshots?.length >= 2 ? p.equity_snapshots : []);
  const flat = !series.length; const nowS = Math.floor(Date.now() / 1000);
  if (flat) series = [{ time: nowS - 7 * 86400, value: p.balance ?? p.start_balance }, { time: nowS, value: p.balance ?? p.start_balance }];
  $('#pf').innerHTML = `
    <div class="grid cols-4">
      <div class="panel stat"><div class="label">Net return</div><div class="v num ${p.net > 0 ? 'glow-g' : p.net < 0 ? 'glow-r' : ''}">${money(p.net)}</div><div class="sub">${ret >= 0 ? '+' : ''}${ret.toFixed(2)}% · avg ${p.avg_r >= 0 ? '+' : ''}${p.avg_r}R</div></div>
      <div class="panel stat"><div class="label">Win rate</div><div style="display:flex;align-items:center;gap:12px"><div class="v num">${p.win_rate}%</div><div class="gauge" style="width:84px;height:48px">${FX.gauge(p.win_rate, p.win_rate >= 50 ? Theme.g : Theme.r).replace('<svg ', '<svg style="width:84px;height:48px" ')}</div></div><div class="sub">${p.wins}W · ${p.losses}L of ${p.trades}</div></div>
      <div class="panel stat"><div class="label">Profit factor</div><div class="v num">${pf ?? '–'}</div><div>${p.trades ? (good ? '<span class="badge-ok">PROFITABLE</span>' : '<span class="badge-bad">BELOW 1.0</span>') : ''} <span class="sub">Max drawdown ${money2(p.max_drawdown)}</span></div></div>
      <div class="panel stat"><div class="label">Average trade</div><div class="v num"><span class="g">${money(p.avg_win)}</span> <span class="m" style="font-size:16px">/</span> <span class="r">${money(p.avg_loss)}</span></div><div class="sub">avg win / avg loss</div></div>
    </div>
    <div class="panel perf-hero" style="margin-top:16px"><canvas id="eqc"></canvas>
      <div class="ph-top"><div><div class="label" style="margin:0 0 6px">Equity curve</div><div class="gap-line">${flat ? '<span class="a">No closed paper trades yet</span> · line shows realized balance · ' : ''}<b>${money(p.net)}</b> over the period · max drawdown <span class="r">${money2(p.max_drawdown)}</span> (${p.max_drawdown_pct}%)</div></div>
      <div class="legend" style="margin:0"><span><i style="background:var(--green)"></i>Equity</span><span><i style="background:transparent;border-top:2px dashed #6E8BFF;height:0"></i>Start balance</span></div></div></div>
    <div class="grid cols-2" style="margin-top:16px">
      <div class="panel"><h3>By instrument</h3><div class="rows">${Object.entries(p.by_symbol || {}).sort((a, b) => b[1].pnl - a[1].pnl).map(([s, b]) => `<div class="ev" style="grid-template-columns:1fr 70px 70px 90px"><b>${esc(s)}</b><span class="m num">${b.n} trades</span><span class="m num">${b.win_rate}%</span><b class="num ${pnlClass(b.pnl)}" style="text-align:right">${money(b.pnl)}</b></div>`).join('') || '<div class="unavail">No trades yet</div>'}</div></div>
      <div class="panel"><h3>Hour by weekday <span class="right">UTC</span></h3>${heatmap(p.heatmap)}</div>
    </div>`;
  FX.equity($('#eqc'), series, { base: p.start_balance, empty: 'No closed paper trades yet - the curve fills as the bot trades.' });
};

/* ================= SETTINGS ================= */
Views.settings = async (v) => {
  const cur = store.get('bg', 'auto');
  v.innerHTML = `<div class="page-title">Settings</div><div class="page-sub">Display only. Trading settings live in config.yaml on the server.</div>
  <div class="grid cols-2">
    <div class="panel"><h3>Background</h3><div class="bg-opts" id="bgo">${App.BGS.map(b => `<div class="bg-opt ${b.id === cur ? 'on' : ''}" data-b="${b.id}" style="${b.src ? `background-image:url(${b.src})` : ''}">${b.art ? `<canvas data-art="${b.art}"></canvas>` : ''}${b.id === 'auto' ? '<canvas data-art="flow"></canvas>' : ''}<span>${esc(b.name)}</span></div>`).join('')}</div>
      <div class="sub" style="margin-top:12px">"Cinematic" changes the scene per tab. Photos: The Metropolitan Museum of Art, Open Access (CC0).</div></div>
    <div class="panel"><h3>Display</h3>
      <div class="set-row"><span>Floating particles</span><button class="switch ${store.get('particles', true) ? 'on' : ''}" data-s="particles"></button></div>
      <div class="set-row"><span>Splash screen</span><button class="switch ${store.get('splash', true) ? 'on' : ''}" data-s="splash"></button></div>
      <div class="set-row"><span>Background dim</span><input type="range" min="0" max="80" value="${store.get('dim', 25)}" id="dim" style="width:160px"></div>
      <div class="set-row"><span>Greeting name</span><input class="txt" style="width:160px;height:36px" id="nm" value="${esc(store.get('name', 'Emis'))}"></div>
      <h3 style="margin-top:20px">Connection</h3>
      <div class="set-row"><span>${API.demo ? '<span class="a">DEMO mode</span> - sample data' : '<span class="g">Connected</span> to your FlowDesk API'}</span>${API.demo ? '' : '<button class="btn" id="disc">Use demo</button>'}</div>
      <div class="sub">To connect, open the desk link FlowDesk sends in Telegram (/desk). It carries the API address and your desk key; the key stays in this browser.</div>
    </div></div>
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
      <div style="display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap"><span class="pill long">▲ LONG</span><span class="pill short">▼ SHORT</span><span class="glow-g big num">+$12.40</span><span class="glow-r big num">-$3.10</span><button class="btn" id="resetTheme" style="margin-left:auto">Reset to Neon</button></div>
    </div>`;
  $$('#bgo canvas').forEach(c => FX.drawArt(c, c.dataset.art, 300, 184));
  $('#bgo').onclick = e => { const o = e.target.closest('.bg-opt'); if (!o) return; store.set('bg', o.dataset.b); $$('#bgo .bg-opt').forEach(x => x.classList.toggle('on', x === o)); App.applyBg('settings'); };
  $$('.switch').forEach(s => s.onclick = () => { const k = s.dataset.s; const nv = !store.get(k, true); store.set(k, nv); s.classList.toggle('on', nv); });
  $('#dim').oninput = e => { store.set('dim', +e.target.value); App.applyDim(); };
  $('#nm').onchange = e => store.set('name', e.target.value.trim() || 'Emis');
  const d = $('#disc'); if (d) d.onclick = () => { API.disconnect(); location.reload(); };
  const refresh = () => { App.applyBg('settings'); $$('#bgo canvas').forEach(c => FX.drawArt(c, c.dataset.art, 300, 184)); };
  $('#pal').onclick = e => { const b = e.target.closest('button[data-p]'); if (!b) return; Theme.save(Object.assign({}, Theme.PALETTES[b.dataset.p], { palette: b.dataset.p })); Views.settings(v); refresh(); };
  $$('input[type=color][data-t]').forEach(i => i.oninput = () => { Theme.save({ [i.dataset.t]: i.value, palette: 'custom' }); $$('#pal button').forEach(x => x.classList.remove('on')); });
  $$('input[type=color][data-t]').forEach(i => i.onchange = refresh);
  $$('input[type=range][data-r]').forEach(i => i.oninput = () => { const k = i.dataset.r; Theme.save({ [k]: +i.value / 100, palette: 'custom' }); $(k === 'a' ? '#aV' : '#glowV').textContent = i.value + '%'; });
  $('#resetTheme').onclick = () => { store.del('theme'); Theme.load(); Theme.apply(); Views.settings(v); refresh(); };
};

/* DEMO mode: deterministic SAMPLE data so the desk can be explored without the API. Never shown as live. */
const INSTRUMENTS = [
  ['EURUSD=X', 'Euro / US Dollar', 'Forex', 1.0975], ['GBPUSD=X', 'British Pound / US Dollar', 'Forex', 1.2840], ['USDJPY=X', 'US Dollar / Japanese Yen', 'Forex', 151.42],
  ['AUDUSD=X', 'Australian Dollar / US Dollar', 'Forex', 0.6610], ['USDCAD=X', 'US Dollar / Canadian Dollar', 'Forex', 1.3920], ['USDCHF=X', 'US Dollar / Swiss Franc', 'Forex', 0.8810],
  ['NZDUSD=X', 'New Zealand Dollar / US Dollar', 'Forex', 0.5980], ['EURGBP=X', 'Euro / British Pound', 'Forex', 0.8547], ['EURJPY=X', 'Euro / Japanese Yen', 'Forex', 166.2],
  ['GBPJPY=X', 'British Pound / Japanese Yen', 'Forex', 194.4], ['AUDJPY=X', 'Australian Dollar / Japanese Yen', 'Forex', 100.1], ['EURCHF=X', 'Euro / Swiss Franc', 'Forex', 0.967],
  ['EURAUD=X', 'Euro / Australian Dollar', 'Forex', 1.66], ['GBPCHF=X', 'British Pound / Swiss Franc', 'Forex', 1.131], ['CADJPY=X', 'Canadian Dollar / Japanese Yen', 'Forex', 108.8],
  ['ES=F', 'E-mini S&P 500', 'Futures', 6812], ['NQ=F', 'E-mini Nasdaq-100', 'Futures', 27240], ['YM=F', 'E-mini Dow', 'Futures', 47310], ['RTY=F', 'E-mini Russell 2000', 'Futures', 2480],
  ['ZN=F', '10-Year T-Note', 'Futures', 112.4], ['ZB=F', '30-Year T-Bond', 'Futures', 117.9], ['6E=F', 'Euro FX Futures', 'Futures', 1.1005],
  ['^GSPC', 'S&P 500 Index', 'Indices', 6790], ['^NDX', 'Nasdaq-100 Index', 'Indices', 27100], ['^DJI', 'Dow Jones Industrial', 'Indices', 47200], ['^GDAXI', 'DAX 40', 'Indices', 24100],
  ['^FTSE', 'FTSE 100', 'Indices', 9620], ['^N225', 'Nikkei 225', 'Indices', 49800], ['^STOXX50E', 'Euro Stoxx 50', 'Indices', 5680], ['^HSI', 'Hang Seng', 'Indices', 26100], ['^VIX', 'CBOE Volatility Index', 'Indices', 17.2],
  ['GC=F', 'Gold Futures', 'Commodities', 3772], ['SI=F', 'Silver Futures', 'Commodities', 46.2], ['CL=F', 'Crude Oil WTI', 'Commodities', 61.8], ['BZ=F', 'Brent Crude', 'Commodities', 65.4],
  ['NG=F', 'Natural Gas', 'Commodities', 4.21], ['HG=F', 'Copper', 'Commodities', 5.02], ['PL=F', 'Platinum', 'Commodities', 1540],
  ['BTC-USD', 'Bitcoin', 'Crypto', 91200], ['ETH-USD', 'Ethereum', 'Crypto', 3050], ['SOL-USD', 'Solana', 'Crypto', 141],
].map(([symbol, name, category, base]) => ({ symbol, name, category, base }));

const DEMO = (() => {
  const now = () => Math.floor(Date.now() / 1000);
  const TF = { '1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400, '1d': 86400 };
  const base = s => (INSTRUMENTS.find(i => i.symbol === s) || { base: 100 }).base;
  const SYMS = ['EURUSD=X', 'NQ=F', 'GC=F', 'ES=F', 'GBPUSD=X', 'CL=F', 'USDJPY=X'];
  const TAGS = ['Liquidity sweep', 'FVG', 'Order block', 'BOS', 'CHoCH', 'Pressure surge', 'Absorption', 'Discount', 'Premium', 'OTE', 'Killzone', 'HTF bias', 'Volume node'];

  function candles(sym, tf = '15m', n = 300) {
    const r = rng(hash(sym + tf)); const step = TF[tf] || 900; const end = Math.floor(now() / step) * step;
    let p = base(sym); const vol = p * (tf === '1d' ? 0.009 : tf === '4h' ? 0.004 : tf === '1h' ? 0.0022 : 0.0011);
    const out = []; let drift = 0;
    for (let i = n - 1; i >= 0; i--) {
      if (i % 40 === 0) drift = (r() - 0.5) * vol * 0.35;
      const o = p; const c = o + drift + (r() - 0.5) * vol * 1.6 + (r() < 0.04 ? (r() - 0.5) * vol * 5 : 0);
      const hi = Math.max(o, c) + r() * vol * 0.8, lo = Math.min(o, c) - r() * vol * 0.8;
      out.push({ time: end - i * step, open: o, high: hi, low: lo, close: c, volume: Math.round(200 + r() * 1800 * (Math.abs(c - o) / vol + 0.3)) });
      p = c;
    }
    // rescale so the last close equals the base (keeps prices realistic)
    const k = base(sym) / out[out.length - 1].close;
    out.forEach(b => { b.open *= k; b.high *= k; b.low *= k; b.close *= k; });
    return out;
  }

  function overlays(cs) {
    const n = cs.length; const fvgs = [], obs = [], st = [];
    for (let i = n - 120; i < n; i++) {
      if (cs[i].low > cs[i - 2].high) fvgs.push({ dir: 'bull', top: cs[i].low, bottom: cs[i - 2].high, time: cs[i - 1].time, filled: false });
      if (cs[i].high < cs[i - 2].low) fvgs.push({ dir: 'bear', top: cs[i - 2].low, bottom: cs[i].high, time: cs[i - 1].time, filled: false });
    }
    const hiI = cs.slice(-80).reduce((a, b, i, arr) => b.high > arr[a].high ? i : a, 0) + n - 80;
    const loI = cs.slice(-80).reduce((a, b, i, arr) => b.low < arr[a].low ? i : a, 0) + n - 80;
    const ob1 = cs[Math.max(0, loI - 1)], ob2 = cs[Math.max(0, hiI - 1)];
    obs.push({ dir: 'bull', top: ob1.high, bottom: ob1.low, time: ob1.time }, { dir: 'bear', top: ob2.high, bottom: ob2.low, time: ob2.time });
    st.push({ type: 'BOS', dir: 'bull', level: cs[n - 60].high, time: cs[n - 52].time, from_time: cs[n - 60].time });
    st.push({ type: 'CHoCH', dir: 'bear', level: cs[n - 30].low, time: cs[n - 24].time, from_time: cs[n - 30].time });
    const day = cs.slice(-96 * 2, -96);
    const liq = day.length ? [{ name: 'PDH', price: Math.max(...day.map(b => b.high)), side: 'buy' }, { name: 'PDL', price: Math.min(...day.map(b => b.low)), side: 'sell' }] : [];
    const lo = Math.min(...cs.slice(-120).map(b => b.low)), hi = Math.max(...cs.slice(-120).map(b => b.high));
    const bins = []; for (let i = 0; i < 40; i++) bins.push({ price: lo + (hi - lo) * (i + .5) / 40, vol: 0 });
    cs.slice(-120).forEach(b => { bins.forEach(x => { if (x.price >= b.low && x.price <= b.high) x.vol += b.volume; }); });
    const poc = bins.reduce((a, b) => b.vol > a.vol ? b : a).price;
    const sessions = [];
    for (let d = 2; d >= 0; d--) {
      const t0 = Math.floor(now() / 86400) * 86400 - d * 86400;
      [['London', 7], ['New York', 12]].forEach(([nm, hr]) => {
        const blk = cs.filter(b => b.time >= t0 + hr * 3600 && b.time < t0 + (hr + 3) * 3600);
        if (blk.length > 1) sessions.push({ name: nm, start: blk[0].time, end: blk[blk.length - 1].time, high: Math.max(...blk.map(b => b.high)), low: Math.min(...blk.map(b => b.low)) });
      });
    }
    const delta = cs.map(b => ({ time: b.time, value: b.volume * ((b.close - b.low) - (b.high - b.close)) / ((b.high - b.low) || 1), surge: 0, absorb: 0 }));
    // sample ProfitPro-style key levels
    const avgR = cs.slice(-120).reduce((a, b) => a + b.high - b.low, 0) / 120;
    const imbalances = [];
    for (let i = n - 110; i < n - 3 && imbalances.length < 3; i += 1) { const b = cs[i]; const body = Math.abs(b.close - b.open);
      if (body > 1.7 * avgR) { imbalances.push({ side: b.close > b.open ? 'buy' : 'sell', top: Math.max(b.open, b.close), bottom: Math.max(b.open, b.close) - body * .35, time: b.time, label: `${3 + (i % 5)}x | ${8 + (i % 17)}` }); i += 12; } }
    const top2 = bins.map((b, i) => ({ ...b, i })).sort((a, b) => b.vol - a.vol).slice(0, 2); const totV = bins.reduce((a, b) => a + b.vol, 0) || 1; const bh = (hi - lo) / 40;
    const hvn_zones = top2.map(b => ({ bottom: b.price - bh * 1.5, top: b.price + bh * 1.5, time: cs[n - 96].time, label: `${Math.round(b.vol * 3 / 1000)}k | ${Math.round(b.vol * 3 / totV * 100)}%` }));
    const heavy_abs = []; for (let i = n - 90; i < n; i += 9) { const b = cs[i]; const up = (i / 9) % 2 > 1; heavy_abs.push({ time: b.time, side: up ? 'trapped_buyers' : 'trapped_sellers', price: up ? b.high : b.low, label: String(40 + (i * 7) % 160), vol_ratio: 1.6 + (i % 5) * .3 }); }
    return { imbalances, hvn_zones, heavy_abs, fvgs: fvgs.slice(-6), order_blocks: obs, structure: st, liquidity: liq, sweeps: [], sessions, profile: { poc, vah: poc + (hi - lo) * .18, val: poc - (hi - lo) * .18, hvn: [], bins }, psych: [], delta };
  }

  function check({ symbol, tf = '15m' }) {
    const sym = symbol; const cs = candles(sym, tf); const last = cs[cs.length - 1].close;
    const atr = cs.slice(-14).reduce((a, b) => a + b.high - b.low, 0) / 14;
    const r = rng(hash(sym + tf + Math.floor(now() / 900)));
    const roll = r(); const decision = roll < 0.42 ? 'LONG' : roll < 0.8 ? 'SHORT' : 'NO TRADE';
    const sgn = decision === 'SHORT' ? -1 : 1; const conf = decision === 'NO TRADE' ? 41 : Math.round(58 + r() * 27);
    const risk = atr * (1.1 + r() * 0.6); const sl = last - sgn * risk;
    const tp1 = last + sgn * risk * (1.3 + r() * .5), tp2 = last + sgn * risk * (2.6 + r() * .9);
    const L = decision !== 'SHORT';
    const reasons = (L ? [
      ['Sell-side liquidity at Asia low was swept and price closed back above it (stop hunt)', 'Liquidity sweep', 15],
      ['HVN Absorption: impulse up (3.1 ATR), pullback into high-volume node, wick absorption on 2.2x volume - continuation toward the prior high', 'HVN Absorption', 22],
      ['Change of character (CHoCH) up through the last lower high', 'CHoCH', 15],
      ['Estimated buying pressure surge: 412% of normal delta on 2.7x volume', 'Pressure surge', 15],
      ['Price is reacting inside a bullish fair value gap', 'FVG', 10],
      ['Price is in the discount half of the range (34%)', 'Discount', 8],
      ['London killzone is active (higher-probability window)', 'Killzone', 5]] : [
      ['Buy-side liquidity at PDH was swept and price closed back below it (stop hunt)', 'Liquidity sweep', 15],
      ['Key Level Absorption Reversal: imbalance level (5x | 19), 2 heavy absorption prints (trapped buyers) and a rejection - New York open', 'Key Level Absorption Reversal', 25],
      ['Break of structure (BOS) down through the last higher low', 'BOS', 15],
      ['Buying absorbed near the highs (2.1x volume, small body, long wick)', 'Absorption', 10],
      ['Price is at a bearish order block', 'Order block', 10],
      ['Price is in the premium half of the range (71%)', 'Premium', 8],
      ['New York AM killzone is active (higher-probability window)', 'Killzone', 5]]).map(([text, tag, points]) => ({ text, tag, points, side: L ? 'long' : 'short' }));
    const ov = overlays(cs);
    const out = {
      ok: true, demo: true, symbol: sym, name: (INSTRUMENTS.find(i => i.symbol === sym) || {}).name || sym, tf, paper: true,
      source: 'DEMO sample data', source_note: 'Sample data for preview only', decision, confluence: conf, price: last,
      winrate: Object.assign(demoWR(L ? 'LONG' : 'SHORT', conf), { setup_stats: { setup: L ? 'HVN Absorption' : 'Key Level Absorption Reversal', n: 11 + conf % 9, win_rate: 52 + conf % 11, avg_r: 0.31, low_sample: true } }),
      sizing: { risk_pct: 20, reason: '20% - short setups scoring 49-69: win 53%, n=42, exp +0.21R', skip: false, risk_amount: 24.87, qty: 1.62, quote_ccy: 'USD', currency: 'EUR', fx_mult: 0.8612 },
      setup: decision === 'NO TRADE' ? null : (L ? 'HVN Absorption' : 'Key Level Absorption Reversal'), setups: decision === 'NO TRADE' ? [] : [{ name: L ? 'HVN Absorption' : 'Key Level Absorption Reversal', side: L ? 'long' : 'short' }],
      scores: { long: L ? conf : 30, short: L ? 30 : conf }, reasons: decision === 'NO TRADE' ? reasons.slice(0, 2) : reasons,
      against: [{ text: 'Higher timeframe (1h) structure is ' + (L ? 'bearish' : 'bullish'), tag: 'HTF bias', points: 15 }],
      warnings: [{ text: 'USD FOMC Meeting Minutes in 5.4 h (high impact)', minutes_away: 325 }],
      atr, killzone: 'London', orderflow_estimated: true, volume_source: 'sample', headlines: [],
      chart: Object.assign({ candles: cs }, ov),
    };
    if (decision !== 'NO TRADE') out.levels = { entry: last, sl, tp1, tp2, rr1: +((tp1 - last) * sgn / risk).toFixed(2), rr2: +((tp2 - last) * sgn / risk).toFixed(2), sl_basis: 'structure', tp1_basis: 'liquidity', tp2_basis: 'liquidity' };
    else out.watch = { bias: 'LONG', sl, tp1, note: 'Not enough confluence - reference levels only, no trade' };
    return out;
  }

  function demoWR(direction, score) {
    const n = 14 + (score % 31); const w = 38 + (score % 17);
    return { status: 'ok', demo: true, direction, band: [score - 10, score + 10], n, low_sample: n < 20, win_rate: w, tp2_rate: Math.round(w * 0.45), avg_r: +((w / 100) * 1.6 - 0.62).toFixed(2), expectancy_r: +((w / 100) * 1.6 - 0.62).toFixed(2), expectancy_usd: +(((w / 100) * 1.6 - 0.62) * 5).toFixed(2), risk_usd: 5, tf: '15m', period_from: Date.now() / 1000 - 86400 * 21, period_to: Date.now() / 1000, method: 'DEMO sample numbers', note: 'Sample data for preview only' };
  }

  let _trades = null;
  function trades() {
    if (_trades) return _trades;
    const r = rng(7); const out = []; let t = now() - 34 * 86400; let id = 1;
    while (t < now() - 3600 * 3) {
      t += 3600 * (2 + r() * 14); const d = new Date(t * 1000); if (d.getUTCDay() === 0 || d.getUTCDay() === 6) continue;
      const sym = SYMS[Math.floor(r() * SYMS.length)]; const side = r() < .55 ? 'LONG' : 'SHORT';
      const win = r() < .5; const R = win ? (r() < .6 ? 1.1 + r() * .6 : 2.2 + r() * .6) : -(r() < .25 ? .1 : 1);
      const risk = 5; const pnl = Math.round(R * risk * 100) / 100; const e = base(sym) * (1 + (r() - .5) * .01);
      const tags = [...new Set([TAGS[Math.floor(r() * TAGS.length)], TAGS[Math.floor(r() * TAGS.length)], TAGS[Math.floor(r() * 4)]])];
      out.push({ id: id++, symbol: sym, tf: '15m', side, entry: e, exit_price: e * (1 + (side === 'LONG' ? 1 : -1) * R * .0012), sl_initial: e * (1 - (side === 'LONG' ? 1 : -1) * .0012),
        tp1: e * (1 + (side === 'LONG' ? 1 : -1) * .0016), tp2: e * (1 + (side === 'LONG' ? 1 : -1) * .003), qty: 1, risk_usd: risk, pnl_usd: pnl, r_multiple: R, risk_pct: 10, risk_reason: '10% - win 52%, n=38 (sample)',
        opened_ts: Math.floor(t), closed_ts: Math.floor(t + 3600 * (0.5 + r() * 5)), status: 'closed', exit_reason: win ? (R > 2 ? 'tp2' : 'trailing stop') : (R > -.5 ? 'breakeven' : 'stop loss'),
        tags, reasons: ['Sample reason: ' + tags.join(', ')] });
    }
    _trades = out.reverse(); return _trades;
  }

  function perf() {
    const tr = trades().slice().reverse(); let eq = 50, peak = eq, mdd = 0; const curve = [{ time: tr[0].opened_ts - 60, value: eq }];
    let w = 0, gw = 0, gl = 0, streak = 0, best = 0;
    tr.forEach(t => { eq += t.pnl_usd; peak = Math.max(peak, eq); mdd = Math.max(mdd, peak - eq); curve.push({ time: t.closed_ts, value: +eq.toFixed(2) });
      if (t.pnl_usd > 0) { w++; gw += t.pnl_usd; streak++; best = Math.max(best, streak) } else { gl -= t.pnl_usd; streak = 0 } });
    const daily = {}; tr.forEach(t => { const d = new Date(t.closed_ts * 1000).toISOString().slice(0, 10); daily[d] = (daily[d] || 0) + t.pnl_usd; });
    const d30 = []; for (let i = 29; i >= 0; i--) { const d = new Date(Date.now() - i * 86400e3).toISOString().slice(0, 10); d30.push({ date: d, pnl: +(daily[d] || 0).toFixed(2) }); }
    const heat = {}; tr.forEach(t => { const d = new Date(t.opened_ts * 1000); const k = ((d.getUTCDay() + 6) % 7) + '-' + d.getUTCHours(); heat[k] = heat[k] || { pnl: 0, n: 0 }; heat[k].pnl += t.pnl_usd; heat[k].n++; });
    const bys = {}; tr.forEach(t => { const b = bys[t.symbol] = bys[t.symbol] || { pnl: 0, n: 0, w: 0 }; b.pnl += t.pnl_usd; b.n++; b.w += t.pnl_usd > 0; });
    Object.values(bys).forEach(b => { b.win_rate = +(100 * b.w / b.n).toFixed(1); b.pnl = +b.pnl.toFixed(2); });
    return { demo: true, trades: tr.length, wins: w, losses: tr.length - w, net: +(eq - 50).toFixed(2), win_rate: +(100 * w / tr.length).toFixed(1),
      profit_factor: +(gw / gl).toFixed(2), avg_win: +(gw / w).toFixed(2), avg_loss: -(gl / (tr.length - w)).toFixed(2), avg_r: 0.62, max_drawdown: +mdd.toFixed(2), max_drawdown_pct: +(100 * mdd / peak).toFixed(2),
      equity_curve: curve, equity_snapshots: [], streak, best_streak: best, balance: +eq.toFixed(2), equity: +(eq + 0.19).toFixed(2), start_balance: 50,
      last_trades: tr.slice(-14).map(t => ({ symbol: t.symbol, side: t.side, pnl: t.pnl_usd, time: t.closed_ts })), daily_30: d30, heatmap: heat, by_symbol: bys };
  }

  function positions() {
    return [
      { id: 91, symbol: 'NQ=F', tf: '15m', side: 'LONG', qty: 0.0011, qty_open: 0.0011, entry: 27198.5, sl: 27152.25, tp1: 27265, tp2: 27340, last_price: 27236, opened_ts: now() - 5400, unrealized: 3.8, realized: 0, tp1_hit: 0, tags: ['Liquidity sweep', 'Order block', 'OTE'], reasons: ['Sample: sell-side liquidity at London low swept'] },
      { id: 92, symbol: 'EURUSD=X', tf: '15m', side: 'SHORT', qty: 410, qty_open: 205, entry: 1.09912, sl: 1.09912, tp1: 1.09790, tp2: 1.09610, last_price: 1.09745, opened_ts: now() - 9800, unrealized: 3.4, realized: 2.5, tp1_hit: 1, tags: ['BOS', 'Premium', 'Pressure surge'], reasons: ['Sample: estimated selling pressure surge'] },
    ];
  }

  function calendar() {
    const t0 = Math.floor(now() / 86400) * 86400; const ev = [];
    const L = [[-1, 13.5, 'USD', 'Core CPI m/m', 'High', '0.3%', '0.3%'], [-1, 9, 'GBP', 'CPI y/y', 'High', '3.6%', '3.8%'], [0, 9, 'EUR', 'German ZEW Economic Sentiment', 'Medium', '38.1', '39.3'],
      [0, 19, 'USD', 'FOMC Meeting Minutes', 'High', '', ''], [0, 15.5, 'USD', 'Crude Oil Inventories', 'Medium', '-1.2M', '0.6M'], [1, 13.5, 'USD', 'Unemployment Claims', 'High', '227K', '232K'],
      [1, 23.5, 'JPY', 'National Core CPI y/y', 'Medium', '3.0%', '2.9%'], [2, 8.5, 'EUR', 'German Flash Manufacturing PMI', 'High', '49.6', '49.6'], [2, 14.75, 'USD', 'Flash Manufacturing PMI', 'High', '52.0', '52.5'], [2, 7, 'GBP', 'Retail Sales m/m', 'High', '0.0%', '0.5%']];
    L.forEach(([d, hr, ccy, title, impact, forecast, previous]) => { const ts = t0 + d * 86400 + hr * 3600; ev.push({ title, ccy, impact, ts, time: new Date(ts * 1000).toISOString(), forecast, previous }); });
    return { ok: true, demo: true, source: 'DEMO sample calendar', events: ev.sort((a, b) => a.ts - b.ts) };
  }
  function news() {
    const H = [['Sample headline: Dollar steadies ahead of FOMC minutes', ['EURUSD=X', 'USDJPY=X', 'GC=F'], ''], ['Sample headline: Nasdaq futures climb as chipmakers rally', ['NQ=F', 'ES=F'], 'up'],
      ['Sample headline: Gold slips from record high as yields rise', ['GC=F'], 'down'], ['Sample headline: Oil drops after surprise inventory build', ['CL=F'], 'down'],
      ['Sample headline: ECB officials signal patience on further cuts', ['EURUSD=X', '^GDAXI'], ''], ['Sample headline: Yen weakens as BoJ keeps rates on hold', ['USDJPY=X'], 'down']];
    return { ok: true, demo: true, source: 'DEMO sample headlines', items: H.map(([title, symbols, tone], i) => ({ title, symbols, tone, source: 'Sample feed', link: '#', ts: now() - i * 1700 - 300 })) };
  }
  function signals() {
    return trades().slice(0, 25).map((t, i) => ({ id: 400 - i, ts: t.opened_ts, symbol: t.symbol, tf: '15m', decision: t.side, confluence: 58 + (i * 7) % 30, win_rate: 40 + (i * 3) % 18, bt_n: 12 + (i * 5) % 40, bt_avg_r: +(((i * 7) % 9) / 20 - 0.15).toFixed(2), risk_pct: [15, 20, 10, 25, 15][i % 5], risk_reason: ['base 15% - low sample (n=14 < 20)', '20% - win 54%, n=41', '10% - negative expectancy', '25% - win 63%, n=27', 'base 15% - win rate still computing'][i % 5], price: t.entry, sl: t.sl_initial, tp1: t.tp1, tp2: t.tp2, rr: 2.6, tags: t.tags, reasons: t.reasons, acted: i % 4 ? 1 : 0, note: i % 4 ? '' : 'high-impact event window' }));
  }
  function session() {
    const pos = positions(); const open = +pos.reduce((a, p) => a + p.unrealized, 0).toFixed(2);
    return { demo: true, paper: true, open_pnl: open, closed_pnl: 6.2, in_trade: pos.length > 0, open_positions: pos.length, net: +(6.2 + open).toFixed(2), trades: 5, wins: 3, losses: 2, win_rate: 60, since: Math.floor(now() / 86400) * 86400 };
  }

  function dashboard() {
    const p = perf();
    return { demo: true, paper: true, balance: p.balance, equity: p.equity, start_balance: 50, today_pnl: 6.2, session: session(), net: p.net, win_rate: p.win_rate, profit_factor: p.profit_factor, trades: p.trades,
      streak: p.streak, best_streak: p.best_streak, last_trades: p.last_trades, daily_30: p.daily_30, heatmap: p.heatmap, open_positions: positions(), status: 'running', heartbeat: now() - 40,
      signals_24h: 9, entries_24h: 3, blocked_24h: 2, daily_limit_hit: false,
      plan: ['Risk 10% per trade', 'Max 4 open positions', 'Stop after -30% day', 'No entries 30 min before high-impact news', 'Min confluence 55/100', 'TP1 closes 50%, stop to breakeven'],
      upcoming_events: calendar().events.filter(e => e.impact === 'High' && e.ts > now()).slice(0, 5), watchlist: SYMS.map(s => ({ symbol: s, tf: '15m' })), source: 'DEMO' };
  }
  const delay = v => new Promise(r => setTimeout(() => r(v), 250 + Math.random() * 300));
  return {
    get(path, params) {
      const m = {
        '/api/check': () => check(params), '/api/winrate': () => demoWR(params.direction || 'LONG', +params.score || 60), '/api/chart': () => check(params), '/api/dashboard': dashboard, '/api/session': session, '/api/performance': perf,
        '/api/positions': () => ({ positions: positions(), paper: true }), '/api/signals': () => ({ signals: signals() }), '/api/journal': () => ({ trades: trades() }),
        '/api/calendar': calendar, '/api/news': news,
        '/api/instruments': () => ({ categories: ['Forex', 'Indices', 'Futures', 'Commodities', 'Crypto'], items: INSTRUMENTS }),
      }[path];
      return delay(m ? m() : {});
    },
  };
})();

/* Candlestick chart with ICT / order-flow overlays (TradingView Lightweight Charts + an overlay canvas). */
const Charts = (() => {
  const TZ = -new Date().getTimezoneOffset() * 60;   // show local time on the axis
  const T = t => t + TZ;

  function create(el, { height } = {}) {
    el.innerHTML = '';
    const chart = LightweightCharts.createChart(el, {
      autoSize: true,
      layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#9CA3AF', fontFamily: 'Inter', fontSize: 11 },
      grid: { vertLines: { color: 'rgba(255,255,255,.035)' }, horzLines: { color: 'rgba(255,255,255,.035)' } },
      rightPriceScale: { borderColor: 'rgba(255,255,255,.06)', scaleMargins: { top: .08, bottom: .22 } },
      timeScale: { borderColor: 'rgba(255,255,255,.06)', timeVisible: true, secondsVisible: false, rightOffset: 8 },
      crosshair: { mode: 0, vertLine: { color: `rgba(${Theme.C},.35)`, labelBackgroundColor: '#0b2a33' }, horzLine: { color: `rgba(${Theme.C},.35)`, labelBackgroundColor: '#0b2a33' } },
      handleScale: { axisPressedMouseMove: true }, handleScroll: { vertTouchDrag: false },
    });
    const candles = chart.addCandlestickSeries({ upColor: Theme.g, downColor: Theme.r, borderUpColor: Theme.g, borderDownColor: Theme.r, wickUpColor: `rgba(${Theme.G},.75)`, wickDownColor: `rgba(${Theme.R},.75)`, priceLineColor: `rgba(${Theme.C},.6)` });
    const delta = chart.addHistogramSeries({ priceScaleId: 'flow', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
    chart.priceScale('flow').applyOptions({ scaleMargins: { top: .82, bottom: 0 }, visible: false });
    const ov = document.createElement('canvas'); ov.className = 'ov'; el.appendChild(ov);
    const st = { chart, candles, delta, ov, el, data: null, opts: {}, lines: [] };
    const redraw = () => requestAnimationFrame(() => drawOverlay(st));
    chart.timeScale().subscribeVisibleLogicalRangeChange(redraw);
    new ResizeObserver(redraw).observe(el);
    st.redraw = redraw;
    return st;
  }

  function idxOf(cs, t) { let lo = 0, hi = cs.length - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (cs[m].time < t) lo = m + 1; else hi = m; } return lo; }

  function set(st, payload, opts = {}) {
    st.data = payload; st.opts = Object.assign({ fvg: true, ob: true, liq: true, vp: true, sess: true, struct: true }, opts);
    const cs = payload.chart?.candles || [];
    st.candles.setData(cs.map(b => ({ time: T(b.time), open: b.open, high: b.high, low: b.low, close: b.close })));
    const dl = payload.chart?.delta || [];
    st.delta.setData(dl.map(d => ({ time: T(d.time), value: Math.abs(d.value), color: d.surge > 0 ? `rgba(${Theme.G},.9)` : d.surge < 0 ? `rgba(${Theme.R},.9)` : d.value >= 0 ? `rgba(${Theme.G},.28)` : `rgba(${Theme.R},.28)` })));
    st.lines.forEach(l => st.candles.removePriceLine(l)); st.lines = [];
    const pr = { price: cs.length ? cs[cs.length - 1].close : 1 };
    const fmt = { type: 'price', precision: dec(pr.price), minMove: Math.pow(10, -dec(pr.price)) };
    st.candles.applyOptions({ priceFormat: fmt });
    const lv = payload.levels;
    const add = (price, color, title, style = 0, w = 2) => price != null && st.lines.push(st.candles.createPriceLine({ price, color, title, lineWidth: w, lineStyle: style, axisLabelVisible: true }));
    if (lv && st.opts.levels !== false) {
      add(lv.entry, Theme.c, 'ENTRY'); add(lv.sl, Theme.r, 'SL'); add(lv.tp1, Theme.g, 'TP1'); add(lv.tp2, Theme.g, 'TP2', 2);
    } else if (payload.watch && st.opts.levels !== false) {
      add(payload.watch.sl, `rgba(${Theme.R},.6)`, 'ref SL', 2, 1); add(payload.watch.tp1, `rgba(${Theme.G},.6)`, 'ref TP', 2, 1);
    }
    const marks = [];
    const seen = new Set();
    (payload.chart?.sweeps || []).forEach(s => { const i = idxOf(cs, s.time); if (!cs[i] || seen.has(i + s.dir)) return; seen.add(i + s.dir); marks.push({ time: T(cs[i].time), position: s.dir === 'bull' ? 'belowBar' : 'aboveBar', color: s.dir === 'bull' ? Theme.g : Theme.r, shape: s.dir === 'bull' ? 'arrowUp' : 'arrowDown', text: 'sweep' }); });
    dl.forEach(d => { if (d.absorb) marks.push({ time: T(d.time), position: d.absorb > 0 ? 'belowBar' : 'aboveBar', color: Theme.c, shape: 'circle', text: 'abs' }); });
    marks.sort((a, b) => a.time - b.time); st.candles.setMarkers(marks);
    if (opts.fit !== false) { const n = cs.length; st.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - (innerWidth < 860 ? 70 : 140)), to: n + 6 }); }
    st.redraw();
  }

  function drawOverlay(st) {
    const { ov, el, data, chart, candles, opts } = st; if (!data) return;
    const d = Math.min(devicePixelRatio || 1, 2); const W = el.clientWidth, H = el.clientHeight;
    ov.width = W * d; ov.height = H * d; ov.style.width = W + 'px'; ov.style.height = H + 'px';
    const x = ov.getContext('2d'); x.scale(d, d); x.clearRect(0, 0, W, H);
    const cs = data.chart?.candles || []; if (!cs.length) return;
    const ts = chart.timeScale(); const plotW = W - (chart.priceScale('right').width() || 60);
    const X = t => { const c = ts.logicalToCoordinate(idxOf(cs, t)); return c == null ? null : c; };
    const Y = p => candles.priceToCoordinate(p);
    x.save(); x.beginPath(); x.rect(0, 0, plotW, H); x.clip();
    x.font = '600 10px Inter';
    const W0 = W;
    const box = (x1, y1, x2, y2, fill, stroke, label, lc) => {
      if (x1 == null || y1 == null || y2 == null) return; const top = Math.min(y1, y2), hh = Math.max(2, Math.abs(y2 - y1));
      x.fillStyle = fill; x.fillRect(x1, top, (x2 ?? plotW) - x1, hh); x.strokeStyle = stroke; x.lineWidth = 1; x.strokeRect(x1 + .5, top + .5, (x2 ?? plotW) - x1, hh);
      if (label) { x.fillStyle = lc || stroke; x.fillText(label, x1 + 4, top + 11); }
    };
    const ch = data.chart || {};
    if (opts.sess) (ch.sessions || []).forEach(s => box(X(s.start), Y(s.high), X(s.end), Y(s.low), 'rgba(110,139,255,.05)', 'rgba(110,139,255,.25)', W < 600 ? '' : s.name, 'rgba(160,180,255,.8)'));
    if (opts.fvg) (ch.fvgs || []).slice(W < 600 ? -3 : -8).forEach(g => box(X(g.time), Y(g.top), null, Y(g.bottom), g.dir === 'bull' ? `rgba(${Theme.G},.08)` : `rgba(${Theme.R},.08)`, g.dir === 'bull' ? `rgba(${Theme.G},.35)` : `rgba(${Theme.R},.35)`, 'FVG'));
    if (opts.ob) (ch.order_blocks || []).slice(W < 600 ? -2 : -6).forEach(o => box(X(o.time), Y(o.top), null, Y(o.bottom), o.dir === 'bull' ? `rgba(${Theme.C},.09)` : 'rgba(245,181,68,.09)', o.dir === 'bull' ? `rgba(${Theme.C},.45)` : 'rgba(245,181,68,.45)', o.dir === 'bull' ? 'Bull OB' : 'Bear OB'));
    const hline = (p, color, label, dash = [4, 4], w = 1) => { const y = Y(p); if (y == null) return; x.setLineDash(dash); x.strokeStyle = color; x.lineWidth = w; x.beginPath(); x.moveTo(0, y); x.lineTo(plotW, y); x.stroke(); x.setLineDash([]); if (label) { x.fillStyle = color; x.textAlign = 'right'; x.fillText(label, plotW - 6, y - 4); x.textAlign = 'left'; } };
    const small = W < 600; const lastPx = cs[cs.length - 1].close;
    const span = Math.max(...cs.slice(-120).map(b => b.high)) - Math.min(...cs.slice(-120).map(b => b.low)) || 1;
    if (opts.liq) {
      const pick = []; (ch.liquidity || []).slice().sort((a, b) => Math.abs(a.price - lastPx) - Math.abs(b.price - lastPx))
        .forEach(l => { if (pick.length < (small ? 4 : 7) && !pick.some(q => Math.abs(q.price - l.price) < span * .02)) pick.push(l); });
      pick.forEach(l => hline(l.price, 'rgba(255,255,255,.32)', '$$$ ' + l.name, [2, 4]));
    }
    if (opts.vp && ch.profile?.poc) {
      hline(ch.profile.poc, 'rgba(245,181,68,.85)', 'POC', [6, 3], 1.4);
      if (ch.profile.vah) hline(ch.profile.vah, 'rgba(245,181,68,.35)', 'VAH', [2, 4]); if (ch.profile.val) hline(ch.profile.val, 'rgba(245,181,68,.35)', 'VAL', [2, 4]);
      const bins = ch.profile.bins || []; const mx = Math.max(...bins.map(b => b.vol), 1);
      bins.forEach(b => { const y = Y(b.price); if (y == null) return; const w = (b.vol / mx) * plotW * .16; x.fillStyle = 'rgba(245,181,68,.10)'; x.fillRect(plotW - w, y - 2, w, 4); });
    }
    if (opts.struct) (ch.structure || []).slice(W < 600 ? -4 : -12).forEach(e => { const x1 = X(e.from_time), x2 = X(e.time), y = Y(e.level); if (x1 == null || x2 == null || y == null) return;
      const c = e.dir === 'bull' ? `rgba(${Theme.G},.75)` : `rgba(${Theme.R},.75)`; x.strokeStyle = c; x.setLineDash([3, 3]); x.beginPath(); x.moveTo(x1, y); x.lineTo(x2, y); x.stroke(); x.setLineDash([]);
      x.fillStyle = c; x.textAlign = 'center'; x.fillText(e.type, (x1 + x2) / 2, e.dir === 'bull' ? y - 4 : y + 12); x.textAlign = 'left'; });
    x.restore();
  }
  return { create, set };
})();

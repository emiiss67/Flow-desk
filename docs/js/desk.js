/* FlowDesk static desk. Sample numbers are used only when no API is saved. */
(function () {
  const TABS = [
    ["check", "Check"],
    ["dashboard", "Dashboard"],
    ["chart", "Chart"],
    ["signals", "Signals"],
    ["positions", "Positions"],
    ["news", "News"],
    ["journal", "Journal"],
    ["performance", "Performance"],
    ["settings", "Settings"],
  ];
  const TIMEFRAMES = ["M5", "M15", "M30", "H1", "H4", "D1"];
  const CATEGORIES = ["all", "forex", "indices", "futures", "commodities", "crypto"];
  const state = {
    tab: "check",
    mode: "demo",
    instruments: [],
    symbol: "EURUSD",
    timeframe: "M15",
    category: "all",
    query: "",
    check: null,
    chart: null,
    dashboard: null,
    signals: null,
    positions: null,
    journal: null,
    performance: null,
    news: null,
    calendar: null,
    busy: false,
    panelError: "",
    panelDetail: "",
    offlineMessage: "",
    chartHandle: null,
    equityFrame: 0,
  };

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  function amount(value) {
    if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
    return Math.abs(Number(value)).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function money(value) {
    if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
    const n = Number(value);
    const abs = amount(n);
    if (n > 0) return "+" + abs;
    if (n < 0) return "−" + abs;
    return abs;
  }

  function tone(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n === 0) return "flat";
    return n > 0 ? "pos" : "neg";
  }

  function instrumentOf(id) {
    return state.instruments.find((item) => item.id === id);
  }

  function formatPrice(symbol, value) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    const inst = instrumentOf(symbol);
    const digits = inst ? inst.digits : Math.abs(value) >= 100 ? 2 : Math.abs(value) >= 10 ? 3 : 5;
    return Number(value).toFixed(digits);
  }

  function motionOff() {
    return localStorage.getItem("fd_motion") === "1"
      || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function samplePill() {
    return state.mode === "demo" ? '<span class="pill sample">Sample</span>' : "";
  }

  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0;
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function sampleCandles() {
    const rand = mulberry32(42);
    let price = 1.078;
    const start = 1762000000;
    const candles = [];
    for (let i = 0; i < 96; i += 1) {
      const pull = Math.sin(i / 7) * 0.0011;
      const o = price;
      const c = Math.max(1.07, price + pull + (rand() - 0.42) * 0.0016);
      const high = Math.max(o, c) + 0.00035 + rand() * 0.0007;
      const low = Math.min(o, c) - 0.00035 - rand() * 0.0007;
      price = c;
      candles.push({ time: start + i * 900, open: o, high, low, close: c, volume: 800 + Math.round(rand() * 1400) });
    }
    return candles;
  }

  function sampleCheck() {
    const candles = sampleCandles();
    const last = candles[candles.length - 1].close;
    const entry = last;
    const stop = last - 0.0048;
    const tp1 = last + 0.0072;
    const tp2 = last + 0.0115;
    return {
      sample: true,
      call: "LONG",
      symbol: "EURUSD",
      display: "Euro / US Dollar",
      timeframe: "M15",
      confidence: 64,
      confidence_note: "Sample score for the layout. Not a probability and not a live calculation.",
      hypothetical: false,
      blocked_by_event: false,
      entry, stop_loss: stop, take_profit_1: tp1, take_profit_2: tp2,
      risk_reward_1: 1.5,
      risk_reward_2: 2.44,
      confluences: ["Structure", "FVG", "Discount"],
      reasons: [
        { tag: "Sample", side: "info", points: 0, text: "Sample confluence, not a calculation from a feed. Connect the desk API to run a real check." },
        { tag: "Structure", side: "long", points: 18, text: "Sample: M15 structure is drawn as bullish so the card has something to show." },
        { tag: "FVG", side: "long", points: 10, text: "Sample: a bullish fair value gap is painted on the chart. It is not detected from live candles." },
        { tag: "Order flow", side: "info", points: 0, text: "Sample order-flow estimate. This is not tick footprint and not a reading of the current market." },
      ],
      warnings: ["Sample warning: a high-impact USD event would be listed here when the calendar feed is connected."],
      levels_basis: {
        stop: "Sample stop, placed under the sample swing so the chart has a line. Not a computed level.",
        tp1: "Sample TP1 at 1.5R of that sample stop.",
        tp2: "Sample TP2.",
      },
      order_flow: {
        available: true,
        kind: "estimate",
        note: "Sample estimate. Not OHLCV from a feed and not a footprint.",
        cumulative_delta: null,
        delta_ratio: null,
        poc: last - 0.0004,
      },
      data: { source: "Sample", delay: "No market data is loaded in demo mode.", as_of: null },
      candles,
      overlays: {
        fvgs: [{ direction: "bullish", bottom: last - 0.0032, top: last - 0.0016, time: candles[70].time, time_end: candles[95].time }],
        order_blocks: [{ direction: "bullish", low: last - 0.0055, high: last - 0.0038, time: candles[62].time, time_end: candles[95].time }],
        liquidity: [{ price: last - 0.006, label: "sample swing low" }],
        poc: last - 0.0022,
      },
    };
  }

  function sampleEquity() {
    const rand = mulberry32(7);
    let equity = 10000;
    const points = [];
    for (let i = 0; i < 48; i += 1) {
      equity += 40 + rand() * 180 - (i % 11 === 0 ? 260 : 0);
      points.push({ t: "sample-" + i, equity: Math.round(equity * 100) / 100 });
    }
    return points;
  }

  function sampleDashboard() {
    return {
      sample: true,
      net_pnl: 4280.5,
      unrealized: 120,
      open_positions: 1,
      win_rate: 61.4,
      profit_factor: 1.86,
      no_losses: false,
      daily_realized: 140,
      daily_loss_limit: 300,
      daily_loss_used_pct: 0,
      status_today: "Clean",
      balance: 14280.5,
      max_drawdown: 640,
      signals_today: 4,
      trades_today: 1,
      streak: ["W", "W", "L", "W", "W", "W", "L", "W"],
      last_trades: [
        { symbol: "EURUSD", side: "long", pnl: 220, closed_at: "sample" },
        { symbol: "ES", side: "short", pnl: -80, closed_at: "sample" },
        { symbol: "XAUUSD", side: "long", pnl: 140, closed_at: "sample" },
        { symbol: "GBPUSD", side: "long", pnl: 60, closed_at: "sample" },
      ],
    };
  }

  async function api(path) {
    const base = (localStorage.getItem("fd_api") || "").replace(/\/$/, "");
    const key = localStorage.getItem("fd_key") || "";
    if (!base || !key) {
      const error = new Error("demo");
      error.demo = true;
      throw error;
    }
    const join = base + path + (path.includes("?") ? "&" : "?") + "key=" + encodeURIComponent(key);
    let response;
    try {
      response = await fetch(join, { headers: { "X-FlowDesk-Key": key } });
    } catch (err) {
      const error = new Error("API unreachable");
      error.offline = true;
      throw error;
    }
    const data = await response.json().catch(() => ({}));
    if (data.error === "data unavailable" || response.status === 503) {
      const error = new Error("data unavailable");
      error.detail = data.detail || "";
      error.unavailable = true;
      throw error;
    }
    if (response.status === 401) throw new Error("Desk key was rejected");
    if (!response.ok) {
      const error = new Error(typeof data.detail === "string" ? data.detail : (data.error || "Request failed"));
      error.detail = data.detail || "";
      throw error;
    }
    return data;
  }

  function consumeHash() {
    const raw = location.hash.replace(/^#/, "");
    if (!raw) return;
    if (raw.includes("=")) {
      const params = new URLSearchParams(raw);
      if (params.get("api")) localStorage.setItem("fd_api", params.get("api").replace(/\/$/, ""));
      if (params.get("key")) localStorage.setItem("fd_key", params.get("key"));
      const tab = params.get("tab");
      const next = TABS.some(([id]) => id === tab) ? tab : "check";
      history.replaceState(null, "", "#" + next);
      state.tab = next;
      return;
    }
    if (TABS.some(([id]) => id === raw)) state.tab = raw;
  }

  function applyBackground() {
    const key = localStorage.getItem("fd_bg") || "statue";
    const scene = document.getElementById("scene");
    scene.style.backgroundImage = 'url("assets/bg-' + key + '.svg")';
    document.body.classList.toggle("reduce", motionOff());
  }

  function startDust() {
    const canvas = document.getElementById("dust");
    const ctx = canvas.getContext("2d");
    const dots = Array.from({ length: 48 }, () => spawn());
    function spawn() {
      return {
        x: Math.random(),
        y: Math.random(),
        r: 0.6 + Math.random() * 1.4,
        s: 0.00015 + Math.random() * 0.00035,
        a: 0.15 + Math.random() * 0.45,
      };
    }
    function frame() {
      const w = canvas.width = window.innerWidth;
      const h = canvas.height = window.innerHeight;
      ctx.clearRect(0, 0, w, h);
      for (const dot of dots) {
        if (!motionOff()) dot.y -= dot.s;
        if (dot.y < 0) dot.y = 1;
        ctx.fillStyle = "rgba(255,255,255," + dot.a + ")";
        ctx.beginPath();
        ctx.arc(dot.x * w, dot.y * h, dot.r, 0, Math.PI * 2);
        ctx.fill();
      }
      if (!motionOff()) requestAnimationFrame(frame);
    }
    frame();
  }

  function stopEquity() {
    if (state.equityFrame) cancelAnimationFrame(state.equityFrame);
    state.equityFrame = 0;
  }

  function destroyChart() {
    if (state.chartHandle && state.chartHandle.remove) state.chartHandle.remove();
    state.chartHandle = null;
  }

  function drawEquity(canvas, points) {
    stopEquity();
    const ctx = canvas.getContext("2d");
    const values = (points || []).map((point) => Number(point.equity)).filter((n) => Number.isFinite(n));
    function paint(tick) {
      const width = canvas.clientWidth || 600;
      const height = canvas.clientHeight || 280;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(width * ratio);
      canvas.height = Math.floor(height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, width, height);
      if (!values.length) {
        ctx.fillStyle = "#9CA3AF";
        ctx.font = "14px Outfit, sans-serif";
        ctx.fillText("No equity points yet.", 16, 32);
        return;
      }
      if (values.length === 1) values.push(values[0]);
      const min = Math.min(...values);
      const max = Math.max(...values);
      const span = max - min || 1;
      const pad = 18;
      const coords = values.map((value, index) => {
        const x = pad + (index / (values.length - 1)) * (width - pad * 2);
        const y = pad + (1 - (value - min) / span) * (height - pad * 2);
        return { x, y };
      });
      function yAt(x) {
        for (let i = 1; i < coords.length; i += 1) {
          if (x <= coords[i].x) {
            const left = coords[i - 1];
            const right = coords[i];
            const t = (x - left.x) / (right.x - left.x || 1);
            return left.y + (right.y - left.y) * t;
          }
        }
        return coords[coords.length - 1].y;
      }
      const gradient = ctx.createLinearGradient(0, pad, 0, height);
      gradient.addColorStop(0, "rgba(0,255,102,0.28)");
      gradient.addColorStop(1, "rgba(0,255,102,0)");
      ctx.beginPath();
      ctx.moveTo(coords[0].x, coords[0].y);
      coords.forEach((point) => ctx.lineTo(point.x, point.y));
      ctx.lineTo(coords[coords.length - 1].x, height);
      ctx.lineTo(coords[0].x, height);
      ctx.closePath();
      ctx.fillStyle = gradient;
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(coords[0].x, coords[0].y);
      coords.forEach((point) => ctx.lineTo(point.x, point.y));
      ctx.strokeStyle = "#00FF66";
      ctx.lineWidth = 2;
      ctx.shadowColor = "rgba(0,255,102,0.8)";
      ctx.shadowBlur = 12;
      ctx.stroke();
      ctx.shadowBlur = 0;
      const count = motionOff() ? 0 : 70;
      for (let i = 0; i < count; i += 1) {
        const seed = (i * 97 + Math.floor(tick / 3)) % 1000;
        const x = pad + ((seed * 13) % 1000) / 1000 * (width - pad * 2);
        const top = yAt(x);
        const depth = ((seed * 7 + tick) % 100) / 100;
        const y = top + 8 + depth * (height - top - 8);
        const alpha = 0.15 + (1 - depth) * 0.55;
        ctx.fillStyle = "rgba(0,255,102," + alpha + ")";
        ctx.beginPath();
        ctx.arc(x, y, 1.2, 0, Math.PI * 2);
        ctx.fill();
      }
      if (!motionOff()) state.equityFrame = requestAnimationFrame(paint);
    }
    paint(0);
  }

  function uniqCandles(candles) {
    const map = new Map();
    (candles || []).forEach((candle) => {
      if (candle && Number.isFinite(candle.time)) map.set(candle.time, candle);
    });
    return [...map.values()].sort((a, b) => a.time - b.time);
  }

  function mountCandle(host, candles, extras) {
    destroyChart();
    host.innerHTML = "";
    const rows = uniqCandles(candles);
    if (!rows.length || !window.LightweightCharts) {
      host.textContent = rows.length ? "Chart library failed to load." : "No candles.";
      return;
    }
    try {
      const chart = LightweightCharts.createChart(host, {
        autoSize: true,
        layout: { background: { color: "rgba(8,10,14,0.2)" }, textColor: "#9CA3AF" },
        grid: {
          vertLines: { color: "rgba(255,255,255,0.04)" },
          horzLines: { color: "rgba(255,255,255,0.04)" },
        },
        rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
        timeScale: { borderColor: "rgba(255,255,255,0.08)", timeVisible: true, secondsVisible: false },
      });
      const series = chart.addCandlestickSeries({
        upColor: "#00FF66",
        downColor: "#EF4444",
        borderVisible: false,
        wickUpColor: "#00FF66",
        wickDownColor: "#EF4444",
      });
      series.setData(rows.map((candle) => ({
        time: candle.time, open: candle.open, high: candle.high, low: candle.low, close: candle.close,
      })));
      (extras.lines || []).forEach((line) => {
        if (line.price == null || Number.isNaN(Number(line.price))) return;
        series.createPriceLine({
          price: Number(line.price),
          color: line.color,
          lineWidth: 1,
          lineStyle: line.dashed ? 2 : 0,
          axisLabelVisible: true,
          title: line.title,
        });
      });
      chart.timeScale().fitContent();
      state.chartHandle = chart;
      const svg = host.parentElement.querySelector(".zone-layer");
      const paint = () => paintZones(svg, chart, series, extras.overlays || {});
      chart.timeScale().subscribeVisibleLogicalRangeChange(paint);
      setTimeout(paint, 50);
    } catch (err) {
      host.textContent = "Chart could not be drawn.";
    }
  }

  function paintZones(svg, chart, series, overlays) {
    if (!svg) return;
    const ns = "http://www.w3.org/2000/svg";
    const width = svg.clientWidth || 100;
    const height = svg.clientHeight || 100;
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.replaceChildren();
    const zones = []
      .concat((overlays.fvgs || []).map((zone) => ({
        top: zone.top, bottom: zone.bottom, time: zone.time, time_end: zone.time_end,
        color: zone.direction === "bullish" ? "rgba(0,255,102,0.16)" : "rgba(239,68,68,0.16)",
      })))
      .concat((overlays.order_blocks || []).map((zone) => ({
        top: zone.high, bottom: zone.low, time: zone.time, time_end: zone.time_end,
        color: "rgba(0,212,255,0.14)",
      })));
    zones.slice(-8).forEach((zone) => {
      const y1 = series.priceToCoordinate(zone.top);
      const y2 = series.priceToCoordinate(zone.bottom);
      if (y1 == null || y2 == null) return;
      let x1 = chart.timeScale().timeToCoordinate(zone.time);
      let x2 = chart.timeScale().timeToCoordinate(zone.time_end);
      if (x1 == null) x1 = 0;
      if (x2 == null) x2 = width;
      const rect = document.createElementNS(ns, "rect");
      rect.setAttribute("x", String(Math.min(x1, x2)));
      rect.setAttribute("y", String(Math.min(y1, y2)));
      rect.setAttribute("width", String(Math.max(6, Math.abs(x2 - x1))));
      rect.setAttribute("height", String(Math.max(2, Math.abs(y2 - y1))));
      rect.setAttribute("fill", zone.color);
      svg.appendChild(rect);
    });
  }

  function filtered() {
    const q = state.query.trim().toLowerCase();
    return state.instruments.filter((item) => {
      if (state.category !== "all" && item.category !== state.category) return false;
      if (!q) return true;
      const blob = [item.id, item.name, item.yahoo, ...(item.aliases || [])].join(" ").toLowerCase();
      return blob.includes(q);
    }).slice(0, 40);
  }

  function pickerRows() {
    const rows = filtered().map((item) => (
      '<button type="button" class="result-row' + (item.id === state.symbol ? " on" : "") + '" data-symbol="' + esc(item.id) + '">'
      + "<b>" + esc(item.id) + "</b> " + esc(item.name)
      + "<small>" + esc(item.category) + " · " + esc(item.yahoo) + "</small></button>"
    )).join("");
    const q = state.query.trim();
    const known = state.instruments.some((item) => item.id.toLowerCase() === q.toLowerCase() || item.yahoo.toLowerCase() === q.toLowerCase());
    const custom = q && !known && /^[A-Za-z0-9\^=.\-]{1,24}$/.test(q)
      ? '<button type="button" class="result-row" data-symbol="' + esc(q) + '">Use Yahoo ticker <b>' + esc(q) + "</b><small>Sent to the API as typed. Unknown spread.</small></button>"
      : "";
    return rows + custom || '<p class="small muted">No match in the catalog.</p>';
  }

  function picker() {
    return '<section class="glass pad">'
      + '<p class="kicker">Instrument</p>'
      + '<input class="search" id="q" placeholder="Search EURUSD, ES, gold, or a Yahoo ticker" value="' + esc(state.query) + '">'
      + '<div class="cats">' + CATEGORIES.map((cat) => (
        '<button type="button" data-cat="' + cat + '" class="' + (state.category === cat ? "on" : "") + '">' + esc(cat) + "</button>"
      )).join("") + "</div>"
      + '<div class="results" id="picker-results">' + pickerRows() + "</div>"
      + '<p class="kicker" style="margin-top:14px">Timeframe</p>'
      + '<div class="tfs">' + TIMEFRAMES.map((tf) => (
        '<button type="button" data-tf="' + tf + '" class="' + (state.timeframe === tf ? "on" : "") + '">' + tf + "</button>"
      )).join("") + "</div>"
      + '<p class="small muted">Selected <b>' + esc(state.symbol) + "</b> · " + esc(state.timeframe) + "</p>"
      + "</section>";
  }

  function unavailable(detail) {
    return '<section class="glass unavailable"><strong>data unavailable</strong><p class="muted">'
      + esc(detail || "The feed did not return this.") + "</p></section>";
  }

  function chartBox() {
    return '<div class="chart-box"><div class="lw" id="candle-host"></div><svg class="zone-layer"></svg></div>';
  }

  function levelLines(result) {
    if (!result || result.entry == null) return [];
    const ref = result.call === "NO TRADE" || result.hypothetical;
    return [
      { price: result.entry, color: "#00D4FF", title: ref ? "Ref" : "Entry" },
      { price: result.stop_loss, color: "#EF4444", title: "SL" },
      { price: result.take_profit_1, color: "#00FF66", title: "TP1" },
      { price: result.take_profit_2, color: "#9CA3AF", title: "TP2" },
      { price: result.overlays && result.overlays.poc, color: "#00D4FF", title: "POC est", dashed: true },
    ];
  }

  function renderCheck() {
    let body = "";
    if (state.panelError === "data unavailable") body = unavailable(state.panelDetail);
    else if (state.panelError) body = '<section class="glass unavailable"><strong>' + esc(state.panelError) + "</strong></section>";
    else if (!state.check) {
      body = '<section class="glass pad"><p class="kicker">Check</p><p>Pick an instrument and run a check. This does not place a trade.</p></section>';
    } else {
      const result = state.check;
      const callClass = result.call === "LONG" ? "call-long" : result.call === "SHORT" ? "call-short" : "call-flat";
      const flow = result.order_flow || {};
      const flowBadge = flow.available
        ? '<span class="pill est">' + (flow.kind === "estimate" ? "Order flow estimate" : esc(flow.kind || "Order flow")) + "</span>"
        : '<span class="pill">Order flow data unavailable</span>';
      body = '<section class="glass pad">'
        + '<div class="split"><p class="kicker">' + esc(result.display || result.symbol) + " · " + esc(result.timeframe) + "</p>" + samplePill() + "</div>"
        + '<div class="big ' + callClass + '">' + esc(result.call) + "</div>"
        + "<p>Score <b>" + esc(result.confidence) + "</b> <span class='muted'>" + esc(result.confidence_note || "") + "</span></p>"
        + "<p>" + (result.confluences || []).map((tag) => '<span class="pill">' + esc(tag) + "</span> ").join("") + flowBadge + "</p>"
        + (result.call === "NO TRADE" ? '<p class="small muted">Reference levels, not a trade.</p>' : "")
        + (result.blocked_by_event && result.direction_if_clear ? '<p class="warn">Blocked by the calendar. Setup underneath: ' + esc(result.direction_if_clear) + ".</p>" : "")
        + '<div class="levels">'
        + levelTile("Entry", formatPrice(result.symbol, result.entry))
        + levelTile("Stop", formatPrice(result.symbol, result.stop_loss))
        + levelTile("TP1", formatPrice(result.symbol, result.take_profit_1) + " · " + esc(result.risk_reward_1 ?? "—") + "R")
        + levelTile("TP2", formatPrice(result.symbol, result.take_profit_2) + " · " + esc(result.risk_reward_2 ?? "—") + "R")
        + "</div>"
        + chartBox()
        + '<div class="reasons">' + (result.reasons || []).map((reason) => (
          '<div class="reason"><span class="pill ' + esc(reason.side || "") + '">' + esc(reason.tag) + "</span> " + esc(reason.text) + "</div>"
        )).join("") + "</div>"
        + (result.warnings || []).map((warning) => '<div class="warn">' + esc(warning) + "</div>").join("")
        + (result.levels_basis ? '<p class="small muted">' + esc(result.levels_basis.stop || "") + "</p>" : "")
        + '<p class="small muted">' + esc((result.data && result.data.source) || "") + " · " + esc((result.data && result.data.delay) || "") + "</p>"
        + (flow.available ? '<p class="small muted">' + esc(flow.note || "") + "</p>" : '<p class="small muted">Order flow: data unavailable. ' + esc(flow.reason || "") + "</p>")
        + "</section>";
    }
    return '<div class="layout-2">' + picker()
      + '<div><button class="check-btn" id="go" type="button"' + (state.busy ? " disabled" : "") + ">"
      + (state.busy ? "Checking" : "Check") + "</button>" + body + "</div></div>";
  }

  function levelTile(label, value) {
    return '<div class="level"><span class="kicker">' + esc(label) + "</span><b>" + esc(value) + "</b></div>";
  }

  function renderDashboard() {
    if (state.mode === "offline") return unavailable(state.offlineMessage);
    if (state.panelError === "data unavailable") return unavailable(state.panelDetail);
    const data = state.mode === "demo" ? sampleDashboard() : (state.dashboard || {});
    const streak = data.streak || [];
    const trades = data.last_trades || [];
    const maxBar = Math.max(1, ...trades.map((trade) => Math.abs(Number(trade.pnl) || 0)));
    return '<section class="dash">'
      + '<p class="welcome">Welcome back' + (data.owner_name ? ", <b>" + esc(data.owner_name) + "</b>" : "") + '. <span class="muted">Paper desk. No live orders.</span> ' + samplePill() + "</p>"
      + '<div class="hero"><div class="glass hero-num"><p class="kicker">Net P&L</p><div class="big ' + tone(data.net_pnl) + '">' + esc(money(data.net_pnl)) + '</div><p class="muted">Balance ' + esc(amount(data.balance)) + " · open " + esc(money(data.unrealized)) + "</p></div>"
      + '<div class="stat-col"><div class="glass stat"><p class="kicker">Today</p><strong>' + esc(data.status_today || "—") + '</strong><p class="small muted">Daily loss used ' + esc(data.daily_loss_used_pct == null ? "—" : Number(data.daily_loss_used_pct).toFixed(0) + "%") + "</p></div>"
      + '<div class="glass stat"><p class="kicker">Win rate</p><strong>' + (data.win_rate == null ? "—" : esc(Number(data.win_rate).toFixed(1) + "%")) + "</strong></div></div></div>"
      + '<div class="cards">'
      + stat("Open", data.open_positions ?? "—")
      + stat("Profit factor", data.profit_factor == null ? (data.no_losses ? "no losses" : "—") : Number(data.profit_factor).toFixed(2))
      + stat("Drawdown", amount(data.max_drawdown))
      + stat("Signals today", data.signals_today ?? "—")
      + "</div>"
      + '<div class="grid" style="grid-template-columns: 1fr 1fr"><div class="glass pad"><p class="kicker">Streak</p><div class="streak">'
      + (streak.length ? streak.map((item) => '<span class="tick ' + esc(item) + '"></span>').join("") : '<span class="muted">No closed trades yet.</span>')
      + '</div></div><div class="glass pad"><p class="kicker">Last trades</p><div class="bars">'
      + (trades.length ? trades.slice(0, 12).map((trade) => {
        const h = Math.max(8, Math.round((Math.abs(Number(trade.pnl) || 0) / maxBar) * 88));
        const cls = Number(trade.pnl) >= 0 ? "up" : "down";
        return '<div class="bar ' + cls + '" style="height:' + h + 'px" title="' + esc(trade.symbol) + '"></div>';
      }).join("") : '<span class="muted">No closed trades yet.</span>')
      + "</div></div></div></section>";
  }

  function stat(label, value) {
    return '<div class="glass stat"><p class="kicker">' + esc(label) + "</p><strong>" + esc(value) + "</strong></div>";
  }

  function renderChart() {
    if (state.panelError === "data unavailable") {
      return '<div class="layout-2">' + picker() + unavailable(state.panelDetail) + "</div>";
    }
    const payload = state.mode === "demo" ? sampleCheck() : state.chart;
    const note = state.mode === "demo"
      ? "Sample candles and sample ICT boxes. Not a live chart."
      : ((payload && payload.data && payload.data.delay) || "");
    return '<div class="layout-2">' + picker() + '<section class="glass pad"><div class="split"><p class="kicker">Live chart · ' + esc(state.symbol) + " " + esc(state.timeframe) + "</p>" + samplePill() + "</div>"
      + chartBox()
      + '<p class="small muted">' + esc(note) + "</p>"
      + '<p class="small muted">Green boxes are fair value gaps, cyan boxes are order blocks, the dashed line is an estimated POC. Session and swing prices are the other lines when a live chart is loaded.</p>'
      + "</section></div>";
  }

  function renderSignals() {
    if (state.panelError) return unavailable(state.panelDetail || state.panelError);
    const rows = state.mode === "demo"
      ? [{ ts: "sample", symbol: "EURUSD", timeframe: "M15", call: "LONG", confidence: 64, source: "sample", acted: false, reasons: [{ text: "Sample signal. Not from the scanner." }] }]
      : ((state.signals && state.signals.signals) || []);
    if (!rows.length) return '<section class="glass pad"><p class="kicker">Signals</p><p>No signals journaled yet.</p></section>';
    return '<section class="list">' + rows.map((row) => (
      '<article class="glass list-card"><div class="split"><p class="kicker">' + esc(row.source) + " · " + esc(row.ts) + "</p>" + samplePill() + "</div>"
      + "<h3><span class='pill " + (row.call === "LONG" ? "long" : row.call === "SHORT" ? "short" : "") + "'>" + esc(row.call) + "</span> "
      + esc(row.symbol) + " " + esc(row.timeframe) + " · " + esc(row.confidence) + "</h3>"
      + "<p class='small'>" + esc((row.reasons && row.reasons[0] && row.reasons[0].text) || "") + "</p></article>"
    )).join("") + "</section>";
  }

  function renderPositions() {
    if (state.panelError) return unavailable(state.panelDetail || state.panelError);
    const rows = state.mode === "demo"
      ? [{ symbol: "EURUSD", side: "long", qty: 50000, entry: 1.0852, sl: 1.0821, tp1: 1.0894, unrealized: 120, note: "Sample position. Not in the paper book." }]
      : ((state.positions && state.positions.positions) || []);
    if (!rows.length) return '<section class="glass pad"><p class="kicker">Positions</p><p>No open paper positions. Close a position from Telegram with /close.</p></section>';
    return '<section class="glass pad"><div class="split"><p class="kicker">Open paper positions</p>' + samplePill() + '</div><table class="table"><thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Stop</th><th>TP1</th><th>Open P&L</th></tr></thead><tbody>'
      + rows.map((row) => "<tr><td>" + esc(row.symbol) + "</td><td>" + esc(row.side) + "</td><td>" + esc(formatPrice(row.symbol, row.entry))
        + "</td><td>" + esc(formatPrice(row.symbol, row.sl)) + "</td><td>" + esc(formatPrice(row.symbol, row.tp1))
        + "</td><td class='" + tone(row.unrealized) + "'>" + esc(money(row.unrealized)) + "</td></tr>").join("")
      + "</tbody></table><p class='small muted'>The desk cannot close a position. Use Telegram /close.</p></section>";
  }

  function renderNews() {
    if (state.mode !== "demo" && state.panelError) return unavailable(state.panelDetail || state.panelError);
    const news = state.mode === "demo"
      ? { available: true, items: [
        { title: "Sample headline — not from a feed: central bank speakers on the dollar", source: "sample", matches: ["EURUSD"] },
        { title: "Sample headline — not from a feed: equity index futures ahead of a data print", source: "sample", matches: ["ES"] },
      ] }
      : (state.news || { available: false, error: "data unavailable" });
    const calendar = state.mode === "demo"
      ? { available: true, events: [
        { impact: "High", currency: "USD", title: "Sample CPI", time: "sample", affects: ["EURUSD", "ES"] },
        { impact: "High", currency: "USD", title: "Sample FOMC", time: "sample", affects: ["EURUSD", "XAUUSD"] },
      ] }
      : (state.calendar || { available: false, error: "data unavailable" });
    const newsHtml = news.available === false
      ? unavailable(news.detail || "data unavailable")
      : (news.items || []).slice(0, 12).map((item) => (
        '<article class="glass list-card"><div class="split"><p class="kicker">' + esc(item.source) + "</p>" + samplePill() + "</div><h3>"
        + (item.link ? '<a href="' + esc(item.link) + '" target="_blank" rel="noreferrer">' + esc(item.title) + "</a>" : esc(item.title))
        + "</h3><p>" + (item.matches || []).map((id) => '<span class="pill">' + esc(id) + "</span> ").join("") + "</p></article>"
      )).join("") || '<section class="glass pad">No headlines.</section>';
    const calHtml = calendar.available === false
      ? unavailable(calendar.detail || "data unavailable")
      : '<section class="glass pad"><div class="split"><p class="kicker">Calendar</p>' + samplePill() + "</div>"
        + (calendar.stale ? '<p class="warn">Cached calendar. The fresh fetch failed.</p>' : "")
        + "<table class='table'><tbody>" + (calendar.events || []).slice(0, 20).map((event) => (
          "<tr><td>" + esc(event.impact) + "</td><td>" + esc(event.currency) + "</td><td>" + esc(event.title)
          + "<small class='muted' style='display:block'>" + esc(event.time) + "</small></td><td>" + esc((event.affects || []).slice(0, 6).join(", ")) + "</td></tr>"
        )).join("") + "</tbody></table></section>";
    return '<div class="grid">' + calHtml + newsHtml + "</div>";
  }

  function renderJournal() {
    if (state.panelError && state.mode !== "demo") return unavailable(state.panelDetail || state.panelError);
    const rows = state.mode === "demo"
      ? [{ ts: "sample", symbol: "EURUSD", call: "LONG", confidence: 64, source: "sample", reasons: [{ text: "Sample journal row. The real journal is every check and scanner pass." }], trade: null }]
      : ((state.journal && state.journal.entries) || []);
    if (!rows.length) return '<section class="glass pad"><p class="kicker">Journal</p><p>No journal rows yet.</p></section>';
    return '<section class="list">' + rows.map((row) => (
      '<article class="glass list-card"><div class="split"><p class="kicker">' + esc(row.ts) + " · " + esc(row.source) + "</p>" + samplePill() + "</div>"
      + "<h3>" + esc(row.call) + " " + esc(row.symbol) + " · " + esc(row.confidence) + "</h3>"
      + "<p class='small'>" + esc((row.reasons && row.reasons[0] && row.reasons[0].text) || "") + "</p>"
      + (row.trade ? "<p class='small'>Paper trade " + esc(row.trade.status) + " · P&L " + esc(money(row.trade.pnl)) + "</p>" : "")
      + "</article>"
    )).join("") + "</section>";
  }

  function renderPerformance() {
    if (state.panelError && state.mode !== "demo") return unavailable(state.panelDetail || state.panelError);
    const data = state.mode === "demo"
      ? { sample: true, net: 4280.5, win_rate: 61.4, profit_factor: 1.86, max_drawdown: 640, max_drawdown_pct: 4.4, trades: 18, wins: 11, losses: 7, avg_r: 0.42, equity: sampleEquity(), by_weekday: [
        { day: "Mon", pnl: 400, trades: 3 }, { day: "Tue", pnl: -120, trades: 2 }, { day: "Wed", pnl: 860, trades: 4 },
        { day: "Thu", pnl: 220, trades: 3 }, { day: "Fri", pnl: 140, trades: 2 }, { day: "Sat", pnl: 0, trades: 0 }, { day: "Sun", pnl: 0, trades: 0 },
      ], streak: ["W", "L", "W", "W", "W", "L", "W", "W"], last_trades: sampleDashboard().last_trades }
      : (state.performance || { equity: [], by_weekday: [], streak: [], last_trades: [] });
    const pf = data.profit_factor == null ? (data.no_losses ? "no losses" : "—") : Number(data.profit_factor).toFixed(2);
    const gauge = data.profit_factor == null ? 0 : Math.max(0, Math.min(1, Number(data.profit_factor) / 3));
    const days = data.by_weekday || [];
    const max = Math.max(1, ...days.map((day) => Math.abs(day.pnl || 0)));
    return '<section class="dash"><div class="split"><p class="kicker">Performance</p>' + samplePill() + "</div>"
      + '<div class="perf-top"><div class="glass hero-num"><p class="kicker">Win rate</p><div class="big">' + (data.win_rate == null ? "—" : esc(Number(data.win_rate).toFixed(1) + "%")) + '</div><p class="muted">' + esc(data.trades || 0) + " closed · avg R " + (data.avg_r == null ? "—" : esc(Number(data.avg_r).toFixed(2))) + "</p></div>"
      + '<div class="glass stat" style="text-align:center"><p class="kicker">Profit factor</p><svg class="gauge" viewBox="0 0 120 70"><path d="M10 60 A50 50 0 0 1 110 60" fill="none" stroke="rgba(255,255,255,0.12)" stroke-width="8" stroke-linecap="round"/><path d="M10 60 A50 50 0 0 1 110 60" fill="none" stroke="#00FF66" stroke-width="8" stroke-linecap="round" stroke-dasharray="' + (157 * gauge).toFixed(1) + ' 157" style="filter:drop-shadow(0 0 6px #00FF66)"/></svg><strong>' + esc(pf) + "</strong></div>"
      + '<div class="glass stat"><p class="kicker">Net</p><strong class="' + tone(data.net) + '">' + esc(money(data.net)) + '</strong><p class="small muted">Max drawdown ' + esc(amount(data.max_drawdown)) + (data.max_drawdown_pct ? " (" + esc(Number(data.max_drawdown_pct).toFixed(1)) + "%)" : "") + "</p></div></div>"
      + '<div class="glass equity-card"><canvas id="equity"></canvas></div>'
      + '<div class="glass pad"><p class="kicker">Weekday P&L</p><div class="heat"><span></span>'
      + days.map((day) => "<span class='kicker'>" + esc(day.day) + "</span>").join("")
      + "<span class='kicker'>P&L</span>"
      + days.map((day) => {
        const cls = !day.trades ? "" : day.pnl >= 0 ? "on-pos" : "on-neg";
        const alpha = day.trades ? Math.max(0.25, Math.min(1, Math.abs(day.pnl) / max)) : 0.2;
        return '<div class="cell ' + cls + '" style="opacity:' + alpha + '" title="' + esc(money(day.pnl)) + '"></div>';
      }).join("")
      + "</div></div>"
      + '<div class="glass pad"><p class="kicker">Streak</p><div class="streak">' + ((data.streak || []).map((item) => '<span class="tick ' + esc(item) + '"></span>').join("") || "<span class='muted'>No closed trades yet.</span>") + "</div></div>"
      + "</section>";
  }

  function renderSettings() {
    const bg = localStorage.getItem("fd_bg") || "statue";
    const apiBase = localStorage.getItem("fd_api") || "";
    const choices = ["statue", "eye", "warrior", "light"].map((name) => (
      '<button type="button" class="choice' + (bg === name ? " on" : "") + '" data-bg="' + name + '"><span class="swatch" style="background-image:url(\'assets/bg-' + name + '.svg\')"></span>' + esc(name) + "</button>"
    )).join("");
    return '<section class="glass pad"><p class="kicker">Display</p>'
      + '<p class="small">Risk, the watchlist, pause, and the scanner live in config.yaml and in Telegram. This page only changes how the desk looks.</p>'
      + '<div class="bg-choices">' + choices + "</div>"
      + '<p><label><input type="checkbox" id="motion"' + (localStorage.getItem("fd_motion") === "1" ? " checked" : "") + "> Reduce motion</label></p>"
      + '<p class="small muted">Saved API: ' + (apiBase ? esc(apiBase) : "not set — demo mode") + "</p>"
      + '<button type="button" class="choice" id="forget">Forget saved API</button>'
      + "</section>";
  }

  function render() {
    stopEquity();
    destroyChart();
    document.getElementById("demo-banner").hidden = state.mode !== "demo";
    const offline = document.getElementById("offline-banner");
    offline.hidden = state.mode !== "offline";
    offline.textContent = state.mode === "offline" ? (state.offlineMessage || "API unreachable") : "";
    const link = document.getElementById("link-state");
    link.textContent = state.mode === "live" ? "Live" : state.mode === "offline" ? "Offline" : "Demo";
    link.className = "link-state" + (state.mode === "live" ? " live" : "");
    const nav = document.getElementById("nav");
    nav.innerHTML = TABS.map(([id, label]) => (
      '<button type="button" data-tab="' + id + '" class="' + (state.tab === id ? "active" : "") + '">' + label + "</button>"
    )).join("");
    const views = {
      check: renderCheck,
      dashboard: renderDashboard,
      chart: renderChart,
      signals: renderSignals,
      positions: renderPositions,
      news: renderNews,
      journal: renderJournal,
      performance: renderPerformance,
      settings: renderSettings,
    };
    document.getElementById("main").innerHTML = (views[state.tab] || renderCheck)();
    bind();
    mountActiveChart();
    const equity = document.getElementById("equity");
    if (equity) {
      const points = state.mode === "demo" ? sampleEquity() : ((state.performance && state.performance.equity) || []);
      drawEquity(equity, points);
    }
  }

  function mountActiveChart() {
    const host = document.getElementById("candle-host");
    if (!host) return;
    if (state.tab === "check" && state.check) {
      mountCandle(host, state.check.candles, { lines: levelLines(state.check), overlays: state.check.overlays || {} });
    } else if (state.tab === "chart") {
      const payload = state.mode === "demo" ? sampleCheck() : state.chart;
      if (!payload) {
        host.textContent = state.mode === "live" ? "Loading chart…" : "No chart.";
        return;
      }
      const lines = (payload.overlays && payload.overlays.liquidity || []).slice(0, 6).map((level) => ({
        price: level.price, color: "rgba(255,255,255,0.35)", title: level.label || "liq", dashed: true,
      }));
      if (payload.overlays && payload.overlays.poc) lines.push({ price: payload.overlays.poc, color: "#00D4FF", title: "POC est", dashed: true });
      mountCandle(host, payload.candles, { lines, overlays: payload.overlays || {} });
    }
  }

  function bind() {
    document.getElementById("nav").querySelectorAll("button").forEach((button) => {
      button.onclick = () => setTab(button.dataset.tab);
    });
    const search = document.getElementById("q");
    if (search) {
      search.oninput = (event) => {
        state.query = event.target.value;
        const box = document.getElementById("picker-results");
        if (box) box.innerHTML = pickerRows();
        bindPicker(box);
      };
    }
    document.querySelectorAll("[data-cat]").forEach((button) => {
      button.onclick = () => { state.category = button.dataset.cat; render(); };
    });
    document.querySelectorAll("[data-tf]").forEach((button) => {
      button.onclick = () => { state.timeframe = button.dataset.tf; render(); if (state.tab === "chart") loadTab(); };
    });
    bindPicker(document.getElementById("picker-results"));
    const go = document.getElementById("go");
    if (go) go.onclick = () => runCheck();
    document.querySelectorAll("[data-bg]").forEach((button) => {
      button.onclick = () => {
        localStorage.setItem("fd_bg", button.dataset.bg);
        applyBackground();
        render();
      };
    });
    const motion = document.getElementById("motion");
    if (motion) motion.onchange = () => {
      localStorage.setItem("fd_motion", motion.checked ? "1" : "0");
      applyBackground();
      render();
    };
    const forget = document.getElementById("forget");
    if (forget) forget.onclick = () => {
      localStorage.removeItem("fd_api");
      localStorage.removeItem("fd_key");
      location.hash = "settings";
      location.reload();
    };
  }

  function bindPicker(box) {
    if (!box) return;
    box.querySelectorAll("[data-symbol]").forEach((button) => {
      button.onclick = () => {
        state.symbol = button.dataset.symbol;
        render();
        if (state.tab === "chart" && state.mode === "live") loadTab();
      };
    });
  }

  async function setTab(tab) {
    state.tab = tab;
    state.panelError = "";
    state.panelDetail = "";
    history.replaceState(null, "", "#" + tab);
    await loadTab();
  }

  async function loadTab() {
    if (state.mode !== "live") {
      render();
      return;
    }
    state.busy = true;
    render();
    try {
      if (state.tab === "dashboard") state.dashboard = await api("/api/dashboard");
      if (state.tab === "signals") state.signals = await api("/api/signals?limit=40");
      if (state.tab === "positions") state.positions = await api("/api/positions");
      if (state.tab === "journal") state.journal = await api("/api/journal?limit=40");
      if (state.tab === "performance") state.performance = await api("/api/performance");
      if (state.tab === "news") {
        state.news = await api("/api/news").catch((err) => ({ available: false, error: "data unavailable", detail: err.detail || err.message }));
        state.calendar = await api("/api/calendar").catch((err) => ({ available: false, error: "data unavailable", detail: err.detail || err.message }));
      }
      if (state.tab === "chart") {
        state.chart = await api("/api/chart?symbol=" + encodeURIComponent(state.symbol) + "&timeframe=" + encodeURIComponent(state.timeframe));
      }
      state.panelError = "";
    } catch (err) {
      state.panelError = err.message || "Request failed";
      state.panelDetail = err.detail || "";
    }
    state.busy = false;
    render();
  }

  async function runCheck() {
    state.busy = true;
    state.panelError = "";
    render();
    if (state.mode !== "live") {
      const sample = sampleCheck();
      if (state.symbol !== "EURUSD") {
        sample.warnings = sample.warnings.concat([
          "You picked " + state.symbol + ". Demo mode does not analyze it. This card is a fixed EURUSD sample.",
        ]);
      }
      state.check = sample;
      state.busy = false;
      render();
      return;
    }
    try {
      state.check = await api("/api/check?symbol=" + encodeURIComponent(state.symbol) + "&timeframe=" + encodeURIComponent(state.timeframe));
    } catch (err) {
      state.check = null;
      state.panelError = err.message || "Request failed";
      state.panelDetail = err.detail || "";
    }
    state.busy = false;
    render();
  }

  async function boot() {
    consumeHash();
    applyBackground();
    startDust();
    const params = new URLSearchParams(location.search);
    if (!localStorage.getItem("fd_api") || !localStorage.getItem("fd_key")) state.mode = "demo";
    if (params.has("preview") && state.mode === "demo") state.check = sampleCheck();
    const enter = () => {
      document.getElementById("splash").classList.add("hide");
      document.getElementById("app").hidden = false;
    };
    document.getElementById("enter").onclick = enter;
    if (params.has("nosplash")) enter();
    else setTimeout(enter, motionOff() ? 200 : 1600);
    render();
    try {
      const response = await fetch("instruments.json");
      state.instruments = await response.json();
    } catch (err) {
      state.instruments = [];
    }
    if (localStorage.getItem("fd_api") && localStorage.getItem("fd_key")) {
      try {
        await api("/api/health");
        state.mode = "live";
      } catch (err) {
        state.mode = "offline";
        state.offlineMessage = err.unavailable ? "data unavailable" : (err.message || "API unreachable");
      }
    } else {
      state.mode = "demo";
    }
    await loadTab();
  }

  boot();
})();

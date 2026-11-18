/* Visual effects: floating dust particles, generated background art, and the particle-filled equity curve. */
const FX = (() => {
  const DPR = () => Math.min(window.devicePixelRatio || 1, 2);
  const mobile = () => window.innerWidth < 860;
  const RM = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* how many particles this device can comfortably draw (phones, high-DPR screens and weak CPUs get fewer) */
  function budget(desk, phone) {
    const dpr = window.devicePixelRatio || 1, cores = navigator.hardwareConcurrency || 4;
    let n = mobile() ? phone : desk * Math.min(1.35, Math.max(.6, innerWidth * innerHeight / (1440 * 900)));
    if (dpr > 2.5) n *= .7; if (cores <= 4) n *= .75;
    return Math.round(n * (store.get('pdensity', 100) / 100));
  }
  const sprites = {};
  function sprite(rgb, soft) {           // pre-rendered glow dot: far cheaper than shadowBlur per particle
    const k = rgb + soft; if (sprites[k]) return sprites[k];
    const c = document.createElement('canvas'), S = 64; c.width = c.height = S; const x = c.getContext('2d');
    const g = x.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
    g.addColorStop(0, `rgba(${rgb},1)`); g.addColorStop(soft ? .15 : .22, `rgba(${rgb},${soft ? .5 : .9})`); g.addColorStop(soft ? .5 : .45, `rgba(${rgb},${soft ? .16 : .25})`); g.addColorStop(1, `rgba(${rgb},0)`);
    x.fillStyle = g; x.fillRect(0, 0, S, S); return (sprites[k] = c);
  }

  /* ---------- ambient particles over the background: dust, bokeh, sparkles, rare light streaks ---------- */
  function dust() {
    const c = $('#fx'), x = c.getContext('2d'); let W, H, P = [], S = [], running = false, last = 0, mx = -1e4, my = -1e4;
    const size = () => { const d = DPR(); W = c.width = innerWidth * d; H = c.height = innerHeight * d; c.style.width = innerWidth + 'px'; c.style.height = innerHeight + 'px';
      const n = RM() ? 0 : budget(260, 80);
      P = Array.from({ length: n }, (_, i) => { const kind = i % 25 === 0 ? 2 : i % 7 === 0 ? 1 : 0;   // 0 dust, 1 bokeh, 2 sparkle
        return { x: Math.random() * W, y: Math.random() * H, kind, r: (kind === 1 ? 6 + Math.random() * 14 : kind === 2 ? 2.2 + Math.random() * 2 : .6 + Math.random() * 1.8) * d,
          vx: (Math.random() - .5) * .14, vy: -(Math.random() * .28 + .04) * (kind === 1 ? .45 : 1), a: kind === 1 ? .05 + Math.random() * .09 : .15 + Math.random() * .55, t: Math.random() * 6, sp: .6 + Math.random() * 1.8 }; }); };
    size(); addEventListener('resize', size);
    addEventListener('pointermove', e => { mx = e.clientX * DPR(); my = e.clientY * DPR(); }, { passive: true });
    function loop(now) {
      if (!running) return;
      const fps = mobile() ? 30 : 60; if (now - last < 1000 / fps - 2) return requestAnimationFrame(loop); const dt = Math.min(3, (now - last) / 16.7 || 1); last = now;
      x.clearRect(0, 0, W, H);
      if (store.get('particles', true) && P.length) {
        const d = DPR(), L = Theme.light; const tf = Theme.theme.tf; const main = L ? '150,120,70' : tf ? '214,218,226' : Theme.G, white = L ? '90,90,100' : '225,245,255', acc = L ? '37,99,235' : tf ? '170,178,192' : Theme.C;
        const sp0 = sprite(white, 0), sp1 = sprite(main, 1), sp2 = sprite(acc, 0), sp3 = sprite(main, 0);
        x.globalCompositeOperation = L ? 'source-over' : 'lighter';
        for (const p of P) {
          p.t += .01 * dt * p.sp; p.x += (p.vx + Math.sin(p.t * .7) * .05) * d * dt; p.y += p.vy * d * dt;
          if (p.y < -30) { p.y = H + 20; p.x = Math.random() * W; } if (p.x < -30) p.x = W + 20; else if (p.x > W + 30) p.x = -20;
          const dx = p.x - mx, dy = p.y - my, dd = dx * dx + dy * dy, R = 130 * d;
          if (dd < R * R && p.kind !== 1) { const f = (1 - Math.sqrt(dd) / R) * 1.6 * d; p.x += dx / (Math.sqrt(dd) + 1) * f; p.y += dy / (Math.sqrt(dd) + 1) * f; }
          const tw = p.kind === 2 ? Math.pow(.5 + .5 * Math.sin(p.t * 3), 3) : .6 + .4 * Math.sin(p.t * 2);
          x.globalAlpha = Math.min(1, p.a * tw * (p.kind === 1 ? 1 : .9 + .3 * Theme.glow) * (L ? .7 : 1));
          const img = p.kind === 1 ? sp1 : p.kind === 2 ? sp2 : (p.sp > 1.7 ? sp3 : sp0), s2 = p.r * (p.kind === 1 ? 2 : 4);
          x.drawImage(img, p.x - s2 / 2, p.y - s2 / 2, s2, s2);
          if (p.kind === 2 && tw > .6) { x.globalAlpha = (tw - .6) * 1.2; x.fillStyle = `rgba(${white},1)`; x.fillRect(p.x - p.r * 3, p.y - .5 * d, p.r * 6, d); x.fillRect(p.x - .5 * d, p.y - p.r * 3, d, p.r * 6); }
        }
        // occasional light streak (desktop only)
        if (!mobile() && Math.random() < .004 * dt && S.length < 2) S.push({ x: Math.random() * W, y: Math.random() * H * .5, vx: (4 + Math.random() * 4) * d, vy: (1.5 + Math.random() * 2) * d, life: 1 });
        for (const s of S) { s.x += s.vx * dt; s.y += s.vy * dt; s.life -= .018 * dt; const g = x.createLinearGradient(s.x, s.y, s.x - s.vx * 14, s.y - s.vy * 14);
          g.addColorStop(0, `rgba(${white},${.7 * s.life})`); g.addColorStop(1, `rgba(${main},0)`); x.globalAlpha = 1; x.strokeStyle = g; x.lineWidth = 1.4 * d; x.beginPath(); x.moveTo(s.x, s.y); x.lineTo(s.x - s.vx * 14, s.y - s.vy * 14); x.stroke(); }
        S = S.filter(s => s.life > 0 && s.x < W + 200);
        x.globalAlpha = 1; x.globalCompositeOperation = 'source-over';
      }
      requestAnimationFrame(loop);
    }
    const start = () => { if (running || RM() || document.hidden) return; running = true; last = 0; requestAnimationFrame(loop); };
    const stop = () => { running = false; x.clearRect(0, 0, W, H); };
    document.addEventListener('visibilitychange', () => document.hidden ? (running = false) : start());   // paused while the tab is hidden
    matchMedia('(prefers-reduced-motion: reduce)').addEventListener?.('change', () => { size(); RM() ? stop() : start(); });
    start();
    return { resize: size };
  }

  /* ---------- generated background art (original, no copyright) ---------- */
  function drawArt(c, kind, w, h) {
    const x = c.getContext('2d'); c.width = w; c.height = h; const r = rng(hash(kind));
    x.fillStyle = '#030405'; x.fillRect(0, 0, w, h);
    if (kind === 'flow') {
      const g = x.createRadialGradient(w * .7, h * .4, 0, w * .7, h * .4, w * .6); g.addColorStop(0, 'rgba(0,80,50,.35)'); g.addColorStop(1, 'rgba(0,0,0,0)'); x.fillStyle = g; x.fillRect(0, 0, w, h);
      for (let i = 0; i < 70; i++) {
        const y0 = h * (.2 + r() * .7), amp = h * (.03 + r() * .08), f = 1.5 + r() * 3, ph = r() * 6, col = r() < .6 ? Theme.G : Theme.C;
        x.beginPath(); for (let px = 0; px <= w; px += 6) { const y = y0 + Math.sin(px / w * f * 3.14 + ph) * amp + Math.sin(px / w * 11 + ph * 2) * amp * .15; px ? x.lineTo(px, y) : x.moveTo(px, y); }
        x.strokeStyle = `rgba(${col},${.03 + r() * .12})`; x.lineWidth = .6 + r() * 1.6; x.shadowBlur = 12; x.shadowColor = `rgba(${col},.6)`; x.stroke();
      }
      for (let i = 0; i < 900; i++) { x.fillStyle = `rgba(210,255,230,${r() * .5})`; x.shadowBlur = 0; x.fillRect(r() * w, r() * h, r() * 1.6, r() * 1.6); }
    } else { // 'ascend' - particle clouds rising to a light burst
      const cx = w * .3, cy = h * .18;
      for (let i = 0; i < 260; i++) { const a = r() * 6.283, L = h * (.2 + r() * .9); x.strokeStyle = `rgba(255,250,235,${r() * .07})`; x.lineWidth = r() * 1.2; x.beginPath(); x.moveTo(cx, cy); x.lineTo(cx + Math.cos(a) * L, cy + Math.sin(a) * L); x.stroke(); }
      const g = x.createRadialGradient(cx, cy, 0, cx, cy, h * .45); g.addColorStop(0, 'rgba(255,248,225,.9)'); g.addColorStop(.08, 'rgba(255,240,200,.35)'); g.addColorStop(1, 'rgba(0,0,0,0)'); x.fillStyle = g; x.fillRect(0, 0, w, h);
      const N = 60000;
      for (let i = 0; i < N; i++) {
        const k = r(); const px = r() * w; const cloudY = h * (.55 + .25 * Math.sin(px / w * 7 + 1) * Math.sin(px / w * 3)) ;
        const py = cloudY + (r() - .3) * h * .5 * k; const d = Math.hypot(px - cx, py - cy) / h;
        x.fillStyle = `rgba(235,238,242,${Math.max(0, .8 - d * .3) * r()})`; x.fillRect(px, py, 1.4, 1.4);
      }
      // figure silhouette reaching up
      x.fillStyle = 'rgba(5,6,8,.92)'; const fx = cx, fy = h * .5;
      x.beginPath(); x.ellipse(fx, fy - h * .12, h * .018, h * .024, 0, 0, 6.283); x.fill();
      x.beginPath(); x.moveTo(fx - h * .03, fy - h * .09); x.lineTo(fx + h * .03, fy - h * .09); x.lineTo(fx + h * .045, fy + h * .2); x.lineTo(fx - h * .05, fy + h * .2); x.closePath(); x.fill();
      x.lineWidth = h * .012; x.strokeStyle = 'rgba(5,6,8,.92)'; x.lineCap = 'round';
      x.beginPath(); x.moveTo(fx + h * .02, fy - h * .08); x.lineTo(fx + h * .05, fy - h * .2); x.lineTo(fx + h * .055, fy - h * .27); x.stroke();
    }
  }

  /* ---------- particle equity curve with crosshair + tooltip (hover on PC, tap / press-and-drag on phones) ---------- */
  function equity(canvas, series, opts = {}) {
    const ctx = canvas.getContext('2d'); let W, H, pts = [], parts = [], embers = [], hover = null, hideAt = 0, t0 = RM() ? -1e9 : performance.now(), alive = true, rafOn = false;
    const base = opts.base ?? (series[0]?.value || 0);
    const pad = Object.assign({ l: 16, r: 70, t: 92, b: 34 }, opts.pad || {});
    canvas.style.touchAction = 'pan-y'; canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', 'Equity curve. Hover or drag to read the balance at any point.');
    function layout() {
      const rect = canvas.getBoundingClientRect(); const d = DPR(); W = canvas.width = Math.max(1, rect.width * d); H = canvas.height = Math.max(1, rect.height * d);
      if (!series.length || !rect.width) return;
      const vals = series.map(p => p.value); let lo = Math.min(...vals, base), hi = Math.max(...vals, base); const span = (hi - lo) || 1; lo -= span * .12; hi += span * .1;
      const t1 = series[0].time, t2 = series[series.length - 1].time || t1 + 1;
      const X = t => (pad.l + (t - t1) / ((t2 - t1) || 1) * (rect.width - pad.l - pad.r)) * d, Y = v => (pad.t + (1 - (v - lo) / (hi - lo)) * (rect.height - pad.t - pad.b)) * d;
      pts = series.map((p, i) => ({ x: X(p.time), y: Y(p.value), v: p.value, t: p.time, prev: i ? series[i - 1].value : base })); layout.Y = Y;
      const n = Math.round(budget(opts.small ? 7000 : 16000, opts.small ? 2400 : 4200) * Math.min(1.4, rect.width / 1200) * (opts.small ? 1 : 1));
      parts = []; const bot = H - pad.b * d;
      for (let i = 0; i < n; i++) {
        const px = pts[0].x + Math.random() * (pts[pts.length - 1].x - pts[0].x); const cy = yAt(px);
        const k = Math.pow(Math.random(), 2.4); const py = cy + (bot - cy) * k;
        parts.push({ x: px, y: py, r: (Math.random() * 1.15 + .35) * d, a: (1 - k) * .85 + .07, ph: Math.random() * 6.28, sp: .5 + Math.random() * 1.6, k });
      }
      embers = Array.from({ length: mobile() ? 40 : 110 }, () => newEmber(true));
    }
    function newEmber(any) { const px = pts.length ? pts[0].x + Math.random() * (pts[pts.length - 1].x - pts[0].x) : 0; const y0 = yAt(px);
      return { x: px, y: any ? y0 - Math.random() * 60 * DPR() : y0, vy: -(.25 + Math.random() * .6) * DPR(), vx: (Math.random() - .5) * .25 * DPR(), life: any ? Math.random() : 1, r: (1 + Math.random() * 1.8) * DPR() }; }
    function yAt(px) { for (let i = 1; i < pts.length; i++) if (pts[i].x >= px) { const a = pts[i - 1], b = pts[i]; const f = (px - a.x) / ((b.x - a.x) || 1); return a.y + (b.y - a.y) * f; } return pts.length ? pts[pts.length - 1].y : 0; }
    function nearest(px) { let lo = 0, hi = pts.length - 1; while (hi - lo > 1) { const m = (lo + hi) >> 1; if (pts[m].x < px) lo = m; else hi = m; } return Math.abs(pts[lo].x - px) <= Math.abs(pts[hi].x - px) ? lo : hi; }
    function path() { ctx.beginPath(); pts.forEach((p, i) => { if (!i) return ctx.moveTo(p.x, p.y); const q = pts[i - 1]; const mx = (q.x + p.x) / 2; ctx.bezierCurveTo(mx, q.y, mx, p.y, p.x, p.y); }); }
    function frame(now) {
      rafOn = false; if (!alive || !canvas.isConnected) return;
      const d = DPR(), L = Theme.light, prog = Math.min(1, (now - t0) / 1600), ease = 1 - Math.pow(1 - prog, 3);
      ctx.clearRect(0, 0, W, H);
      if (!pts.length) { ctx.fillStyle = '#9CA3AF'; ctx.font = `${13 * d}px Inter`; ctx.textAlign = 'center'; ctx.fillText(opts.empty || 'No closed trades yet', W / 2, H / 2); return; }
      const up = pts[pts.length - 1].v >= base; const col = up ? Theme.G : Theme.R; const bot = H - pad.b * d;
      ctx.strokeStyle = L ? 'rgba(0,0,0,.06)' : 'rgba(255,255,255,.045)'; ctx.lineWidth = 1; for (let i = 0; i < 5; i++) { const y = (pad.t * d) + i * ((H - (pad.t + pad.b) * d) / 4); ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
      const clipX = pts[0].x + (pts[pts.length - 1].x - pts[0].x) * ease;
      ctx.save(); ctx.beginPath(); ctx.rect(0, 0, clipX + 2, H); ctx.clip();
      path(); ctx.lineTo(pts[pts.length - 1].x, bot); ctx.lineTo(pts[0].x, bot); ctx.closePath();
      const g = ctx.createLinearGradient(0, pad.t * d, 0, H); g.addColorStop(0, `rgba(${col},${L ? .16 : .24})`); g.addColorStop(1, `rgba(${col},0)`); ctx.fillStyle = g; ctx.fill();
      const tt = now / 1000; const hi = L ? '255,255,255' : '233,255,242';
      ctx.fillStyle = `rgb(${col})`;
      for (const p of parts) { if (p.k < .07) continue; const tw = .55 + .45 * Math.sin(tt * p.sp + p.ph); ctx.globalAlpha = p.a * tw * (L ? .75 : 1); ctx.fillRect(p.x, p.y + Math.sin(tt * .6 + p.ph) * 1.2 * d, p.r, p.r); }
      ctx.fillStyle = `rgb(${hi})`;
      for (const p of parts) { if (p.k >= .07) continue; const tw = .55 + .45 * Math.sin(tt * p.sp + p.ph); ctx.globalAlpha = p.a * tw; ctx.fillRect(p.x, p.y + Math.sin(tt * .6 + p.ph) * 1.2 * d, p.r, p.r); }
      // embers rising off the curve
      const em = sprite(col, 0);
      for (let i = 0; i < embers.length; i++) { const e = embers[i]; if (!RM()) { e.x += e.vx; e.y += e.vy; e.life -= .006; } if (e.life <= 0) { embers[i] = newEmber(false); continue; }
        ctx.globalAlpha = Math.sin(e.life * 3.14) * .8; const s2 = e.r * 5; ctx.drawImage(em, e.x - s2 / 2, e.y - s2 / 2, s2, s2); }
      ctx.globalAlpha = 1;
      const by = layout.Y(base); ctx.setLineDash([6 * d, 6 * d]); ctx.strokeStyle = 'rgba(110,139,255,.65)'; ctx.lineWidth = 1.4 * d; ctx.beginPath(); ctx.moveTo(0, by); ctx.lineTo(W, by); ctx.stroke(); ctx.setLineDash([]);
      path(); ctx.strokeStyle = `rgba(${col},1)`; ctx.lineWidth = 2.4 * d; ctx.shadowBlur = 18 * d * Theme.glow; ctx.shadowColor = `rgba(${col},.9)`; ctx.stroke(); ctx.shadowBlur = 0;
      // light sweeping along the line
      if (!RM()) { const sx = pts[0].x + ((tt * .18) % 1) * (pts[pts.length - 1].x - pts[0].x); const gg = ctx.createRadialGradient(sx, yAt(sx), 0, sx, yAt(sx), 38 * d); gg.addColorStop(0, `rgba(${hi},.4)`); gg.addColorStop(1, `rgba(${hi},0)`); ctx.fillStyle = gg; ctx.globalCompositeOperation = L ? 'source-over' : 'lighter'; ctx.fillRect(sx - 38 * d, yAt(sx) - 38 * d, 76 * d, 76 * d); ctx.globalCompositeOperation = 'source-over'; }
      ctx.restore();
      const lp = pts[pts.length - 1];
      if (prog >= 1) { const pr = (tt % 1.8) / 1.8; ctx.beginPath(); ctx.arc(lp.x, lp.y, (5 + pr * 16) * d, 0, 6.283); ctx.strokeStyle = `rgba(${col},${(1 - pr) * .7})`; ctx.lineWidth = 1.5 * d; ctx.stroke(); if (hover == null) badge(lp.x, lp.y, money2(lp.v), col); }
      ctx.fillStyle = L ? '#6B7280' : '#6B7280'; ctx.font = `${11 * d}px Inter`; ctx.textAlign = 'center';
      const nl = mobile() ? 3 : 6; for (let i = 0; i < nl; i++) { const p = pts[Math.round(i * (pts.length - 1) / (nl - 1))]; ctx.fillText(dmy(p.t), Math.min(W - 30 * d, Math.max(30 * d, p.x)), H - 10 * d); }
      if (hover != null && hideAt && now > hideAt) { hover = null; hideAt = 0; }
      if (hover != null) tip(pts[nearest(hover)], col);
      if (RM()) return;
      if (document.hidden) return setTimeout(kick, 1000);
      kick();
    }
    function kick() { if (!rafOn && alive) { rafOn = true; requestAnimationFrame(frame); } }
    function tip(p, col) {
      const d = DPR(), L = Theme.light, top = pad.t * d * .55, bot = H - pad.b * d;
      ctx.strokeStyle = L ? 'rgba(0,0,0,.28)' : 'rgba(255,255,255,.32)'; ctx.lineWidth = d; ctx.setLineDash([4 * d, 4 * d]);
      ctx.beginPath(); ctx.moveTo(p.x, top); ctx.lineTo(p.x, bot); ctx.moveTo(0, p.y); ctx.lineTo(W, p.y); ctx.stroke(); ctx.setLineDash([]);
      ctx.beginPath(); ctx.arc(p.x, p.y, 6 * d, 0, 6.283); ctx.fillStyle = `rgb(${col})`; ctx.shadowBlur = 18 * d; ctx.shadowColor = `rgba(${col},1)`; ctx.fill(); ctx.shadowBlur = 0;
      ctx.beginPath(); ctx.arc(p.x, p.y, 2.5 * d, 0, 6.283); ctx.fillStyle = '#fff'; ctx.fill();
      const pl = p.v - base, pct = base ? pl / base * 100 : 0, ch = p.v - p.prev, chp = p.prev ? ch / p.prev * 100 : 0;
      const sg = v => (v > 0 ? '+' : v < 0 ? '-' : '') , pc = v => sg(v) + Math.abs(v).toFixed(2) + '%';
      const when = new Date(p.t * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      const rows = [['Balance', money2(p.v), null], ['P/L vs start', `${sg(pl)}${money2(Math.abs(pl))} (${pc(pct)})`, pl], ['vs previous', `${sg(ch)}${money2(Math.abs(ch))} (${pc(chp)})`, ch]];
      const fs = (mobile() ? 12 : 12.5) * d; ctx.font = `600 ${fs}px Inter`;
      const lw = Math.max(...rows.map(r => ctx.measureText(r[0]).width)), vw = Math.max(...rows.map(r => { ctx.font = `700 ${fs}px Inter`; return ctx.measureText(r[1]).width; }));
      ctx.font = `600 ${11 * d}px Inter`; const hw = ctx.measureText(when).width;
      const bw = Math.max(lw + vw + 34 * d, hw + 24 * d), lh = 19 * d, bh = 30 * d + rows.length * lh;
      let bx = p.x + 16 * d; if (bx + bw > W - 4 * d) bx = p.x - bw - 16 * d; bx = Math.max(4 * d, bx);
      let byy = Math.min(Math.max(4 * d, p.y - bh / 2), H - bh - 4 * d);
      ctx.fillStyle = L ? 'rgba(255,255,255,.96)' : 'rgba(8,10,14,.92)'; ctx.strokeStyle = `rgba(${col},.7)`; ctx.lineWidth = d;
      ctx.shadowBlur = 24 * d; ctx.shadowColor = L ? 'rgba(0,0,0,.18)' : `rgba(${col},.35)`; roundRect(bx, byy, bw, bh, 10 * d); ctx.fill(); ctx.shadowBlur = 0; ctx.stroke();
      ctx.textBaseline = 'middle'; ctx.textAlign = 'left'; ctx.fillStyle = L ? '#4B5563' : '#9CA3AF'; ctx.fillText(when, bx + 12 * d, byy + 15 * d);
      rows.forEach((r, i) => { const y = byy + 30 * d + i * lh + lh / 2 - 2 * d; ctx.font = `600 ${fs}px Inter`; ctx.textAlign = 'left'; ctx.fillStyle = L ? '#6B7280' : '#9CA3AF'; ctx.fillText(r[0], bx + 12 * d, y);
        ctx.font = `700 ${fs}px Inter`; ctx.textAlign = 'right'; ctx.fillStyle = r[2] == null ? (L ? '#111827' : '#fff') : r[2] > 0 ? Theme.g : r[2] < 0 ? Theme.r : (L ? '#374151' : '#D1D5DB'); ctx.fillText(r[1], bx + bw - 12 * d, y); });
      ctx.textBaseline = 'alphabetic';
      // value tag on the right axis
      ctx.font = `700 ${11 * d}px Inter`; const t2 = money2(p.v), tw2 = ctx.measureText(t2).width + 12 * d; ctx.fillStyle = `rgb(${col})`; roundRect(W - tw2 - 2 * d, p.y - 10 * d, tw2, 20 * d, 5 * d); ctx.fill();
      ctx.fillStyle = L ? '#fff' : '#05130b'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(t2, W - tw2 / 2 - 2 * d, p.y + d); ctx.textBaseline = 'alphabetic';
    }
    function badge(x0, y0, text, col) {
      const d = DPR(), L = Theme.light; ctx.font = `600 ${12 * d}px Inter`; const tw = ctx.measureText(text).width + 16 * d, th = 24 * d;
      let bx = Math.min(W - tw - 4 * d, Math.max(4 * d, x0 - tw / 2)), by = y0 - th - 14 * d; if (by < 4 * d) by = y0 + 14 * d;
      ctx.beginPath(); ctx.arc(x0, y0, 4.5 * d, 0, 6.283); ctx.fillStyle = `rgb(${col})`; ctx.shadowBlur = 16 * d; ctx.shadowColor = `rgba(${col},1)`; ctx.fill(); ctx.shadowBlur = 0;
      ctx.fillStyle = L ? 'rgba(255,255,255,.92)' : 'rgba(8,10,12,.85)'; ctx.strokeStyle = `rgba(${col},.6)`; ctx.lineWidth = d; roundRect(bx, by, tw, th, 7 * d); ctx.fill(); ctx.stroke();
      ctx.fillStyle = L ? '#111827' : '#fff'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, bx + tw / 2, by + th / 2 + d); ctx.textBaseline = 'alphabetic';
    }
    function roundRect(x0, y0, w, h, r) { ctx.beginPath(); ctx.moveTo(x0 + r, y0); ctx.arcTo(x0 + w, y0, x0 + w, y0 + h, r); ctx.arcTo(x0 + w, y0 + h, x0, y0 + h, r); ctx.arcTo(x0, y0 + h, x0, y0, r); ctx.arcTo(x0, y0, x0 + w, y0, r); ctx.closePath(); }
    layout(); kick();
    const ro = new ResizeObserver(() => { layout(); kick(); }); ro.observe(canvas);
    const at = e => { const r = canvas.getBoundingClientRect(); return (e.clientX - r.left) * DPR(); };
    canvas.addEventListener('pointerdown', e => { hover = at(e); hideAt = 0; if (e.pointerType !== 'mouse') try { canvas.setPointerCapture(e.pointerId); } catch { } kick(); });
    canvas.addEventListener('pointermove', e => { if (e.pointerType === 'mouse' || e.buttons || e.pressure > 0 || hover != null) { hover = at(e); hideAt = 0; kick(); } });
    const lift = e => { if (e.pointerType === 'mouse') { hover = null; } else hideAt = performance.now() + 3500; kick(); };   // touch: tooltip stays 3.5s after lifting
    canvas.addEventListener('pointerup', lift); canvas.addEventListener('pointercancel', lift); canvas.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse') { hover = null; kick(); } });
    return { destroy() { alive = false; ro.disconnect(); }, _pts: () => pts };
  }

  /* ---------- small semicircle gauge (svg) ---------- */
  function gauge(pct, color) {
    const a = Math.PI * Math.max(0, Math.min(100, pct)) / 100; const R = 56, cx = 66, cy = 66;
    const ex = cx - R * Math.cos(a), ey = cy - R * Math.sin(a);
    return `<svg viewBox="0 0 132 76"><path d="M10 66 A56 56 0 0 1 122 66" style="stroke:var(--track)" stroke-width="9" fill="none" stroke-linecap="round"/>
      <path d="M10 66 A56 56 0 0 1 ${ex.toFixed(1)} ${ey.toFixed(1)}" stroke="${color}" stroke-width="9" fill="none" stroke-linecap="round" style="filter:drop-shadow(0 0 6px ${color})"/></svg>`;
  }
  return { dust, drawArt, equity, gauge, budget };
})();

/* Visual effects: floating dust particles, generated background art, and the particle-filled equity curve. */
const FX = (() => {
  const DPR = () => Math.min(window.devicePixelRatio || 1, 2);
  const mobile = () => window.innerWidth < 860;

  /* ---------- floating dust over the background ---------- */
  function dust() {
    const c = $('#fx'), x = c.getContext('2d'); let W, H, P = [];
    const size = () => { W = c.width = innerWidth * DPR(); H = c.height = innerHeight * DPR(); c.style.width = innerWidth + 'px'; c.style.height = innerHeight + 'px';
      const n = mobile() ? 35 : 80; P = Array.from({ length: n }, () => ({ x: Math.random() * W, y: Math.random() * H, r: (Math.random() * 1.4 + .3) * DPR(), vx: (Math.random() - .5) * .12, vy: -Math.random() * .25 - .04, a: Math.random() * .5 + .1, t: Math.random() * 6 })); };
    size(); addEventListener('resize', size);
    (function loop() {
      if (store.get('particles', true)) {
        x.clearRect(0, 0, W, H);
        for (const p of P) {
          p.x += p.vx * DPR(); p.y += p.vy * DPR(); p.t += .01; if (p.y < -5) { p.y = H + 5; p.x = Math.random() * W; }
          const a = p.a * (.6 + .4 * Math.sin(p.t * 2));
          x.beginPath(); x.arc(p.x, p.y, p.r, 0, 6.283); x.fillStyle = `rgba(200,255,225,${a})`; x.shadowBlur = 6 * DPR() * Theme.glow; x.shadowColor = `rgba(${Theme.G},.6)`; x.fill();
        }
      } else x.clearRect(0, 0, W, H);
      requestAnimationFrame(loop);
    })();
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

  /* ---------- particle equity curve ---------- */
  function equity(canvas, series, opts = {}) {
    const ctx = canvas.getContext('2d'); let W, H, pts = [], parts = [], hover = null, t0 = performance.now(), alive = true;
    const base = opts.base ?? (series[0]?.value || 0);
    const pad = { l: 16, r: 70, t: 92, b: 34 };
    function layout() {
      const rect = canvas.getBoundingClientRect(); const d = DPR(); W = canvas.width = rect.width * d; H = canvas.height = rect.height * d;
      if (!series.length) return;
      const vals = series.map(p => p.value); let lo = Math.min(...vals, base), hi = Math.max(...vals, base); const span = (hi - lo) || 1; lo -= span * .12; hi += span * .1;
      const t1 = series[0].time, t2 = series[series.length - 1].time || t1 + 1;
      const X = t => (pad.l + (t - t1) / ((t2 - t1) || 1) * (rect.width - pad.l - pad.r)) * d, Y = v => (pad.t + (1 - (v - lo) / (hi - lo)) * (rect.height - pad.t - pad.b)) * d;
      pts = series.map(p => ({ x: X(p.time), y: Y(p.value), v: p.value, t: p.time })); layout.Y = Y; layout.lo = lo; layout.hi = hi;
      const n = Math.round((mobile() ? 3200 : 9000) * Math.min(1.4, rect.width / 1200));
      parts = [];
      for (let i = 0; i < n; i++) {
        const px = pts[0].x + Math.random() * (pts[pts.length - 1].x - pts[0].x); const cy = yAt(px); const bot = H - pad.b * d;
        const k = Math.pow(Math.random(), 2.2); const py = cy + (bot - cy) * k;
        parts.push({ x: px, y: py, r: (Math.random() * 1.1 + .35) * d, a: (1 - k) * .85 + .08, ph: Math.random() * 6.28, sp: .5 + Math.random() * 1.5, k });
      }
    }
    function yAt(px) { for (let i = 1; i < pts.length; i++) if (pts[i].x >= px) { const a = pts[i - 1], b = pts[i]; const f = (px - a.x) / ((b.x - a.x) || 1); return a.y + (b.y - a.y) * f; } return pts.length ? pts[pts.length - 1].y : 0; }
    function path() { ctx.beginPath(); pts.forEach((p, i) => { if (!i) return ctx.moveTo(p.x, p.y); const q = pts[i - 1]; const mx = (q.x + p.x) / 2; ctx.bezierCurveTo(mx, q.y, mx, p.y, p.x, p.y); }); }
    function frame(now) {
      if (!alive || !canvas.isConnected) return;
      const d = DPR(), prog = Math.min(1, (now - t0) / 1400), ease = 1 - Math.pow(1 - prog, 3);
      ctx.clearRect(0, 0, W, H);
      if (!pts.length) { ctx.fillStyle = '#9CA3AF'; ctx.font = `${13 * d}px Inter`; ctx.textAlign = 'center'; ctx.fillText(opts.empty || 'No closed trades yet', W / 2, H / 2); return requestAnimationFrame(frame); }
      const up = pts[pts.length - 1].v >= base; const col = up ? Theme.G : Theme.R;
      // grid
      ctx.strokeStyle = 'rgba(255,255,255,.045)'; ctx.lineWidth = 1; for (let i = 0; i < 5; i++) { const y = (pad.t * d) + i * ((H - (pad.t + pad.b) * d) / 4); ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
      const clipX = pts[0].x + (pts[pts.length - 1].x - pts[0].x) * ease;
      ctx.save(); ctx.beginPath(); ctx.rect(0, 0, clipX + 2, H); ctx.clip();
      // soft area glow
      path(); ctx.lineTo(pts[pts.length - 1].x, H - pad.b * d); ctx.lineTo(pts[0].x, H - pad.b * d); ctx.closePath();
      const g = ctx.createLinearGradient(0, pad.t * d, 0, H); g.addColorStop(0, `rgba(${col},.22)`); g.addColorStop(1, `rgba(${col},0)`); ctx.fillStyle = g; ctx.fill();
      // particles
      const tt = now / 1000;
      for (const p of parts) {
        const tw = .55 + .45 * Math.sin(tt * p.sp + p.ph); const yy = p.y + Math.sin(tt * .6 + p.ph) * 1.2 * d;
        ctx.globalAlpha = p.a * tw; ctx.fillStyle = p.k < .08 ? '#E9FFF2' : `rgb(${col})`; ctx.fillRect(p.x, yy, p.r, p.r);
      }
      ctx.globalAlpha = 1;
      // base line (start balance) dashed
      const by = layout.Y(base); ctx.setLineDash([6 * d, 6 * d]); ctx.strokeStyle = 'rgba(110,139,255,.65)'; ctx.lineWidth = 1.4 * d; ctx.beginPath(); ctx.moveTo(0, by); ctx.lineTo(W, by); ctx.stroke(); ctx.setLineDash([]);
      // glowing line
      path(); ctx.strokeStyle = `rgba(${col},1)`; ctx.lineWidth = 2.4 * d; ctx.shadowBlur = 18 * d * Theme.glow; ctx.shadowColor = `rgba(${col},.9)`; ctx.stroke(); ctx.shadowBlur = 0;
      ctx.restore();
      // last value badge
      const lp = pts[pts.length - 1]; if (prog >= 1) badge(lp.x, lp.y, money2(lp.v), col, true);
      // hover
      if (hover != null && prog >= 1) {
        let best = pts[0]; for (const p of pts) if (Math.abs(p.x - hover) < Math.abs(best.x - hover)) best = p;
        ctx.strokeStyle = 'rgba(255,255,255,.18)'; ctx.lineWidth = d; ctx.beginPath(); ctx.moveTo(best.x, pad.t * d); ctx.lineTo(best.x, H - pad.b * d); ctx.stroke();
        badge(best.x, best.y, money2(best.v) + '  ·  ' + dmy(best.t), Theme.C);
      }
      // x labels
      ctx.fillStyle = '#6B7280'; ctx.font = `${11 * d}px Inter`; ctx.textAlign = 'center';
      const nl = mobile() ? 3 : 6; for (let i = 0; i < nl; i++) { const p = pts[Math.round(i * (pts.length - 1) / (nl - 1))]; ctx.fillText(dmy(p.t), Math.min(W - 30 * d, Math.max(30 * d, p.x)), H - 10 * d); }
      requestAnimationFrame(frame);
    }
    function badge(x0, y0, text, col, end) {
      const d = DPR(); ctx.font = `600 ${12 * d}px Inter`; const tw = ctx.measureText(text).width + 16 * d, th = 24 * d;
      let bx = Math.min(W - tw - 4 * d, Math.max(4 * d, x0 - tw / 2)), by = y0 - th - 14 * d; if (by < 4 * d) by = y0 + 14 * d;
      ctx.beginPath(); ctx.arc(x0, y0, 4.5 * d, 0, 6.283); ctx.fillStyle = `rgb(${col})`; ctx.shadowBlur = 16 * d; ctx.shadowColor = `rgba(${col},1)`; ctx.fill(); ctx.shadowBlur = 0;
      ctx.fillStyle = 'rgba(8,10,12,.85)'; ctx.strokeStyle = `rgba(${col},.6)`; ctx.lineWidth = d; roundRect(bx, by, tw, th, 7 * d); ctx.fill(); ctx.stroke();
      ctx.fillStyle = '#fff'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, bx + tw / 2, by + th / 2 + d); ctx.textBaseline = 'alphabetic';
    }
    function roundRect(x0, y0, w, h, r) { ctx.beginPath(); ctx.moveTo(x0 + r, y0); ctx.arcTo(x0 + w, y0, x0 + w, y0 + h, r); ctx.arcTo(x0 + w, y0 + h, x0, y0 + h, r); ctx.arcTo(x0, y0 + h, x0, y0, r); ctx.arcTo(x0, y0, x0 + w, y0, r); ctx.closePath(); }
    layout(); requestAnimationFrame(frame);
    const ro = new ResizeObserver(() => layout()); ro.observe(canvas);
    canvas.addEventListener('pointermove', e => { const r = canvas.getBoundingClientRect(); hover = (e.clientX - r.left) * DPR(); });
    canvas.addEventListener('pointerleave', () => hover = null);
    return { destroy() { alive = false; ro.disconnect(); } };
  }

  /* ---------- small semicircle gauge (svg) ---------- */
  function gauge(pct, color) {
    const a = Math.PI * Math.max(0, Math.min(100, pct)) / 100; const R = 56, cx = 66, cy = 66;
    const ex = cx - R * Math.cos(a), ey = cy - R * Math.sin(a);
    return `<svg viewBox="0 0 132 76"><path d="M10 66 A56 56 0 0 1 122 66" stroke="rgba(255,255,255,.08)" stroke-width="9" fill="none" stroke-linecap="round"/>
      <path d="M10 66 A56 56 0 0 1 ${ex.toFixed(1)} ${ey.toFixed(1)}" stroke="${color}" stroke-width="9" fill="none" stroke-linecap="round" style="filter:drop-shadow(0 0 6px ${color})"/></svg>`;
  }
  return { dust, drawArt, equity, gauge };
})();

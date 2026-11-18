/* Cinematic motion layer: staggered card entrance, number count-ups, button ripples, background parallax.
   Everything is skipped under prefers-reduced-motion. */
const Anim = (() => {
  const RM = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fine = () => matchMedia('(hover: hover) and (pointer: fine)').matches;
  let t0 = 0, idx = 0;
  const fresh = () => performance.now() - t0 < 2500;          // only animate content that appears right after a tab change
  const NUM_SEL = '.huge, .stat .v, .big, .sess-net, .sz-pct, .wr-grid .v, .sess-grid .v, .gauge .gv, .pnl-count';

  function countUp(el) {
    if (el.dataset.cu || el.children.length) return; el.dataset.cu = '1';
    const txt = el.textContent.trim(); const m = txt.match(/^([^\d]*?)(\d[\d,]*(?:\.\d+)?)([^\d]*)$/); if (!m) return;
    const [, pre, numS, post] = m; const target = parseFloat(numS.replace(/,/g, '')); if (!isFinite(target) || target === 0) return;
    const decs = (numS.split('.')[1] || '').length, commas = numS.includes(',');
    const fmt = v => v.toLocaleString('en-US', { minimumFractionDigits: decs, maximumFractionDigits: decs, useGrouping: commas });
    const dur = 900 + Math.min(600, Math.log10(target + 1) * 200), s = performance.now();
    const step = now => { const k = Math.min(1, (now - s) / dur), e = 1 - Math.pow(1 - k, 4);
      if (!el.isConnected) return; el.textContent = k < 1 ? pre + fmt(target * e) + post : txt; if (k < 1) requestAnimationFrame(step); };
    el.textContent = pre + fmt(0) + post; requestAnimationFrame(step);
  }

  function scan(root) {
    if (RM() || !fresh()) return;
    const panels = root.matches?.('.panel') ? [root] : [];
    panels.push(...(root.querySelectorAll ? root.querySelectorAll('.panel') : []));
    panels.forEach(p => { if (p.classList.contains('pin')) return; p.style.setProperty('--i', Math.min(idx++, 12)); p.classList.add('pin'); });
    const nums = root.matches?.(NUM_SEL) ? [root] : []; nums.push(...(root.querySelectorAll ? root.querySelectorAll(NUM_SEL) : []));
    nums.forEach(countUp);
  }

  function ripple(e) {
    const b = e.target.closest('.btn, .chip, .seg button, .tabs button, .check-btn, .pal button, .theme-card, .bg-opt'); if (!b || RM()) return;
    const r = b.getBoundingClientRect(), d = Math.max(r.width, r.height) * 2.2; const s = document.createElement('span'); s.className = 'rip';
    s.style.cssText = `width:${d}px;height:${d}px;left:${e.clientX - r.left - d / 2}px;top:${e.clientY - r.top - d / 2}px`;
    b.appendChild(s); setTimeout(() => s.remove(), 650);
  }

  function parallax() {
    const bg = $('#bg'); let mx = 0, my = 0, sy = 0, raf = 0;
    const put = () => { raf = 0; bg.style.setProperty('--px', (mx).toFixed(1) + 'px'); bg.style.setProperty('--py', (my + sy).toFixed(1) + 'px'); };
    const q = () => { if (!raf) raf = requestAnimationFrame(put); };
    addEventListener('pointermove', e => { if (RM() || !fine()) return; mx = (e.clientX / innerWidth - .5) * -22; my = (e.clientY / innerHeight - .5) * -14; q(); }, { passive: true });
    addEventListener('scroll', () => { if (RM()) return; sy = Math.max(-40, -scrollY * .04); q(); }, { passive: true });
  }

  return {
    stamp() { t0 = performance.now(); idx = 0; },
    init() {
      const v = $('#view');
      new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => n.nodeType === 1 && scan(n)))).observe(v, { childList: true, subtree: true });
      document.addEventListener('pointerdown', ripple, { passive: true });
      parallax();
    },
    countUp,
  };
})();

# Headless check that an open desk/PWA reloads itself after a new build is published.
# Usage: cp -r docs /tmp/fdpwa && (cd /tmp/fdpwa && python3 -m http.server 8011 &) && python tools/pwa_autoreload_check.py
import asyncio, subprocess, os
from playwright.async_api import async_playwright
URL = "http://127.0.0.1:8011/?tab=settings#demo=1"
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, service_workers="allow")
        page = await ctx.new_page()
        await page.goto(URL); await page.wait_for_timeout(2500)
        await page.evaluate("localStorage.setItem('fd_theme', JSON.stringify(Object.assign({}, Theme.cur, {theme:'gold'}))); localStorage.setItem('fd_splash','false')")
        await page.reload(); await page.wait_for_timeout(2000)
        v1 = await page.evaluate("Updater.cur"); sw = await page.evaluate("navigator.serviceWorker.controller ? 'controlled' : 'none'")
        await page.evaluate("window.__marker = 42")
        # ship a new build: change a desk file and re-stamp (like a push)
        with open("/tmp/fdpwa/js/views.js", "a") as f: f.write("\n/* build bump test */\n")
        v2 = subprocess.check_output(["python3", "tools/stamp_version.py"], env=dict(os.environ, FD_DOCS="/tmp/fdpwa"), text=True).strip()
        same = await page.evaluate("window.__marker")
        await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")   # app brought back to the foreground
        await page.wait_for_timeout(3500)
        after = await page.evaluate("[window.__marker ?? null, Updater.cur, document.querySelector('meta[name=fd-version]').content, Theme.cur.theme, store.get('tab')]")
        bumped = await page.evaluate("fetch('js/views.js').then(r => r.text()).then(t => t.includes('build bump test'))")
        print({"v1": v1, "sw": sw, "v2": v2, "marker_before": same, "after_reload": after, "new_code_loaded": bumped})
        assert after[0] is None and after[1] == v2 and bumped and after[3] == 'gold'
        print("AUTO-RELOAD OK")
        await b.close()
asyncio.run(main())

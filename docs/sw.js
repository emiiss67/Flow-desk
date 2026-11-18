/* FlowDesk service worker: always fresh desk code.
   HTML / JS / CSS / JSON: network first (revalidated), cache only as an offline fallback.
   Images & fonts: cache first (their URLs never change in place). The API (other origin) is never touched. */
const CACHE = 'fd-shell-v1';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
  await self.clients.claim();
})()));
self.addEventListener('fetch', e => {
  const req = e.request; const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.endsWith('/version.json') || url.pathname.endsWith('/endpoint.json')) {
    e.respondWith(fetch(req, { cache: 'no-store' }).catch(() => caches.match(req, { ignoreSearch: true }))); return;
  }
  const code = req.mode === 'navigate' || /\.(html|js|css|json|webmanifest)$/.test(url.pathname) || url.pathname.endsWith('/');
  if (code) {
    e.respondWith((async () => {
      try {
        const res = await fetch(req, { cache: 'no-cache' });
        if (res.ok) { const c = await caches.open(CACHE); c.put(req, res.clone()); }
        return res;
      } catch { return (await caches.match(req)) || (await caches.match(req, { ignoreSearch: true })) || Response.error(); }
    })());
    return;
  }
  e.respondWith((async () => {
    const hit = await caches.match(req); if (hit) return hit;
    const res = await fetch(req); if (res.ok) { const c = await caches.open(CACHE); c.put(req, res.clone()); } return res;
  })());
});

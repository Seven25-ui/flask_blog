// SE7EN service worker
// - Pages: network-first (kanunay presko ang login/session), offline page kung walay internet
// - /static/: cache (stale-while-revalidate)
// - POST, socket.io, api, ug laing sites (Cloudinary etc.): dili hilabtan
const CACHE = 'se7en-v1';
const OFFLINE_URL = '/static/offline.html';
const PRECACHE = [OFFLINE_URL, '/static/icons/icon-192.png', '/static/icons/icon-512.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/socket.io') || url.pathname.startsWith('/api/')) return;

  // Page navigations
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  // Static files
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then((hit) => {
        const network = fetch(req)
          .then((res) => {
            if (res && res.ok) {
              const copy = res.clone();
              caches.open(CACHE).then((c) => c.put(req, copy));
            }
            return res;
          })
          .catch(() => hit);
        return hit || network;
      })
    );
  }
});

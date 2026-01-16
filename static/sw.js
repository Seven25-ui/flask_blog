self.addEventListener('install', (e) => {
  console.log('SE7EN App: Installed');
});

self.addEventListener('fetch', (e) => {
  e.respondWith(fetch(e.request));
});

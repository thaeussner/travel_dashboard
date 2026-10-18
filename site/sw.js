// Offline support: the app shell is cached, data is fetched fresh when possible.
// The GitHub API is never cached; unsaved edits live in localStorage (see assets/store.js).
const CACHE = 'flight-free-v2';
const SHELL = [
  './', './costs/', './emissions/', './method/', './manifest.webmanifest', './icons/icon.svg',
  './assets/app.css', './assets/common.js', './assets/store.js', './assets/editor.js',
  './assets/costs.js', './assets/emissions.js', './assets/home.js', './assets/method.js', './vendor/d3.v7.9.0.min.js',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.hostname === 'api.github.com') return;
  if (url.origin === location.origin && url.pathname.includes('/data/')) {
    e.respondWith(fetch(req)
      .then(res => { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); return res; })
      .catch(() => caches.match(req)));
    return;
  }
  if (url.origin === location.origin || url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    e.respondWith(caches.open(CACHE).then(async (c) => {
      const hit = await c.match(req, { ignoreSearch: url.origin === location.origin });
      const net = fetch(req)
        .then(res => { if (res.ok || res.type === 'opaque') c.put(req, res.clone()); return res; })
        .catch(() => hit);
      return hit || net;
    }));
  }
});

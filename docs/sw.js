// Service worker minimo: rete prima, cache come riserva (offline).
// Serve perche' il browser consideri il sito installabile come app.
const CACHE = 'cinemasspd-v1';
const PRECACHE = [
  '/cinemassPD/',
  '/cinemassPD/index.html',
  '/cinemassPD/manifest.json',
  '/cinemassPD/apple-touch-icon.png',
  '/cinemassPD/web-app-manifest-192x192.png',
  '/cinemassPD/web-app-manifest-512x512.png',
  '/cinemassPD/favicon-96x96.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => Promise.all(PRECACHE.map((url) => cache.add(url).catch(() => {}))))
      .then(() => self.skipWaiting())
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
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || caches.match('/cinemassPD/index.html')))
  );
});

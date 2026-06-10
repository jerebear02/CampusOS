// CampusOS service worker
//
// Strategy:
//   - On install: precache the offline fallback page and core static assets.
//   - HTML navigations: network-first, fall back to cache, then to /offline.
//   - Same-origin /static/* GETs: cache-first, then network (and cache on miss).
//   - Cross-origin (Google Fonts CDN, etc.): just pass through to network.

const CACHE_VERSION = 'campusos-v2';
const OFFLINE_URL = '/offline';

// Assets to seed the cache with on first install. Keep the list short — anything
// missing here will still be cached lazily the first time it's fetched.
const CORE_ASSETS = [
  OFFLINE_URL,
  '/static/style.css',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
  '/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // Never touch non-GET requests (POSTs to /match/request, etc. must hit the network)
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Cross-origin requests (Google Fonts): network-only, no caching layer
  if (url.origin !== self.location.origin) return;

  // HTML navigations: network-first so users see fresh content; on failure,
  // fall back to any cached copy of the page, then to the offline page.
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() =>
          caches.match(req).then((cached) => cached || caches.match(OFFLINE_URL))
        )
    );
    return;
  }

  // /static/* assets: cache-first, fall back to network and warm the cache
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then(
        (cached) =>
          cached ||
          fetch(req).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(CACHE_VERSION).then((c) => c.put(req, copy)).catch(() => {});
            }
            return res;
          })
      )
    );
    return;
  }

  // /manifest.json: cache-first since it almost never changes
  if (url.pathname === '/manifest.json') {
    event.respondWith(
      caches.match(req).then((cached) => cached || fetch(req))
    );
    return;
  }

  // Default: try network, fall back to whatever is cached
  event.respondWith(fetch(req).catch(() => caches.match(req)));
});

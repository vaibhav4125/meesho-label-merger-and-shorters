const CACHE_NAME = 'meesho-hub-v2.1';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/css/style.css',
  '/js/app.js',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/icon-maskable-192.png',
  '/icons/icon-maskable-512.png',
  '/icons/icon.svg',
  '/icons/apple-touch-icon.png',
  '/icons/favicon.png'
];

// Install: Cache core static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[ServiceWorker] Pre-caching static assets');
      return cache.addAll(STATIC_ASSETS).catch((err) => {
        console.warn('[ServiceWorker] Some assets could not be pre-cached:', err);
      });
    })
  );
  self.skipWaiting();
});

// Activate: Clean up previous cache versions
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            console.log('[ServiceWorker] Removing old cache:', key);
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// Fetch: Strategy depending on request type
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Non-GET requests (e.g. POST upload, POST generate) bypass cache directly
  if (req.method !== 'GET') {
    return;
  }

  // File downloads & exports MUST bypass Service Worker completely for native browser download handling
  if (
    url.pathname.startsWith('/api/download/') ||
    url.pathname.startsWith('/api/checklist/pdf') ||
    url.pathname.includes('/export') ||
    url.pathname.includes('/backup')
  ) {
    return;
  }

  // API calls: Network-first, do NOT cache dynamic data that modifies state
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req).catch(() => {
        // If offline and request is an API call, return custom offline JSON response
        return new Response(
          JSON.stringify({ offline: true, error: 'Network unavailable. Using offline mode.' }),
          {
            headers: { 'Content-Type': 'application/json' },
            status: 503
          }
        );
      })
    );
    return;
  }

  // Static files & App shell: Network-first with cache fallback
  event.respondWith(
    fetch(req)
      .then((networkRes) => {
        if (networkRes && networkRes.status === 200) {
          const resClone = networkRes.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(req, resClone);
          });
        }
        return networkRes;
      })
      .catch(() => {
        return caches.match(req).then((cached) => {
          if (cached) return cached;
          if (req.headers.get('accept') && req.headers.get('accept').includes('text/html')) {
            return caches.match('/index.html');
          }
          return new Response('Offline resource not found', { status: 404 });
        });
      })
  );
});

// Handle skip-waiting trigger
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

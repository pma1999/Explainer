/* ============================================================
   EXPLAINER — Service Worker
   ============================================================
   Estrategias de caché:
   - Same-origin (por defecto): Network-first + actualizar caché (prioriza versión nueva)
   - Modo offline voluntario (mensaje SET_PREFER_OFFLINE): Cache-first same-origin
   - Google Fonts: Stale-while-revalidate
   - CDN jsdelivr: Network-first con caché como fallback
   - Llamadas /api/*: Pass-through (sin caché — la app usa IndexedDB)
   ============================================================
   Para forzar actualización: cambia CACHE_VERSION
   ============================================================ */

const CACHE_VERSION = 'v2';
const STATIC_CACHE = `explainer-static-${CACHE_VERSION}`;
const FONTS_CACHE = `explainer-fonts-${CACHE_VERSION}`;
const CDN_CACHE = `explainer-cdn-${CACHE_VERSION}`;

/** Set via postMessage from the app when the user enables "modo offline / ahorrar datos". */
let preferOfflineMode = false;

const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/style.css',
  '/favicon.svg',
  '/manifest.json',
  '/router.js',
  '/js/main.js',
  '/js/state.js',
  '/js/api.js',
  '/js/router.js',
  '/js/auth.js',
  '/js/landing.js',
  '/js/projects.js',
  '/js/projectView.js',
  '/js/shared.js',
  '/js/share.js',
  '/js/export.js',
  '/js/sse.js',
  '/js/storage.js',
  '/js/backupStorage.js',
  '/js/dom.js',
  '/js/pwa.js',
  '/icons/icon-192.svg',
  '/icons/icon-512.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/apple-touch-icon.svg',
  '/icons/apple-touch-icon.png',
];

// ─── Install ────────────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then(async (cache) => {
      // Pre-cache assets one by one to avoid failing on missing config.js
      const results = await Promise.allSettled(
        STATIC_ASSETS.map((url) => cache.add(url).catch(() => null))
      );
      // Try to cache config.js (may not exist in dev)
      await cache.add('/config.js').catch(() => null);
      return results;
    }).then(() => self.skipWaiting())
  );
});

// ─── Activate ───────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  const currentCaches = [STATIC_CACHE, FONTS_CACHE, CDN_CACHE];
  event.waitUntil(
    caches.keys().then((cacheNames) =>
      Promise.all(
        cacheNames
          .filter((name) => !currentCaches.includes(name))
          .map((name) => caches.delete(name))
      )
    ).then(() => self.clients.claim())
  );
});

// ─── Fetch ──────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // 1. API calls — always pass-through, never cache
  if (url.pathname.startsWith('/api/')) {
    return; // let browser handle it normally
  }

  // 2. Non-GET requests — pass-through
  if (request.method !== 'GET') {
    return;
  }

  // 3. Chrome extension or other schemes — ignore
  if (!url.protocol.startsWith('http')) {
    return;
  }

  // 4. Google Fonts — stale-while-revalidate
  if (
    url.hostname === 'fonts.googleapis.com' ||
    url.hostname === 'fonts.gstatic.com'
  ) {
    event.respondWith(staleWhileRevalidate(request, FONTS_CACHE));
    return;
  }

  // 5. Supabase CDN (supabase-js) — network-first with cache fallback
  if (url.hostname === 'cdn.jsdelivr.net') {
    event.respondWith(networkFirstWithCache(request, CDN_CACHE));
    return;
  }

  // 6. Same-origin static assets — network-first (default) or cache-first (prefer offline)
  if (url.origin === self.location.origin) {
    if (preferOfflineMode) {
      event.respondWith(cacheFirst(request));
    } else {
      event.respondWith(networkFirstWithCache(request, STATIC_CACHE));
    }
    return;
  }
});

// ─── Cache Strategies ───────────────────────────────────────

/**
 * Cache-first: serve from cache, fallback to network + update cache.
 * For app shell: index.html always gets a network refresh in background
 * so the SW can update itself on next load.
 */
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) {
    // For HTML pages: refresh cache in background (stale-while-revalidate)
    const url = new URL(request.url);
    if (url.pathname === '/' || url.pathname.endsWith('.html')) {
      refreshCache(request, STATIC_CACHE);
    }
    return cached;
  }
  return fetchAndCache(request, STATIC_CACHE);
}

/**
 * Stale-while-revalidate: serve from cache immediately, refresh in background.
 */
async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  // Always trigger a background update
  const networkFetch = fetch(request)
    .then((response) => {
      if (response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);
  return cached || networkFetch;
}

/**
 * Network-first: try network, fallback to cache.
 */
async function networkFirstWithCache(request, cacheName) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch (_) {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw new Error('Network and cache both failed');
  }
}

/**
 * Fetch and store in cache.
 */
async function fetchAndCache(request, cacheName) {
  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(cacheName);
    cache.put(request, response.clone());
  }
  return response;
}

/**
 * Background cache refresh (fire and forget).
 */
function refreshCache(request, cacheName) {
  fetch(request)
    .then(async (response) => {
      if (response.ok) {
        const cache = await caches.open(cacheName);
        cache.put(request, response);
      }
    })
    .catch(() => null);
}

// ─── Messages from clients ──────────────────────────────────
self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') {
    self.skipWaiting();
    return;
  }
  if (event.data && event.data.type === 'SET_PREFER_OFFLINE') {
    preferOfflineMode = Boolean(event.data.value);
  }
});

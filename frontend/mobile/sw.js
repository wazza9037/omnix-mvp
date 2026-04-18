/* ───────────────────────────────────────────────────────────
   OMNIX Mobile — Service Worker
   Offline-first caching, background sync, push notifications
   ─────────────────────────────────────────────────────────── */

const CACHE_VERSION = 'omnix-mobile-v1';
const STATIC_CACHE  = `${CACHE_VERSION}-static`;
const API_CACHE     = `${CACHE_VERSION}-api`;
const CDN_CACHE     = `${CACHE_VERSION}-cdn`;

/* Assets to pre-cache on install */
const PRECACHE_URLS = [
  '/mobile',
  '/mobile/manifest.json',
  '/mobile/icon-192.png',
  '/mobile/icon-512.png',
];

/* API paths to cache with network-first strategy */
const CACHEABLE_API = [
  '/api/devices',
  '/api/bt/templates',
  '/api/marketplace/featured',
  '/api/mobile/dashboard',
];

/* ── Install: pre-cache shell ── */
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      return cache.addAll(PRECACHE_URLS).catch(() => {
        /* Partial cache is OK — we'll fetch on demand */
      });
    })
  );
  self.skipWaiting();
});

/* ── Activate: purge old caches ── */
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k.startsWith('omnix-mobile-') && k !== STATIC_CACHE && k !== API_CACHE && k !== CDN_CACHE)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

/* ── Fetch strategy router ── */
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  /* Skip non-GET and WebSocket */
  if (event.request.method !== 'GET') return;
  if (url.protocol === 'ws:' || url.protocol === 'wss:') return;

  /* CDN resources (Three.js etc.) — cache-first */
  if (url.hostname.includes('cdnjs.cloudflare.com') || url.hostname.includes('cdn.jsdelivr.net')) {
    event.respondWith(cacheFirst(event.request, CDN_CACHE));
    return;
  }

  /* API calls — network-first with cache fallback */
  if (url.pathname.startsWith('/api/')) {
    const isCacheable = CACHEABLE_API.some((p) => url.pathname.startsWith(p));
    if (isCacheable) {
      event.respondWith(networkFirst(event.request, API_CACHE, 3000));
    }
    return;
  }

  /* Static assets — cache-first */
  if (url.pathname.startsWith('/mobile')) {
    event.respondWith(cacheFirst(event.request, STATIC_CACHE));
    return;
  }
});

/* ── Cache-first: serve from cache, fallback to network ── */
async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    return new Response('Offline', { status: 503, statusText: 'Service Unavailable' });
  }
}

/* ── Network-first: try network with timeout, fallback to cache ── */
async function networkFirst(request, cacheName, timeoutMs) {
  const cache = await caches.open(cacheName);
  try {
    const controller = new AbortController();
    const tid = setTimeout(() => controller.abort(), timeoutMs);
    const response = await fetch(request, { signal: controller.signal });
    clearTimeout(tid);
    if (response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: 'offline', cached: false }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

/* ── Command queue for offline mode ── */
const COMMAND_QUEUE_KEY = 'omnix-cmd-queue';

self.addEventListener('message', (event) => {
  const { type, payload } = event.data || {};

  if (type === 'QUEUE_COMMAND') {
    /* Store command for later replay when online */
    event.waitUntil(queueCommand(payload));
  }

  if (type === 'FLUSH_QUEUE') {
    event.waitUntil(flushCommandQueue());
  }

  if (type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

async function queueCommand(cmd) {
  const cache = await caches.open(API_CACHE);
  const queueRes = await cache.match('/_cmd_queue');
  let queue = [];
  if (queueRes) {
    try { queue = await queueRes.json(); } catch (_) {}
  }
  queue.push({ ...cmd, queued_at: Date.now() });
  await cache.put('/_cmd_queue', new Response(JSON.stringify(queue)));
}

async function flushCommandQueue() {
  const cache = await caches.open(API_CACHE);
  const queueRes = await cache.match('/_cmd_queue');
  if (!queueRes) return;
  let queue = [];
  try { queue = await queueRes.json(); } catch (_) { return; }
  if (!queue.length) return;

  const failed = [];
  for (const cmd of queue) {
    try {
      await fetch(cmd.url, {
        method: cmd.method || 'POST',
        headers: { 'Content-Type': 'application/json', ...(cmd.headers || {}) },
        body: JSON.stringify(cmd.body),
      });
    } catch (_) {
      failed.push(cmd);
    }
  }
  if (failed.length) {
    await cache.put('/_cmd_queue', new Response(JSON.stringify(failed)));
  } else {
    await cache.delete('/_cmd_queue');
  }
}

/* ── Push notifications ── */
self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : {};
  const title = data.title || 'OMNIX';
  const options = {
    body: data.body || '',
    icon: '/mobile/icon-192.png',
    badge: '/mobile/icon-192.png',
    tag: data.tag || 'omnix-notification',
    data: data.url || '/mobile',
    vibrate: [100, 50, 100],
    actions: data.actions || [],
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data || '/mobile';
  event.waitUntil(
    clients.matchAll({ type: 'window' }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url.includes('/mobile') && 'focus' in client) {
          return client.focus();
        }
      }
      return clients.openWindow(url);
    })
  );
});

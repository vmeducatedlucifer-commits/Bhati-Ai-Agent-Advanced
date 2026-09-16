const CACHE_NAME = 'rawal-ai-v3';

self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keyList) => {
      return Promise.all(keyList.map((key) => {
        if (key !== CACHE_NAME) {
          return caches.delete(key);
        }
      }));
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Exclude API requests, previews, and WebSocket upgrades from caching entirely
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/preview/')) {
    return; // Pass through to browser natively
  }

  // Use Network-First strategy for HTML navigations to avoid stale blank screens
  if (e.request.mode === 'navigate' || e.request.headers.get('accept').includes('text/html')) {
    e.respondWith(
      fetch(e.request).then((res) => {
        const resClone = res.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(e.request, resClone);
        });
        return res;
      }).catch(async (error) => {
        console.warn('Network failed, falling back to cache:', error);
        const cachedRes = await caches.match(e.request);
        if (cachedRes) return cachedRes;
        return caches.match('/');
      })
    );
    return;
  }

  // Cache-First strategy for static assets (JS, CSS, SVGs, Images)
  e.respondWith(
    caches.match(e.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(e.request).then((networkResponse) => {
        if (e.request.method === 'GET' && networkResponse.status === 200 && (url.protocol === 'http:' || url.protocol === 'https:')) {
            const resClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => {
                cache.put(e.request, resClone);
            });
        }
        return networkResponse;
      }).catch(error => {
        console.error('Fetching static asset failed:', error);
        throw error;
      });
    })
  );
});


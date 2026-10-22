/* Ice Factory service worker — minimal by design.

   Its ONLY job is a friendly no-connection page. It caches nothing except
   offline.html itself, and it never caches app pages or data, so financial
   data can never go stale or be read from a shared phone's cache.
*/

const OFFLINE_URL = "/static/offline.html";
const CACHE_NAME = "ice-factory-offline-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.add(OFFLINE_URL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // Only navigations get the offline fallback. Everything else goes
  // straight to the network, uncached.
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(OFFLINE_URL))
    );
  }
});

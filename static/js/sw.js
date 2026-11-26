// Minimal service worker -- exists only so the app passes Chrome's PWA
// installability checks (manifest + registered service worker + HTTPS).
// Deliberately network-only: grades/notifications must never be served
// stale from a cache, so this never calls caches.open()/caches.match().
self.addEventListener("install", (event) => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
    event.respondWith(fetch(event.request));
});

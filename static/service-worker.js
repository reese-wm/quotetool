const CACHE_NAME = "big-valley-tools-v1";
const APP_SHELL = [
    "/",
    "/install-quote",
    "/service-quote",
    "/purchase-order",
    "/offline",
    "/manifest.webmanifest",
    "/static/logo.png",
    "/app-icon/192.png",
    "/app-icon/512.png",
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
    );
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(
                keys
                    .filter((key) => key !== CACHE_NAME)
                    .map((key) => caches.delete(key))
            )
        )
    );
    self.clients.claim();
});

self.addEventListener("fetch", (event) => {
    if (event.request.method !== "GET") {
        return;
    }

    const requestUrl = new URL(event.request.url);
    const isNavigation = event.request.mode === "navigate";
    const isSameOrigin = requestUrl.origin === self.location.origin;

    if (isNavigation) {
        event.respondWith(
            fetch(event.request).catch(() => caches.match("/offline"))
        );
        return;
    }

    if (!isSameOrigin) {
        return;
    }

    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            if (cachedResponse) {
                return cachedResponse;
            }

            return fetch(event.request).then((networkResponse) => {
                if (!networkResponse || networkResponse.status !== 200) {
                    return networkResponse;
                }

                const responseClone = networkResponse.clone();
                caches.open(CACHE_NAME).then((cache) => {
                    cache.put(event.request, responseClone);
                });
                return networkResponse;
            });
        })
    );
});

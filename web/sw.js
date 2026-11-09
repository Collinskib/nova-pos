/* ShujaaPOS web till — keep the shell available offline without going stale.
   Pages: network-first (new deploys win, cache is the offline fallback).
   Static assets: cache-first (icon, manifest, CDN libs don't change per deploy).
   The sales queue lives in localStorage in app.html; the SW only owns assets. */
const C = "shujaa-v3";
const SHELL = ["/app.html", "/icon.png", "/manifest.webmanifest"];

self.addEventListener("install", e =>
  e.waitUntil(caches.open(C).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", e =>
  e.waitUntil(caches.keys().then(ks =>
    Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k)))).then(() => clients.claim())));

self.addEventListener("fetch", e => {
  const u = e.request.url;
  if (e.request.method !== "GET" || u.includes("/api/") ||
      u.includes("supabase.co") || u.includes("speed-insights")) return;

  // HTML navigations: try the network first so deploys are never stale,
  // fall back to the cached shell when offline.
  if (e.request.mode === "navigate" || (e.request.headers.get("accept") || "").includes("text/html")) {
    e.respondWith(fetch(e.request).then(r => {
      if (r.ok) { const cp = r.clone(); caches.open(C).then(c => c.put(e.request, cp)); }
      return r;
    }).catch(() => caches.match(e.request).then(m => m || caches.match("/app.html"))));
    return;
  }

  // Everything else (icons, CDN js): cache-first, refresh cache in passing.
  e.respondWith(caches.match(e.request).then(hit => hit ||
    fetch(e.request).then(r => {
      if (r.ok) { const cp = r.clone(); caches.open(C).then(c => c.put(e.request, cp)); }
      return r;
    })));
});

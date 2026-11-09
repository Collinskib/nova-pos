/* ShujaaPOS web till — cache the shell so the till opens offline.
   Sales queue lives in localStorage in app.html; the SW only owns assets. */
const C = "shujaa-v2";
const SHELL = ["/app.html", "/config.js", "/icon.png", "/manifest.webmanifest"];

self.addEventListener("install", e =>
  e.waitUntil(caches.open(C).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", e =>
  e.waitUntil(caches.keys().then(ks =>
    Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k)))).then(() => clients.claim())));

self.addEventListener("fetch", e => {
  const u = e.request.url;
  if (e.request.method !== "GET" || u.includes("/api/") ||
      u.includes("supabase.co") || u.includes("speed-insights")) return;
  e.respondWith(
    caches.match(e.request).then(hit => hit ||
      fetch(e.request).then(r => {
        if (r.ok) { const cp = r.clone(); caches.open(C).then(c => c.put(e.request, cp)); }
        return r;
      }).catch(() => caches.match("/app.html"))));
});

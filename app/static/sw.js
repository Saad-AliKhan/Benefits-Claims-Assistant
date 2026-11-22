const CACHE = "lm-shell-v5"; // bump the number whenever you change a cached file
const SHELL = ["/citizen", "/assistant", "/static/assistant.js", "/static/style.css", "/static/api.js", "/static/i18n.js", "/static/offline.js",
               "/static/voice.js", "/static/citizen.js", "/static/manifest.json", "/static/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE)
    .then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => {}))))
    .then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

/* Network first, but fall back to the saved copy after 4 s (weak signal) or when offline. */
function networkFirst(req) {
  return new Promise((resolve) => {
    let done = false;
    const timer = setTimeout(async () => {
      const c = await caches.match(req);
      if (c && !done) { done = true; resolve(c); }
    }, 4000);
    fetch(req).then((res) => {
      clearTimeout(timer);
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
      if (!done) { done = true; resolve(res); }
    }).catch(async () => {
      clearTimeout(timer);
      const c = await caches.match(req);
      if (!done) { done = true; resolve(c || Response.error()); }
    });
  });
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname === "/citizen" || url.pathname === "/assistant" || url.pathname.startsWith("/static/")) e.respondWith(networkFirst(req));
});
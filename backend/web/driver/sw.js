// App shell only; API calls are never cached (not even intercepted).
const C = 'driver-shell-v1';
const SHELL = ['./', 'index.html', 'app.js', 'styles.css', 'manifest.webmanifest'];
self.addEventListener('install', e => e.waitUntil(caches.open(C).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener('activate', e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  const base = new URL('./', self.location).pathname;
  const name = u.pathname.slice(base.length);
  if (e.request.method !== 'GET' || u.origin !== location.origin || !u.pathname.startsWith(base) || !(name === '' || SHELL.includes(name))) return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request, {ignoreSearch: true})));
});

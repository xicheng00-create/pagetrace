/* Service Worker — App Shell 缓存。
   铁律（CLAUDE.md §5）：前端资产改动必须同时 bump 下面的 CACHE 与 V，
   并在 index.html 把所有 ?v= 一起换掉（Cloudflare 对 .js/.css 强发 max-age，只 bump 这里不够）。 */
const CACHE = 'review-v0.18.3';
const V = '0.18.3';
const SHELL = [
  '/',
  '/index.html',
  '/css/app.css?v=' + V,
  '/js/api.js?v=' + V,
  '/js/flashcard.js?v=' + V,
  '/js/app.js?v=' + V, '/js/invites.js?v=' + V,
  '/js/review.js?v=' + V,
  '/js/quiz.js?v=' + V,
  '/js/wrong.js?v=' + V,
  '/js/plan.js?v=' + V,
  '/js/weak.js?v=' + V,
  '/js/report.js?v=' + V,
  '/js/scope.js?v=' + V,
  '/js/upload.js?v=' + V,
  '/js/drafts.js?v=' + V,
  '/img/logo.svg',
  '/img/icon-192.png',
  '/img/apple-touch-icon.png',
  '/manifest.webmanifest',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.pathname.startsWith('/api/') || url.pathname === '/health') {
    return; // 接口一律走网络，不缓存
  }
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return r;
      })
      .catch(() => caches.match(e.request))
  );
});

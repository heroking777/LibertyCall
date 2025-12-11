// Service Worker for LibertyCall LP
// PWA対応: オフラインキャッシュとパフォーマンス最適化

const CACHE_NAME = 'libertycall-lp-v1';
const urlsToCache = [
  '/lp/',
  '/lp/index.html',
  '/lp/style.css',
  '/lp/hero_main.png',
  '/lp/ai_abstract.png',
  '/lp/ai_call_phone.png',
  '/lp/office_modern1.png',
  '/lp/office_modern2.png',
  '/lp/contact_reception.png'
];

// インストール時: キャッシュを作成
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('Opened cache');
        return cache.addAll(urlsToCache);
      })
      .catch((error) => {
        console.error('Cache install failed:', error);
      })
  );
  self.skipWaiting();
});

// アクティベート時: 古いキャッシュを削除
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            console.log('Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  return self.clients.claim();
});

// フェッチ時: キャッシュから取得、なければネットワークから
self.addEventListener('fetch', (event) => {
  // 外部リソース（Google Analytics等）はキャッシュしない
  if (event.request.url.startsWith('http') && 
      !event.request.url.startsWith(self.location.origin)) {
    return;
  }

  event.respondWith(
    caches.match(event.request)
      .then((response) => {
        // キャッシュがあれば返す
        if (response) {
          return response;
        }
        // なければネットワークから取得してキャッシュに保存
        return fetch(event.request).then((response) => {
          // 有効なレスポンスかチェック
          if (!response || response.status !== 200 || response.type !== 'basic') {
            return response;
          }
          // レスポンスをクローン（一度しか読み取れないため）
          const responseToCache = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
          return response;
        });
      })
      .catch(() => {
        // ネットワークエラー時: オフラインページを返す（オプション）
        if (event.request.destination === 'document') {
          return caches.match('/lp/index.html');
        }
      })
  );
});


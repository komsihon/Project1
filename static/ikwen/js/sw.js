'use strict';

importScripts('https://storage.googleapis.com/workbox-cdn/releases/5.1.2/workbox-sw.js');

if (workbox) {
    console.log(`Yay! Workbox is loaded🎉`);
} else {
    console.log(`Boo! Workbox didn't load😬`);
}

// workbox.precaching.precacheAndRoute([
//     {url: '', revision: '200513'}
// ]);

workbox.core.setCacheNameDetails({
  prefix: 'ikwen',
  suffix: 'v2',
  precache: 'install-time',
  runtime: 'run-time',
  googleAnalytics: 'ga',
});

workbox.routing.registerRoute(
  new RegExp('.+\\.js'),
  new workbox.strategies.StaleWhileRevalidate()
);

workbox.routing.registerRoute(
  new RegExp('.+\\.css'),
  new workbox.strategies.StaleWhileRevalidate()
);

workbox.routing.registerRoute(
  ({url}) => url.origin === 'https://fonts.googleapis.com',
  new workbox.strategies.StaleWhileRevalidate(),
);

workbox.routing.registerRoute(
  ({url}) => url.origin === 'https://fonts.gstatic.com',
  new workbox.strategies.CacheFirst({
    cacheName: 'google-fonts-webfonts',
    plugins: [
      new workbox.cacheableResponse.CacheableResponsePlugin({
        statuses: [0, 200],
      }),
      new workbox.expiration.ExpirationPlugin({
        maxAgeSeconds: 60 * 60 * 24 * 365,
        maxEntries: 30,
      }),
    ],
  })
);

workbox.routing.registerRoute(
  // Cache image files.
  ({request}) => request.destination === 'image',
  // Use the cache if it's available.
  new workbox.strategies.CacheFirst({
    // Use a custom cache name.
    cacheName: 'image-cache',
    plugins: [
      new workbox.expiration.ExpirationPlugin({
        // Cache  100 images.
        maxEntries: 100,
        // Cache for a maximum of a month.
        maxAgeSeconds: 30 * 24 * 60 * 60,
      })
    ],
  })
);

const CACHE_NAME = 'offline-html';
const FALLBACK_HTML_URL = '/offline.html';

self.addEventListener('install', async (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.add(FALLBACK_HTML_URL))
  );
});

workbox.navigationPreload.enable();

const networkOnly = new workbox.strategies.NetworkOnly();
const navigationHandler = async (params) => {
  try {
      // Attempt a network request.
      return await networkOnly.handle(params);
  } catch (error) {
      // If it fails, return the cached HTML.
      return caches.match(FALLBACK_HTML_URL, {
          cacheName: CACHE_NAME,
      });
  }
};


/*********     HANDLING PUSH NOTIFICATIONS      **********/

self.addEventListener('push', function(event) {
    console.log(`[Service Worker] Push Received with data: "${event.data.text()}"`);

    let data = event.data.json();
    const title = data.title;
    const options = {
        body: data.body,
        icon: data.icon, // 'images/icon.png',
        badge: data.badge, // 'images/badge.png',
        tag: "renotify",
        renotify: true,
        timestamp: data.timestamp,
        data: {
            'target': data.target
        }
        // actions: [
        //     { "action": "yes", "title": "Yes", "icon": "images/yes.png" },
        //     { "action": "no", "title": "No", "icon": "images/no.png" }
        // ]
    };
    if (data.image) {
        options['image'] = data.image
    }
    const notificationPromise = self.registration.showNotification(title, options);
    event.waitUntil(notificationPromise);
    // const analyticsPromise = pushReceivedTracking();
    // const pushInfoPromise = fetch('/analytics').then(function(response) {
    //     return response.json();
    // }).then(function(response) {
    //     self.registration.showNotification(title, options);
    // });
    // const promiseChain = Promise.all([
    //     analyticsPromise,
    //     pushInfoPromise
    // ]);
    // event.waitUntil(promiseChain);
});

self.addEventListener('notificationclick', function(event) {
    const pushTargetPage = event.notification.data.target;
    if (pushTargetPage) {
        const urlToOpen = new URL(pushTargetPage, self.location.origin).href;
        const promiseChain = clients.matchAll({
            type: 'window',
            includeUncontrolled: true
        }).then((windowClients) => {
            let matchingClient = null;
            for (let i = 0; i < windowClients.length; i++) {
                const windowClient = windowClients[i];
                if (windowClient.url === urlToOpen) {
                    matchingClient = windowClient;
                    break;
                }
            }
            if (matchingClient) {
                return matchingClient.focus();
            } else {
                return clients.openWindow(urlToOpen);
            }
        });
        event.notification.close();
        event.waitUntil(promiseChain);
    } else {
        event.notification.close();
    }
});


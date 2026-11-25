{% load static %}
const CACHE = 'dipu-turf-shell-v3';
const SHELL = [
  '{% static "turf/site.css" %}',
  '{% static "turf/workspace.css" %}',
  '{% static "turf/booking.css" %}',
  '{% static "turf/craft.css" %}',
  '{% static "turf/friendly.css" %}',
  '{% static "turf/icon.svg" %}',
  '{% static "turf/manifest.webmanifest" %}'
];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)));
  self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)))));
  self.clients.claim();
});
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET' || new URL(request.url).origin !== self.location.origin) return;
  if (request.destination === 'style' || request.destination === 'image' || request.url.includes('/manifest.webmanifest')) {
    event.respondWith(caches.match(request).then(cached => cached || fetch(request).then(response => {
      const copy = response.clone();
      caches.open(CACHE).then(cache => cache.put(request, copy));
      return response;
    })));
  }
});

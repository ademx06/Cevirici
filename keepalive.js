/**
 * Render uyku modunu önlemek — sayfa açıkken /api/status ping (4 dk).
 */
(function (global) {
  'use strict';

  const INTERVAL_MS = 4 * 60 * 1000;

  let timer = null;

  function ping() {
    fetch('/api/status', { method: 'GET', cache: 'no-store' }).catch(function () {});
  }

  function start() {
    if (timer) return;
    ping();
    timer = setInterval(ping, INTERVAL_MS);
  }

  function stop() {
    if (!timer) return;
    clearInterval(timer);
    timer = null;
  }

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stop();
    else start();
  });

  if (!document.hidden) start();

  global.KeepAlive = { start: start, stop: stop, ping: ping };
})(typeof window !== 'undefined' ? window : globalThis);

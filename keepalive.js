/**
 * Sunucuyu uyanık tut — /api/ping (2 dk). AI isteği sırasında da yanıt alır.
 */
(function (global) {
  'use strict';

  const INTERVAL_MS = 2 * 60 * 1000;
  const PING_URL = '/api/ping';

  let timer = null;

  function ping() {
    fetch(PING_URL, { method: 'GET', cache: 'no-store' }).catch(function () {});
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
    if (document.hidden) {
      stop();
    } else {
      ping();
      start();
    }
  });

  if (!document.hidden) start();

  global.KeepAlive = { start: start, stop: stop, ping: ping };
})(typeof window !== 'undefined' ? window : globalThis);

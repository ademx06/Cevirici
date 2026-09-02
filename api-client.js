/**
 * Sunucu bağlantısı — Render uyku modu ve geçici 502 için uyandırma + yeniden deneme.
 */
(function (global) {
  'use strict';

  const RETRYABLE = new Set([0, 502, 503, 504]);

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  async function fetchWithTimeout(url, options, timeoutMs) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: ctrl.signal, cache: 'no-store' });
    } finally {
      clearTimeout(timer);
    }
  }

  async function wakeServer(maxWaitMs = 45000) {
    const start = Date.now();
    let delay = 1200;
    while (Date.now() - start < maxWaitMs) {
      try {
        const r = await fetchWithTimeout('/api/status', { method: 'GET' }, 8000);
        if (r.ok) {
          const d = await r.json();
          if (d && d.ok) return true;
        }
      } catch {
        /* sunucu uyanıyor */
      }
      await sleep(delay);
      delay = Math.min(delay * 1.4, 5000);
    }
    return false;
  }

  async function fetchJson(url, options = {}, cfg = {}) {
    const {
      retries = 3,
      timeoutMs = 90000,
      wakeFirst = true,
      onRetry = null,
    } = cfg;

    if (wakeFirst) {
      await wakeServer(45000);
    }

    let lastErr = null;
    for (let attempt = 0; attempt < retries; attempt++) {
      if (attempt > 0) {
        if (typeof onRetry === 'function') onRetry(attempt, retries);
        await wakeServer(30000);
        await sleep(800 * attempt);
      }
      try {
        const r = await fetchWithTimeout(url, options, timeoutMs);
        if (RETRYABLE.has(r.status)) {
          lastErr = new Error(`HTTP ${r.status}`);
          continue;
        }
        const text = await r.text();
        let data = {};
        if (text.trim()) {
          try {
            data = JSON.parse(text);
          } catch {
            lastErr = new Error('Geçersiz sunucu yanıtı');
            continue;
          }
        }
        return { ok: r.ok, status: r.status, data };
      } catch (err) {
        lastErr = err;
      }
    }
    throw lastErr || new Error('Bağlantı hatası');
  }

  function connectionErrorMessage(err) {
    if (err && err.name === 'AbortError') {
      return 'İstek zaman aşımına uğradı — tekrar dene.';
    }
    return 'Bağlantı hatası — sunucu uyuyor olabilir, birkaç saniye sonra tekrar dene.';
  }

  global.ApiClient = {
    wakeServer,
    fetchJson,
    connectionErrorMessage,
  };
})(typeof window !== 'undefined' ? window : globalThis);

/**
 * Sunucu bağlantısı — Render uyku + eşzamanlı AI isteklerinde erişilebilirlik.
 */
(function (global) {
  'use strict';

  const RETRYABLE = new Set([0, 502, 503, 504]);
  const PING_URL = '/api/ping';
  const STATUS_URL = '/api/status';

  function sleep(ms) {
    return new Promise(function (r) { setTimeout(r, ms); });
  }

  async function fetchWithTimeout(url, options, timeoutMs) {
    const ctrl = new AbortController();
    const timer = setTimeout(function () { ctrl.abort(); }, timeoutMs);
    try {
      return await fetch(url, Object.assign({}, options, { signal: ctrl.signal, cache: 'no-store' }));
    } finally {
      clearTimeout(timer);
    }
  }

  async function quickPing(timeoutMs) {
    timeoutMs = timeoutMs || 6000;
    try {
      const r = await fetchWithTimeout(PING_URL, { method: 'GET' }, timeoutMs);
      if (!r.ok) return false;
      const d = await r.json();
      return !!(d && d.ok);
    } catch {
      return false;
    }
  }

  async function quickStatusCheck(timeoutMs) {
    timeoutMs = timeoutMs || 6000;
    try {
      const r = await fetchWithTimeout(STATUS_URL, { method: 'GET' }, timeoutMs);
      if (!r.ok) return false;
      const d = await r.json();
      return !!(d && d.ok);
    } catch {
      return false;
    }
  }

  async function wakeServer(maxWaitMs, onProgress) {
    maxWaitMs = maxWaitMs || 90000;
    if (await quickPing(5000)) return true;

    const start = Date.now();
    let delay = 1500;
    let tick = 0;
    while (Date.now() - start < maxWaitMs) {
      tick += 1;
      if (typeof onProgress === 'function') {
        const sec = Math.round((Date.now() - start) / 1000);
        onProgress(sec, maxWaitMs);
      }
      if (await quickPing(8000)) return true;
      await sleep(delay);
      delay = Math.min(Math.round(delay * 1.15), 4000);
    }
    return false;
  }

  async function ensureConnection(onProgress) {
    return wakeServer(90000, onProgress);
  }

  async function fetchJson(url, options, cfg) {
    options = options || {};
    cfg = cfg || {};
    const retries = cfg.retries != null ? cfg.retries : 3;
    const timeoutMs = cfg.timeoutMs != null ? cfg.timeoutMs : 90000;
    const wakeFirst = cfg.wakeFirst !== false;
    const onRetry = cfg.onRetry || null;
    const onWakeProgress = cfg.onWakeProgress || null;

    if (wakeFirst) {
      const awake = await wakeServer(90000, onWakeProgress);
      if (!awake) throw new Error('Sunucu uyanamadı');
    }

    let lastErr = null;
    for (let attempt = 0; attempt < retries; attempt++) {
      if (attempt > 0) {
        if (typeof onRetry === 'function') onRetry(attempt, retries);
        await wakeServer(60000, onWakeProgress);
        await sleep(1000 * attempt);
      }
      try {
        const r = await fetchWithTimeout(url, options, timeoutMs);
        if (RETRYABLE.has(r.status)) {
          lastErr = new Error('HTTP ' + r.status);
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
        return { ok: r.ok, status: r.status, data: data };
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
    if (err && err.message === 'Sunucu uyanamadı') {
      return 'Sunucu uyandırılamadı — 1 dakika bekleyip tekrar dene.';
    }
    return 'Bağlantı hatası — tekrar dene.';
  }

  global.ApiClient = {
    quickPing: quickPing,
    quickStatusCheck: quickStatusCheck,
    wakeServer: wakeServer,
    ensureConnection: ensureConnection,
    fetchJson: fetchJson,
    connectionErrorMessage: connectionErrorMessage,
  };
})(typeof window !== 'undefined' ? window : globalThis);

/**
 * Sunucu bağlantısı — hızlı kontrol, kısa uyandırma, gerektiğinde tek retry.
 */
(function (global) {
  'use strict';

  const RETRYABLE = new Set([0, 502, 503, 504]);

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

  async function quickStatusCheck(timeoutMs) {
    timeoutMs = timeoutMs || 3500;
    try {
      const r = await fetchWithTimeout('/api/status', { method: 'GET' }, timeoutMs);
      if (!r.ok) return false;
      const d = await r.json();
      return !!(d && d.ok);
    } catch {
      return false;
    }
  }

  async function wakeServer(maxWaitMs) {
    maxWaitMs = maxWaitMs || 15000;
    if (await quickStatusCheck(3500)) return true;
    const start = Date.now();
    let delay = 1200;
    while (Date.now() - start < maxWaitMs) {
      if (await quickStatusCheck(5000)) return true;
      await sleep(delay);
      delay = Math.min(Math.round(delay * 1.25), 3500);
    }
    return false;
  }

  async function fetchJson(url, options, cfg) {
    options = options || {};
    cfg = cfg || {};
    const retries = cfg.retries != null ? cfg.retries : 2;
    const timeoutMs = cfg.timeoutMs != null ? cfg.timeoutMs : 90000;
    const wakeFirst = cfg.wakeFirst !== false;
    const onRetry = cfg.onRetry || null;

    if (wakeFirst) {
      const awake = await wakeServer(15000);
      if (!awake) throw new Error('Sunucu uyanamadı');
    }

    let lastErr = null;
    for (let attempt = 0; attempt < retries; attempt++) {
      if (attempt > 0) {
        if (typeof onRetry === 'function') onRetry(attempt, retries);
        await sleep(1200 * attempt);
      }
      try {
        const r = await fetchWithTimeout(url, options, timeoutMs);
        if (RETRYABLE.has(r.status)) {
          lastErr = new Error('HTTP ' + r.status);
          if (attempt === 0 && r.status === 502) {
            await wakeServer(12000);
          }
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
      return 'Sunucu uyuyor — birkaç saniye bekleyip tekrar dene.';
    }
    return 'Bağlantı hatası — tekrar dene.';
  }

  global.ApiClient = {
    quickStatusCheck: quickStatusCheck,
    wakeServer: wakeServer,
    fetchJson: fetchJson,
    connectionErrorMessage: connectionErrorMessage,
  };
})(typeof window !== 'undefined' ? window : globalThis);

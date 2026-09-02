/**
 * Sunucu bağlantısı — Render uyku + uzun AI istekleri.
 */
(function (global) {
  'use strict';

  const RETRYABLE = new Set([0, 502, 503, 504]);
  const PING_URL = '/api/ping';

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
    timeoutMs = timeoutMs || 5000;
    try {
      const r = await fetchWithTimeout(PING_URL, { method: 'GET' }, timeoutMs);
      if (!r.ok) return false;
      const d = await r.json();
      return !!(d && d.ok);
    } catch {
      return false;
    }
  }

  async function wakeServer(maxWaitMs, onProgress) {
    maxWaitMs = maxWaitMs || 30000;
    if (await quickPing(5000)) return true;
    const start = Date.now();
    let delay = 1500;
    while (Date.now() - start < maxWaitMs) {
      if (typeof onProgress === 'function') {
        onProgress(Math.round((Date.now() - start) / 1000), maxWaitMs);
      }
      if (await quickPing(8000)) return true;
      await sleep(delay);
      delay = Math.min(Math.round(delay * 1.2), 3500);
    }
    return false;
  }

  async function fetchJson(url, options, cfg) {
    options = options || {};
    cfg = cfg || {};
    const retries = cfg.retries != null ? cfg.retries : 2;
    const timeoutMs = cfg.timeoutMs != null ? cfg.timeoutMs : 90000;
    const wakeMs = cfg.wakeMs != null ? cfg.wakeMs : 30000;
    const wakeFirst = cfg.wakeFirst !== false;
    const onRetry = cfg.onRetry || null;
    const onWakeProgress = cfg.onWakeProgress || null;

    if (wakeFirst) {
      const awake = await wakeServer(wakeMs, onWakeProgress);
      if (!awake) throw new Error('Sunucu uyanamadı');
    }

    let lastErr = null;
    for (let attempt = 0; attempt < retries; attempt++) {
      if (attempt > 0) {
        if (typeof onRetry === 'function') onRetry(attempt, retries);
        await wakeServer(wakeMs, onWakeProgress);
        await sleep(1500);
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

  /** Kelime dersi — tek deneme, uzun timeout, otomatik retry yok */
  async function fetchWordLesson(url, body, callbacks) {
    callbacks = callbacks || {};
    if (!(await quickPing(4000))) {
      const awake = await wakeServer(25000, callbacks.onWake);
      if (!awake) throw new Error('Sunucu uyanamadı');
    }
    const started = Date.now();
    let progressTimer = null;
    if (typeof callbacks.onProgress === 'function') {
      progressTimer = setInterval(function () {
        callbacks.onProgress(Math.round((Date.now() - started) / 1000));
      }, 5000);
    }
    try {
      const r = await fetchWithTimeout(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }, 150000);
      if (RETRYABLE.has(r.status)) {
        throw new Error('HTTP ' + r.status);
      }
      const text = await r.text();
      let data = {};
      if (text.trim()) {
        data = JSON.parse(text);
      }
      return { ok: r.ok, status: r.status, data: data };
    } finally {
      if (progressTimer) clearInterval(progressTimer);
    }
  }

  function connectionErrorMessage(err) {
    if (err && err.name === 'AbortError') {
      return 'AI dersi uzun sürdü — tekrar dene.';
    }
    if (err && err.message === 'Sunucu uyanamadı') {
      return 'Sunucu uyuyor — birkaç saniye bekleyip tekrar dene.';
    }
    return 'Bağlantı hatası — tekrar dene.';
  }

  global.ApiClient = {
    quickPing: quickPing,
    wakeServer: wakeServer,
    fetchJson: fetchJson,
    fetchWordLesson: fetchWordLesson,
    connectionErrorMessage: connectionErrorMessage,
  };
})(typeof window !== 'undefined' ? window : globalThis);

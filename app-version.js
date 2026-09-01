/**
 * Uygulama sürüm çubuğu — ana menü ve diğer sayfalarda paylaşılır.
 */
(function (global) {
  'use strict';

  function clientBundleVersion() {
    const meta = document.querySelector('meta[name="app-version"]');
    return meta?.getAttribute('content') || '';
  }

  function versionNumber(v) {
    const m = String(v || '').match(/v(\d+)/i);
    return m ? parseInt(m[1], 10) : 0;
  }

  function shouldOfferUpdate(serverVersion) {
    const client = clientBundleVersion();
    if (!client || !serverVersion) return false;
    return versionNumber(serverVersion) > versionNumber(client);
  }

  async function fetchAppStatus() {
    const r = await fetch('/api/status', { cache: 'no-store' });
    return r.json();
  }

  function hardReloadApp() {
    const u = new URL(window.location.href);
    u.searchParams.set('_v', String(Date.now()));
    window.location.replace(u.toString());
  }

  async function pollForNewVersion(baseline, maxMs = 120000) {
    const start = Date.now();
    while (Date.now() - start < maxMs) {
      await new Promise((r) => setTimeout(r, 4000));
      try {
        const d = await fetchAppStatus();
        if (d.app_version && d.app_version !== baseline) {
          hardReloadApp();
          return true;
        }
      } catch {
        /* keep polling */
      }
    }
    hardReloadApp();
    return false;
  }

  function renderAppVersionBar(d, opts = {}) {
    const bar = document.getElementById('appVersionBar');
    const text = document.getElementById('appVersionText');
    const btn = document.getElementById('appUpdateBtn');
    if (!bar || !text) return;
    const v = d?.app_version || '?';
    const target = d?.target_app_version || clientBundleVersion() || v;
    const stale = shouldOfferUpdate(v);
    const updating = !!opts.updating;
    const ai = d?.ai_fallback_enabled
      ? ` · AI: ${d.ai_provider_label || d.ai_provider || ''}`
      : d?.ai_provider_label
        ? ` · ${d.ai_provider_label}`
        : '';
    const ok = d?.ok ? '✅' : '⚠️';
    text.textContent = updating
      ? `⏳ Güncelleniyor… (şu an ${v})`
      : stale
        ? `${ok} Eski sürüm: ${v} · Hedef: ${target}${ai}`
        : `${ok} Sürüm ${v}${ai}`;
    bar.classList.toggle('app-version-stale', stale || updating);
    bar.classList.toggle('app-version-ok', !stale && !!d?.app_version);
    if (btn) {
      btn.classList.toggle('hidden', !stale && !updating);
      btn.disabled = updating;
      btn.textContent = updating ? 'Güncelleniyor…' : 'Programı Güncelle';
    }
    if (!stale && v && v !== '?') {
      try { localStorage.setItem('appVersion', v); } catch { /* ignore */ }
    }
  }

  async function runAppUpdate() {
    const btn = document.getElementById('appUpdateBtn');
    if (!btn || btn.disabled) return;
    let baseline = '?';
    try {
      const current = await fetchAppStatus();
      baseline = current.app_version || '?';
      renderAppVersionBar(current, { updating: true });
    } catch {
      renderAppVersionBar({ ok: false, app_version: '?' }, { updating: true });
    }
    btn.disabled = true;
    try {
      await fetch('/api/deploy-update', { method: 'POST', cache: 'no-store' });
    } catch {
      /* deploy hook yoksa bile sayfa yenileme devam */
    }
    await pollForNewVersion(baseline);
  }

  async function initAppVersion() {
    const btn = document.getElementById('appUpdateBtn');
    btn?.addEventListener('click', runAppUpdate);
    try {
      const d = await fetchAppStatus();
      renderAppVersionBar(d);
    } catch {
      renderAppVersionBar({ ok: false, app_version: '?' });
    }
  }

  global.AppVersion = {
    init: initAppVersion,
    fetchStatus: fetchAppStatus,
    render: renderAppVersionBar,
    clientBundleVersion,
  };
})(typeof window !== 'undefined' ? window : globalThis);

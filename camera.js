/* Kamera çeviri: kamera önizlemesi → kare → /api/camera/translate (Gemini görsel okuma + çeviri). */
(() => {
  'use strict';
  const LANGS = [
    ['tr', '🇹🇷 Türkçe'], ['en', '🇬🇧 English'], ['de', '🇩🇪 Deutsch'], ['fr', '🇫🇷 Français'], ['es', '🇪🇸 Español'],
    ['it', '🇮🇹 Italiano'], ['ru', '🇷🇺 Русский'], ['ar', '🇸🇦 العربية'], ['zh', '🇨🇳 中文'], ['ka', '🇬🇪 ქართული'], ['id', '🇮🇩 Bahasa Indonesia'],
  ];
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const video = $('camVideo'); const shot = $('camShot'); const canvas = $('camCanvas');
  const sel = $('camTarget'); const out = $('camOut');
  let stream = null; let live = false; let busy = false; let timer = null; let lastSig = null; let lastKey = '';
  const get = (k, d) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
  const set = (k, v) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } };

  sel.innerHTML = LANGS.map(([c, n]) => `<option value="${c}">${n}</option>`).join('');
  sel.value = get('cam_target', 'tr');
  sel.addEventListener('change', () => { set('cam_target', sel.value); lastSig = null; lastKey = ''; if (live) tick(true); });

  const status = (t) => { $('camStatusText').textContent = t; };
  const msg = (t) => { const m = $('camMsg'); m.textContent = t || ''; m.hidden = !t; };

  async function startCam() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { msg('Bu tarayıcıda kamera yok — “Fotoğraf seç” ile çevir'); return; }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false });
      video.srcObject = stream; await video.play().catch(() => {});
      msg(''); status('Yazıya tut ve “Çevir”e bas ya da Canlı’yı aç');
    } catch (e) {
      msg('Kamera izni verilmedi — “Fotoğraf seç” ile de çevirebilirsin');
    }
  }
  function stopCam() { if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; } }

  /** Videodan (ya da seçilen resimden) küçültülmüş JPEG üretir. */
  function grab(src, w, h) {
    const max = 1280; const k = Math.min(1, max / Math.max(w, h));
    canvas.width = Math.round(w * k); canvas.height = Math.round(h * k);
    const ctx = canvas.getContext('2d'); ctx.drawImage(src, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.72);
  }
  /** 16x16 gri imza → sahne değişmediyse canlı modda yeniden istek atma. */
  function signature() {
    const c = document.createElement('canvas'); c.width = 16; c.height = 16;
    const x = c.getContext('2d'); x.drawImage(video, 0, 0, 16, 16);
    const d = x.getImageData(0, 0, 16, 16).data; const s = [];
    for (let i = 0; i < d.length; i += 4) s.push((d[i] + d[i + 1] + d[i + 2]) / 3);
    return s;
  }
  const differs = (a, b) => !a || !b || a.reduce((n, v, i) => n + Math.abs(v - b[i]), 0) / a.length > 9;

  function render(res) {
    const blocks = (res && Array.isArray(res.blocks)) ? res.blocks : [];
    if (!blocks.length) { out.innerHTML = '<p class="cam-empty">Okunabilir yazı bulunamadı. Yazıya yaklaş ve net tut.</p>'; return; }
    out.innerHTML = blocks.map((b) => `<div class="cam-card"><div class="cam-src" dir="auto">${esc(b.text)}</div><div class="cam-tr" dir="auto">${esc(b.translation)}</div></div>`).join('');
  }

  async function translate(dataUrl, fromLive) {
    if (busy) return; busy = true;
    status('Çevriliyor…');
    const ctrl = new AbortController(); const to = setTimeout(() => ctrl.abort(), 30000);
    try {
      const r = await fetch('/api/camera/translate', { method: 'POST', signal: ctrl.signal, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: dataUrl, target: sel.value }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || 'Çeviri yapılamadı');
      const key = JSON.stringify((j.blocks || []).map((b) => b.text));
      if (!(fromLive && key === lastKey)) render(j);
      lastKey = key; status(j.blocks && j.blocks.length ? 'Tamam' : 'Yazı bulunamadı');
    } catch (e) {
      status(e && e.name === 'AbortError' ? 'Zaman aşımı — tekrar dene' : String(e.message || e));
    } finally { clearTimeout(to); busy = false; }
  }

  function snap() {
    if (!stream || !video.videoWidth) { status('Kamera hazır değil'); return; }
    const url = grab(video, video.videoWidth, video.videoHeight);
    translate(url, false);
  }
  function tick(force) {
    clearTimeout(timer);
    if (!live) return;
    const next = () => { if (live) timer = setTimeout(tick, 1500); };
    if (busy || !stream || !video.videoWidth) { next(); return; }
    const sig = signature();
    if (force !== true && !differs(sig, lastSig)) { next(); return; }
    lastSig = sig;
    translate(grab(video, video.videoWidth, video.videoHeight), true).finally(next);
  }

  $('camSnap').addEventListener('click', snap);
  $('camLive').addEventListener('click', () => {
    live = !live; const b = $('camLive'); b.textContent = `Canlı: ${live ? 'açık' : 'kapalı'}`; b.setAttribute('aria-pressed', String(live));
    b.classList.toggle('btn-primary', live);
    if (live) { lastSig = null; tick(true); } else clearTimeout(timer);
  });
  $('camFile').addEventListener('change', (e) => {
    const f = e.target.files && e.target.files[0]; if (!f) return;
    const img = new Image(); const u = URL.createObjectURL(f);
    img.onload = () => { const url = grab(img, img.naturalWidth, img.naturalHeight); URL.revokeObjectURL(u); translate(url, false); };
    img.onerror = () => status('Resim açılamadı');
    img.src = u; e.target.value = '';
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { stopCam(); clearTimeout(timer); } else if (!stream) startCam().then(() => { if (live) tick(true); });
  });
  window.addEventListener('pagehide', stopCam);
  startCam();
})();

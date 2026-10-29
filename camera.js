/* Kamera çeviri: (1) Fotoğraf/yazı → tam metin çeviri + sesli okuma. (2) Canlı altyazı → Gemini Live ile kareler anında çevrilip seslendirilir. */
(() => {
  'use strict';
  const LANGS = [
    ['tr', '🇹🇷 Türkçe'], ['en', '🇬🇧 English'], ['de', '🇩🇪 Deutsch'], ['fr', '🇫🇷 Français'], ['es', '🇪🇸 Español'],
    ['it', '🇮🇹 Italiano'], ['ru', '🇷🇺 Русский'], ['ar', '🇸🇦 العربية'], ['zh', '🇨🇳 中文'], ['ka', '🇬🇪 ქართული'], ['id', '🇮🇩 Bahasa Indonesia'],
  ];
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const video = $('camVideo'); const shot = $('camShot'); const canvas = $('camCanvas'); const sel = $('camTarget'); const out = $('camOut');
  const get = (k, d) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
  const set = (k, v) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } };
  let stream = null; let mode = 'photo'; let busy = false; let ttsSrc = null; let last = null;

  sel.innerHTML = LANGS.map(([c, n]) => `<option value="${c}">${n}</option>`).join('');
  sel.value = get('cam_target', 'tr'); $('camSound').checked = get('cam_sound', '1') === '1';
  sel.addEventListener('change', () => { set('cam_target', sel.value); if (live.on) liveStop(); });
  $('camSound').addEventListener('change', (e) => { set('cam_sound', e.target.checked ? '1' : '0'); if (!e.target.checked) stopSpeech(); });
  const status = (t) => { $('camStatusText').textContent = t; };
  const msg = (t) => { const m = $('camMsg'); m.textContent = t || ''; m.hidden = !t; };

  // ------------------------------------------------------------ kamera
  async function startCam() {
    if (stream) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { msg('Bu tarayıcıda kamera yok — “Fotoğraf seç” ile çevir'); return; }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false });
      video.srcObject = stream; await video.play().catch(() => {});
      msg(''); status('Hazır');
    } catch { msg('Kamera izni verilmedi — “Fotoğraf seç” ile de çevirebilirsin'); }
  }
  function stopCam() { if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; } }
  function grab(src, w, h, max = 1280, q = 0.72) {
    const k = Math.min(1, max / Math.max(w, h));
    canvas.width = Math.round(w * k); canvas.height = Math.round(h * k);
    canvas.getContext('2d').drawImage(src, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', q);
  }

  // ------------------------------------------------------------ ses (yazılı çeviriyi okuma)
  function stopSpeech() { if (ttsSrc) { try { ttsSrc.stop(); } catch { /* ignore */ } ttsSrc = null; } }
  async function speak(text, tl) {
    if (!text) return;
    try {
      stopSpeech();
      const c = LiveAudio.unlock();
      const r = await fetch('/api/tts?' + new URLSearchParams({ q: text.trim().slice(0, 1800), tl }));
      if (!r.ok) throw new Error('tts');
      const buf = await LiveAudio.audioCtx().decodeAudioData(await r.arrayBuffer());
      stopSpeech();
      ttsSrc = c.createBufferSource(); ttsSrc.buffer = buf; ttsSrc.connect(c.destination); ttsSrc.start();
    } catch { status('Ses oluşturulamadı — metin ekranda'); }
  }

  // ------------------------------------------------------------ fotoğraf modu
  function renderPhoto(j, tl) {
    last = { tr: j.translation || '', src: j.text || '', tl };
    if (!last.tr) { out.innerHTML = '<p class="cam-empty">Okunabilir yazı bulunamadı. Yazıya yaklaş, net ve aydınlık tut.</p>'; return; }
    out.innerHTML = `<article class="cam-main">
      <div class="cam-main-h"><b>Çeviri</b><span><button type="button" class="cam-mini" id="cmListen">🔊 Dinle</button><button type="button" class="cam-mini" id="cmCopy">Kopyala</button></span></div>
      <div class="cam-main-tr" dir="auto">${esc(last.tr).replace(/\n/g, '<br>')}</div>
      <details class="cam-orig"><summary>Orijinal metin${j.lang ? ' (' + esc(j.lang) + ')' : ''}</summary><div dir="auto">${esc(last.src).replace(/\n/g, '<br>')}</div></details>
    </article>`;
    $('cmListen').addEventListener('click', () => speak(last.tr, tl));
    $('cmCopy').addEventListener('click', async () => { try { await navigator.clipboard.writeText(last.tr); status('Kopyalandı'); } catch { status('Kopyalanamadı'); } });
  }
  async function translatePhoto(dataUrl) {
    if (busy) return; busy = true;
    shot.src = dataUrl; shot.hidden = false; $('camAgain').hidden = false; $('camSnap').hidden = true;
    status('Çevriliyor…'); out.innerHTML = '<p class="cam-empty">Çevriliyor…</p>';
    const tl = sel.value; const ctrl = new AbortController(); const to = setTimeout(() => ctrl.abort(), 35000);
    try {
      let r; let j = {};
      for (let a = 0; a < 2; a += 1) { // geçici hata → bir kez daha dene
        r = await fetch('/api/camera/translate', { method: 'POST', signal: ctrl.signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image: dataUrl, target: tl }) });
        j = await r.json().catch(() => ({}));
        if (r.ok || r.status < 500) break;
      }
      if (!r.ok) throw new Error(j.error || 'Çeviri yapılamadı');
      renderPhoto(j, tl); status(j.translation ? 'Tamam' : 'Yazı bulunamadı');
      if (j.translation && $('camSound').checked) speak(j.translation, tl);
    } catch (e) {
      out.innerHTML = ''; status(e && e.name === 'AbortError' ? 'Zaman aşımı — tekrar dene' : String(e.message || e));
    } finally { clearTimeout(to); busy = false; }
  }
  function again() { stopSpeech(); shot.hidden = true; $('camAgain').hidden = true; $('camSnap').hidden = false; out.innerHTML = ''; status('Hazır'); }
  $('camSnap').addEventListener('click', () => {
    LiveAudio.unlock();
    if (!stream || !video.videoWidth) { status('Kamera hazır değil — “Fotoğraf seç”i dene'); return; }
    translatePhoto(grab(video, video.videoWidth, video.videoHeight));
  });
  $('camAgain').addEventListener('click', again);
  $('camFile').addEventListener('change', (e) => {
    const f = e.target.files && e.target.files[0]; if (!f) return;
    LiveAudio.unlock();
    const img = new Image(); const u = URL.createObjectURL(f);
    img.onload = () => { const url = grab(img, img.naturalWidth, img.naturalHeight, 1600, 0.78); URL.revokeObjectURL(u); translatePhoto(url); };
    img.onerror = () => status('Resim açılamadı');
    img.src = u; e.target.value = '';
  });

  // ------------------------------------------------------------ canlı altyazı (Gemini Live: kare + ipucu → anında sesli çeviri)
  const live = { on: false, session: null, player: null, gen: false, pending: false, timer: null, sig: null, sent: null, stable: 0, buf: '', lastSend: 0, lines: [], count: 0 };
  // 48x36 ızgara, ortalaması çıkarılmış parlaklık: ince yazı/altyazı değişimi de yakalanır, pozlama kayması etkilemez
  const sigOf = () => {
    const c = document.createElement('canvas'); c.width = 48; c.height = 36;
    const x = c.getContext('2d'); x.drawImage(video, 0, 0, 48, 36);
    const d = x.getImageData(0, 0, 48, 36).data; const s = []; let m = 0;
    for (let i = 0; i < d.length; i += 4) { const v = (d[i] + d[i + 1] + d[i + 2]) / 3; s.push(v); m += v; }
    m /= s.length; return s.map((v) => v - m);
  };
  // iki imza arasında belirgin değişen hücre oranı
  const dist = (a, b) => (!a || !b ? 1 : a.reduce((n, v, i) => n + (Math.abs(v - b[i]) > 28 ? 1 : 0), 0) / a.length);

  function liveLines() {
    out.innerHTML = live.lines.length
      ? live.lines.map((t, i) => `<article class="cam-line${i === 0 ? ' is-new' : ''}" dir="auto">${esc(t)}</article>`).join('')
      : '<p class="cam-empty">Altyazıya ya da yazıya tut — çeviri anında okunur.</p>';
  }
  async function trigger() {
    const s = live.session; if (!s || !stream || !video.videoWidth) return;
    live.lastSend = Date.now(); live.act = 0; live.sent = live.sig; live.pending = false;
    // her ~18 çeviride oturumu yenile (bağlam şişmesin, gecikme artmasın)
    if (live.count >= 18) { try { s.close(); } catch { /* ignore */ } live.count = 0; }
    try { if (!s.isOpen) await s.connect(); } catch { status('Bağlantı kurulamadı'); return; }
    live.player.stop(); live.buf = ''; live.gen = true; live.count += 1;
    const url = grab(video, video.videoWidth, video.videoHeight, 1024, 0.72);
    // kare ve ipucu AYNI turda → model kareyi görmeden cevap vermez
    s.send({ clientContent: { turns: [{ role: 'user', parts: [{ inlineData: { mimeType: 'image/jpeg', data: url.split(',')[1] } }, { text: '[ÇEVİR]' }] }], turnComplete: true } });
    status('Çevriliyor…');
  }
  function liveFinish() {
    live.gen = false;
    const t = live.buf.replace(/\s+/g, ' ').trim(); live.buf = '';
    if (t && t !== '.' && t !== live.lines[0]) { live.lines.unshift(t); live.lines = live.lines.slice(0, 8); liveLines(); }
    status(live.on ? 'Dinliyor… yazıya tut' : 'Hazır');
    if (live.pending && live.on) trigger();
  }
  function loop() {
    if (!live.on) return;
    live.timer = setTimeout(loop, 300);
    // yanıt "bitti" sinyali gelmezse takılı kalma: sessizlik 2.5 sn ya da toplam 7 sn → bitmiş say
    if (live.gen) {
      const now = Date.now();
      if ((live.act && now - live.act > 2500) || now - live.lastSend > 7000) liveFinish();
    }
    if (!stream || !video.videoWidth) return;
    const sig = sigOf(); const moving = dist(sig, live.sig) > 0.12; live.sig = sig;
    live.stable = moving ? 0 : live.stable + 1;
    const since = Date.now() - live.lastSend;
    const changed = dist(sig, live.sent);
    // elde tutarken görüntü hiç "oturmayabilir": oturduysa hemen, oturmadıysa en geç 2 sn'de bir (değişiklik varsa) gönder
    const go = !live.sent || (live.stable >= 2 && changed > 0.012) || (since > 2000 && changed > 0.06);
    if (!go) return;
    if (live.gen) { live.pending = true; return; }
    if (since < 700) return;
    trigger();
  }
  async function liveStart() {
    LiveAudio.unlock();
    await startCam();
    if (!stream) return;
    live.player = new LiveAudio.Player({});
    live.session = new LiveAudio.Session({
      body: () => ({ kind: 'camera', target: sel.value }),
      onAudio: (u8, rate) => { live.act = Date.now(); if ($('camSound').checked) live.player.enqueue(u8, rate); },
      onOutput: (t) => { live.act = Date.now(); live.buf += t; },
      onTurnComplete: liveFinish,
      onGenerationComplete: () => { if (live.gen) setTimeout(() => { if (live.gen && Date.now() - (live.act || 0) > 600) liveFinish(); }, 700); },
      onInterrupted: () => {},
      onState: (st) => { if (st === 'error') status('Bağlantı hatası — tekrar dene'); },
    });
    live.on = true; live.sig = null; live.sent = null; live.stable = 0; live.lines = []; liveLines();
    $('camLive').textContent = '■ Durdur'; $('camLiveDot').hidden = false; status('Bağlanıyor…');
    try { await live.session.connect(); status('Dinliyor… yazıya tut'); } catch (e) { status(String(e.message || e)); }
    loop();
  }
  function liveStop() {
    live.on = false; clearTimeout(live.timer);
    try { if (live.player) live.player.stop(); } catch { /* ignore */ }
    try { if (live.session) live.session.close(); } catch { /* ignore */ }
    live.session = null; live.gen = false;
    $('camLive').textContent = '▶ Canlı çeviriyi başlat'; $('camLiveDot').hidden = true; status('Hazır');
  }
  $('camLive').addEventListener('click', () => (live.on ? liveStop() : liveStart()));

  function setMode(m) {
    mode = m; const photo = m === 'photo';
    $('tabPhoto').classList.toggle('is-on', photo); $('tabLive').classList.toggle('is-on', !photo);
    $('tabPhoto').setAttribute('aria-selected', String(photo)); $('tabLive').setAttribute('aria-selected', String(!photo));
    $('barPhoto').hidden = !photo; $('barLive').hidden = photo;
    $('camTag').textContent = photo ? 'Yazıya tut, çevirsin ve okusun' : 'Altyazı / konuşma yazısı: saniyeler içinde sesli çeviri';
    if (photo) { liveStop(); again(); } else { stopSpeech(); shot.hidden = true; liveLines(); }
  }
  $('tabPhoto').addEventListener('click', () => setMode('photo'));
  $('tabLive').addEventListener('click', () => setMode('live'));

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { liveStop(); stopCam(); } else if (!stream) startCam();
  });
  window.addEventListener('pagehide', () => { liveStop(); stopCam(); });
  startCam();
})();

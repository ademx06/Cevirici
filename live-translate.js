/* Canlı tercüman — Eğitimdeki aynı Gemini Live modeli (tercüman talimatıyla)
 *
 * Çeviri (translate.html): iki bas-konuş düğmesi. Bas → anında kayıt, bırak → ~1 sn'de sesli çeviri.
 *   Her yön için hazır bekleyen bir oturum (elle başlat/bitir — eğitimdeki gibi). Her basış = yeni kutucuk.
 * Karşılıklı (live-talk.html): eller serbest — tek oturum, iki yönlü; kim hangi dilde konuşursa diğerine çevrilir.
 */
(function () {
  'use strict';

  const LANGS = [
    { code: 'tr', name: 'Türkçe', flag: '🇹🇷' }, { code: 'en', name: 'English', flag: '🇬🇧' },
    { code: 'de', name: 'Deutsch', flag: '🇩🇪' }, { code: 'fr', name: 'Français', flag: '🇫🇷' },
    { code: 'es', name: 'Español', flag: '🇪🇸' }, { code: 'it', name: 'Italiano', flag: '🇮🇹' },
    { code: 'ru', name: 'Русский', flag: '🇷🇺' }, { code: 'ar', name: 'العربية', flag: '🇸🇦' },
    { code: 'zh', name: '中文', flag: '🇨🇳' }, { code: 'ka', name: 'ქართული', flag: '🇬🇪' },
  ];
  const HOLD = { tr: 'Basılı tut, konuş', en: 'Hold to speak', de: 'Gedrückt halten', fr: 'Maintenir pour parler',
    es: 'Mantén para hablar', it: 'Tieni premuto', ru: 'Удерживай', ar: 'اضغط مطولاً', zh: '按住说话', ka: 'დააჭირე და ილაპარაკე' };
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const lang = (c) => LANGS.find((l) => l.code === c) || LANGS[0];
  const PAGE = $('ltToggle') ? 'talk' : 'translate';
  const KEY = PAGE === 'talk' ? 'lt_langs_v2' : 'tr_langs_v2';
  const SILENCE = new Uint8Array(3200); // 100 ms @16 kHz
  // Sessiz / kısa basışta Live'ın uydurduğu dolgular (eğitimdeki gibi atılır)
  const FILLER_RE = /^(¿\s*)?(qué|que|what|huh|hmm+|m+h?m+|uh+|um+|ah+|oh+|eh+|hä|ähm|quoi|cosa)(\s*[?.!]*)?$/i;

  let prefs = { my: 'tr', other: 'en' };
  try { prefs = Object.assign(prefs, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch { /* ignore */ }
  const savePrefs = () => { try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* ignore */ } };

  const ids = PAGE === 'talk'
    ? { my: 'ltMyLang', other: 'ltOtherLang', swap: 'ltSwapBtn', status: 'ltStatusText', dot: 'ltStatusDot', err: 'ltErrorBox', msgs: 'ltMessages', clear: 'ltClearBtn' }
    : { my: 'myLang', other: 'otherLang', swap: 'swapBtn', status: 'statusText', dot: 'statusDot', err: 'errorBox', msgs: 'messages', clear: 'clearBtn' };

  // ---------------------------------------------------------------- state
  const player = new LiveAudio.Player({ onStart: () => setStatus('Çeviri seslendiriliyor…', true), onIdle: () => idle() });
  const sessions = {}; // key → Session   (translate: 'toOther' / 'toMine'; talk: 'both')
  const bubbles = []; // {dir, from, to, orig, trans, done, okunus, audio:[], rate, listening}
  const cur = {}; // session key → bubble that receives this session's current turn
  let mic = null;
  let holdDir = null;
  let handsFree = false;
  let pending = [];
  let micBusy = false;
  let turnReady = null;

  function setStatus(t, live = false) { $(ids.status).textContent = t; $(ids.dot).classList.toggle('active', !!live); }
  function idle() {
    if (holdDir) return;
    if (handsFree) { setStatus('Dinliyorum — konuşabilirsiniz', true); return; }
    setStatus(PAGE === 'talk' ? 'Başlat\'a bas, sırayla konuşun' : 'Hangi dilde konuşacaksan o düğmeye basılı tut', false);
  }
  function showErr(t) { const b = $(ids.err); if (!b) return; b.textContent = t; b.classList.toggle('hidden', !t); }

  function targetOf(dir) { return dir === 'toOther' ? prefs.other : prefs.my; }
  function sourceOf(dir) { return dir === 'toOther' ? prefs.my : prefs.other; }

  // ---------------------------------------------------------------- dil tahmini (eller serbestte yön etiketi için)
  const HINTS = {
    tr: /[çğıöşüÇĞİÖŞÜ]|\b(ve|bir|bu|ne|nasıl|evet|hayır|merhaba|teşekkür\w*|ben|sen|biz|var|yok|mı|mi|değil|için|çok)\b/gi,
    en: /\b(the|is|are|you|i|and|to|what|how|yes|no|hello|thanks?|my|your|this|that|do|can|please)\b/gi,
    de: /[äöüßÄÖÜ]|\b(ich|und|der|die|das|ist|nicht|du|sie|wir|ja|nein|danke|bitte|wie|was)\b/gi,
    fr: /[éèêàçù]|\b(je|tu|le|la|les|est|et|vous|oui|non|merci|bonjour|que|pas|une?)\b/gi,
    es: /[ñ¿¡áéíóú]|\b(el|la|que|y|es|sí|no|gracias|hola|yo|tú|por|para|una?)\b/gi,
    it: /[àèìòù]|\b(il|che|è|sono|non|grazie|ciao|io|tu|per|una?|lo|gli)\b/gi,
    ru: /[а-яё]/gi, ar: /[؀-ۿ]/g, zh: /[一-鿿]/g, ka: /[Ⴀ-ჿ]/g,
  };
  const score = (text, code) => ((String(text || '').match(HINTS[code] || /$^/g) || []).length);
  function guessDir(orig, trans) {
    const d = (score(orig, prefs.my) - score(orig, prefs.other)) + (score(trans, prefs.other) - score(trans, prefs.my));
    return d >= 0 ? 'toOther' : 'toMine';
  }

  function isFiller(t) {
    const s = String(t || '').trim();
    if (!s) return true;
    return FILLER_RE.test(s);
  }

  // ---------------------------------------------------------------- oturumlar
  function session(key) {
    if (sessions[key]) return sessions[key];
    // Eğitimdeki gibi: bas-konuş elle (vad:false); karşılıklı otomatik algılama (vad:true)
    const body = key === 'both'
      ? () => ({ kind: 'interpret', source: prefs.my, target: prefs.other, both: true, vad: true })
      : () => ({ kind: 'interpret', source: sourceOf(key), target: targetOf(key), vad: false });
    const s = new LiveAudio.Session({
      body,
      onInput: (t) => {
        const chunk = String(t || '');
        let b = cur[key];
        if (key === 'both' && (!b || b.trans)) b = newBubble('both', 'toOther');
        if (!b) return;
        const next = (b.orig + chunk).replace(/\s+/g, ' ');
        // Tek başına dolgu (¿Qué?) yazma — uydurma metin gösterme
        if (!b.orig.trim() && isFiller(next)) return;
        b.orig = next;
        b._heard = true;
        if (key === 'both') retarget(b);
        renderSoon();
      },
      onOutput: (t) => {
        const chunk = String(t || '');
        let b = cur[key];
        if (!b || b.done) b = newBubble(key, key === 'both' ? 'toOther' : key);
        const next = (b.trans + chunk).replace(/\s+/g, ' ');
        if (!b.trans.trim() && isFiller(next) && !b.orig.trim() && !(b.audio && b.audio.length)) return;
        b.trans = next;
        b.listening = false;
        if (key === 'both') retarget(b);
        renderSoon();
      },
      onAudio: (u8, rate) => {
        let b = cur[key];
        if (!b || b.done) b = newBubble(key, key === 'both' ? 'toOther' : key);
        b.audio.push(u8); b.rate = rate;
        b._heard = true;
        LiveAudio.unlock();
        player.enqueue(u8, rate);
      },
      onInterrupted: () => { player.stop(); },
      onTurnComplete: () => { if (holdDir !== key) finalize(key); },
      onState: (st, info) => {
        if (st === 'error') showErr(String(info || 'Canlı bağlantı kurulamadı'));
        if ((st === 'closed' || st === 'goaway') && document.visibilityState === 'visible' && sessions[key] === s) {
          setTimeout(() => { if (sessions[key] === s) s.connect().catch(() => {}); }, 1200);
        }
      },
    });
    sessions[key] = s;
    return s;
  }
  function closeAll() {
    Object.keys(sessions).forEach((k) => { const s = sessions[k]; delete sessions[k]; try { s.close(); } catch { /* ignore */ } });
  }

  function newBubble(key, dir) {
    if (cur[key]) finalize(key);
    const b = { dir, from: sourceOf(dir), to: targetOf(dir), orig: '', trans: '', done: false, okunus: '', audio: [], rate: 24000, listening: false, t: Date.now() };
    bubbles.push(b);
    cur[key] = b;
    renderSoon();
    return b;
  }
  function retarget(b) {
    const dir = guessDir(b.orig, b.trans);
    if (dir !== b.dir) { b.dir = dir; b.from = sourceOf(dir); b.to = targetOf(dir); lastSig = ''; }
  }
  async function finalize(key) {
    const b = cur[key];
    if (!b) return;
    cur[key] = null;
    b.listening = false;
    const orig = (b.orig || '').trim();
    const trans = (b.trans || '').trim();
    // Boş / dolgu turu (¿Qué?) — kutucuğu ve sesi at (eğitimdeki boş mesaj silme gibi)
    if ((!orig && !trans) || (isFiller(orig) && (!trans || isFiller(trans))) || (isFiller(trans) && !orig && !(b.audio && b.audio.length))) {
      player.stop();
      const i = bubbles.indexOf(b);
      if (i >= 0) bubbles.splice(i, 1);
      renderSoon();
      return;
    }
    if (isFiller(trans) && orig) b.trans = '';
    b.done = true;
    renderSoon();
    if (b.to !== 'tr' && b.trans.trim()) {
      const q = b.trans.trim().slice(0, 400);
      void fetch('/api/pronounce?' + new URLSearchParams({ q, lang: b.to }))
        .then((r) => r.json())
        .then((d) => { b.okunus = d.phonetic || ''; renderSoon(); })
        .catch(() => {});
    }
  }

  /** Yazılı çeviri sesi — hızlı Google TTS + blob (uzun URL / nöral gecikme yok). Live yapısına dokunmaz. */
  async function playTypedTts(text, lang) {
    const q = (text || '').trim().slice(0, 1800);
    if (!q) return;
    LiveAudio.unlock();
    try {
      const r = await fetch('/api/tts?' + new URLSearchParams({ q, tl: lang }));
      if (!r.ok) return;
      const blob = await r.blob();
      if (!blob.size) return;
      const u = URL.createObjectURL(blob);
      const au = new Audio(u);
      au.onended = () => { URL.revokeObjectURL(u); LiveAudio.unlock(); };
      au.onerror = () => { URL.revokeObjectURL(u); LiveAudio.unlock(); };
      await au.play();
    } catch { /* ignore */ }
  }

  // ---------------------------------------------------------------- render (yerinde güncelleme → titreme yok)
  let rp = false;
  let lastSig = '';
  function sig() { return bubbles.map((b, i) => `${i}:${b.dir}:${b.done ? 1 : 0}:${b.okunus ? 1 : 0}`).join('|'); }
  function origText(b) { return b.orig || (b.listening ? (b._heard ? '🎙️ Seni duyuyorum…' : '🎙️ Dinliyorum…') : '…'); }
  function renderSoon() {
    if (rp) return; rp = true;
    requestAnimationFrame(() => {
      rp = false;
      if (sig() !== lastSig) { render(); return; }
      const el = $(ids.msgs);
      bubbles.forEach((b, i) => {
        const a = el.querySelector(`[data-b="${i}"]`);
        if (!a) return;
        const o = a.querySelector('.bubble-original'); const t = a.querySelector('.bubble-translated');
        if (o && o.textContent !== origText(b)) o.textContent = origText(b);
        const tt = b.trans || (b.orig && !b.done ? 'Çevriliyor…' : '');
        if (t && t.textContent !== tt) t.textContent = tt;
      });
    });
  }
  function render() {
    lastSig = sig();
    const el = $(ids.msgs);
    if ($(ids.clear)) $(ids.clear).classList.toggle('hidden', !bubbles.length);
    if (!bubbles.length) {
      el.innerHTML = `<div class="empty-state"><div class="empty-icon"></div>
        <h2>${PAGE === 'talk' ? 'Konuşun, anında çevireyim' : 'Basılı tut ve konuş'}</h2>
        <p>${PAGE === 'talk' ? 'Başlat\'a bas, telefonu ortaya koy. Kim hangi dilde konuşursa, susunca diğer dile sesli çevrilir.' : 'Bastığın an dinlemeye başlar; bırakınca çeviri hemen sesli gelir.'}</p></div>`;
      return;
    }
    el.innerHTML = bubbles.slice().reverse().map((b) => {
      const f = lang(b.from), t = lang(b.to);
      const i = bubbles.indexOf(b);
      const tt = b.trans || (b.orig && !b.done ? 'Çevriliyor…' : '');
      return `<article class="bubble ${b.dir === 'toOther' ? 'me' : 'other'} ${b.done ? '' : 'is-live'}" data-b="${i}">
        <div class="bubble-label">${f.flag} ${esc(f.name)}</div>
        <div class="bubble-original"${b.from === 'ar' ? ' dir="rtl"' : ''}>${esc(origText(b))}</div>
        <div class="bubble-divider"></div>
        <div class="bubble-label">${t.flag} ${esc(t.name)}</div>
        <div class="bubble-translated"${b.to === 'ar' ? ' dir="rtl"' : ''}>${esc(tt)}</div>
        ${b.okunus ? `<div class="bubble-phonetic"><b>Okunuş</b> · ${esc(b.okunus)}</div>` : ''}
        ${b.done && b.audio.length ? `<button type="button" class="replay-btn" data-replay="${i}">▶ Tekrar dinle</button>` : ''}
      </article>`;
    }).join('');
  }
  $(ids.msgs).addEventListener('click', (e) => {
    const r = e.target.closest('[data-replay]');
    if (!r) return;
    LiveAudio.unlock();
    const b = bubbles[Number(r.dataset.replay)];
    if (b) player.replay(b.audio, b.rate);
  });

  // ---------------------------------------------------------------- languages
  function fillSelects() {
    [$(ids.my), $(ids.other)].forEach((sel) => {
      sel.innerHTML = LANGS.map((l) => `<option value="${l.code}">${l.flag} ${esc(l.name)}</option>`).join('');
    });
    $(ids.my).value = prefs.my; $(ids.other).value = prefs.other;
    syncLabels();
  }
  function syncLabels() {
    const m = lang(prefs.my), o = lang(prefs.other);
    if (PAGE === 'translate') {
      $('micTitleMy').textContent = `${m.flag} ${m.name}`; $('micActionMy').textContent = HOLD[m.code] || 'Basılı tut';
      $('micTitleOther').textContent = `${o.flag} ${o.name}`; $('micActionOther').textContent = HOLD[o.code] || 'Basılı tut';
    } else {
      $('ltPair').textContent = `${m.flag} ${m.name}  ⇄  ${o.flag} ${o.name}`;
    }
  }
  function onLangChange() {
    if (prefs.my === prefs.other) prefs.other = prefs.my === 'en' ? 'tr' : 'en';
    const wasHF = handsFree;
    savePrefs(); stopAll(); closeAll(); fillSelects(); preconnect();
    if (wasHF) void startHandsFree();
  }
  $(ids.my).addEventListener('change', (e) => { prefs.my = e.target.value; onLangChange(); });
  $(ids.other).addEventListener('change', (e) => { prefs.other = e.target.value; onLangChange(); });
  $(ids.swap).addEventListener('click', () => { [prefs.my, prefs.other] = [prefs.other, prefs.my]; onLangChange(); });
  if ($(ids.clear)) $(ids.clear).addEventListener('click', () => { bubbles.length = 0; Object.keys(cur).forEach((k) => { cur[k] = null; }); render(); });

  function preconnect() {
    // Bağlantıyı önceden kur → basınca bekleme olmasın
    const keys = PAGE === 'talk' ? ['both'] : ['toOther', 'toMine'];
    keys.forEach((k) => { session(k).connect().catch(() => {}); });
  }

  // ---------------------------------------------------------------- ilk basış: yalnızca mikrofon izni
  async function ensureMicFor(btn) {
    if (LiveAudio.micReady()) return true;
    micBusy = true;
    btn.classList.add('arming');
    let perm = 'unknown';
    try { perm = await LiveAudio.micPermission(); } catch { /* ignore */ }
    if (perm !== 'granted') setStatus('Mikrofon izni isteniyor… “İzin ver”e dokun', true);
    const t0 = performance.now();
    try { await LiveAudio.openMic(); } catch (e) {
      micBusy = false; btn.classList.remove('arming');
      showErr(e && e.name === 'NotAllowedError' ? 'Mikrofon izni gerekli (Ayarlar → Safari → Mikrofon)' : 'Mikrofon açılamadı');
      idle(); return false;
    }
    micBusy = false; btn.classList.remove('arming');
    if (perm !== 'granted' || performance.now() - t0 > 900 || !btn._held) {
      setStatus('Mikrofon hazır ✓ — şimdi basılı tutup konuş', true);
      setTimeout(() => { if (!holdDir) idle(); }, 2500);
      return false;
    }
    return true;
  }

  // ---------------------------------------------------------------- bas-konuş (Çeviri) — eğitimdeki yapı
  async function holdStart(btn, dir) {
    if (holdDir || micBusy) return;
    LiveAudio.unlock();
    showErr('');
    if (!(await ensureMicFor(btn))) return;
    if (!btn._held) return;
    holdDir = dir; pending = [];
    btn._holdT0 = performance.now();
    player.stop();
    btn.classList.add('recording');
    setStatus(`Dinliyorum — ${lang(sourceOf(dir)).name} konuş`, true);
    const b = newBubble(dir, dir); b.listening = true; b._heard = false; renderSoon();
    const s = session(dir);
    s._activity = false;
    turnReady = s.connect().then(() => {
      s.activityStart(); s._activity = true;
      const q = pending; pending = []; q.forEach((c) => s.sendAudio(c));
    });
    turnReady.catch((e) => holdAbort(btn, (e && e.message) || 'Canlı bağlantı kurulamadı'));
    mic = new LiveAudio.Mic({
      onChunk: (u8) => { if (s.isOpen && s._activity && !pending.length) s.sendAudio(u8); else pending.push(u8); },
      onLevel: (lv) => {
        btn.style.setProperty('--lv', Math.min(1, lv * 3).toFixed(2));
        if (lv > 0.06 && b.listening && !b._heard) { b._heard = true; renderSoon(); }
      },
    });
    mic.start().catch((e) => holdAbort(btn, e && e.name === 'NotAllowedError' ? 'Mikrofon izni gerekli' : 'Mikrofon açılamadı'));
  }
  function holdAbort(btn, msg) {
    const d = holdDir; holdDir = null;
    if (mic) { mic.stop(); mic = null; }
    btn.classList.remove('recording', 'arming');
    // activityEnd yok — uydurma cevap tetiklenmesin
    const s = d && sessions[d];
    if (s) s._activity = false;
    if (d) {
      const b = cur[d];
      cur[d] = null;
      if (b) {
        const i = bubbles.indexOf(b);
        if (i >= 0) bubbles.splice(i, 1);
      }
      renderSoon();
    }
    if (msg) showErr(msg);
    idle();
  }
  async function holdEnd(btn) {
    if (!holdDir) return;
    const dir = holdDir; holdDir = null;
    btn.classList.remove('recording', 'arming');
    btn.style.removeProperty('--lv');
    const b = cur[dir]; if (b) { b.listening = false; renderSoon(); }
    const holdMs = performance.now() - (btn._holdT0 || 0);
    const m = mic; mic = null;
    if (m) await m.stop();
    const s = sessions[dir];
    try { await turnReady; } catch { return; }
    if (!s || !s.isOpen) return;
    // Eğitim gibi: ses yoksa / çok kısa basışta Gemini'ye bitiş gönderme → ¿Qué? uydurmasın
    if (!b || (!b._heard && holdMs < 450)) {
      s._activity = false;
      cur[dir] = null;
      const i = b ? bubbles.indexOf(b) : -1;
      if (i >= 0) bubbles.splice(i, 1);
      renderSoon();
      setStatus('Seni duyamadım — basılı tutup konuş');
      setTimeout(() => { if (!holdDir) idle(); }, 2200);
      return;
    }
    setStatus('Çeviriliyor…', true);
    if (pending.length) { const q = pending; pending = []; q.forEach((c) => s.sendAudio(c)); }
    s.activityEnd(); s._activity = false;
    setTimeout(() => {
      if (cur[dir] === b && b && !b.orig.trim() && !b.trans.trim() && !(b.audio && b.audio.length)) {
        finalize(dir);
        setStatus('Seni duyamadım — basılı tutup tekrar konuş');
      }
    }, 6000);
  }
  function bindHold(btn, dirFn) {
    if (!btn) return;
    let touchUsed = false;
    const down = (e) => { e.preventDefault(); btn._held = true; void holdStart(btn, dirFn()); };
    const up = (e) => { e.preventDefault(); btn._held = false; void holdEnd(btn); };
    btn.addEventListener('contextmenu', (e) => e.preventDefault());
    btn.addEventListener('touchstart', (e) => { touchUsed = true; down(e); }, { passive: false });
    btn.addEventListener('touchend', up, { passive: false });
    btn.addEventListener('touchcancel', up, { passive: false });
    btn.addEventListener('mousedown', (e) => { if (!touchUsed) down(e); });
    btn.addEventListener('mouseup', (e) => { if (!touchUsed) up(e); });
    btn.addEventListener('mouseleave', (e) => { if (!touchUsed && holdDir) up(e); });
  }

  // ---------------------------------------------------------------- eller serbest (Karşılıklı) — tek oturum, iki yön
  async function startHandsFree() {
    LiveAudio.unlock();
    showErr('');
    handsFree = true;
    $('ltToggle').classList.add('recording');
    $('ltToggleText').textContent = 'Durdur';
    setStatus(LiveAudio.micReady() ? 'Bağlanıyor…' : 'Mikrofon izni isteniyor…', true);
    const s = session('both');
    try {
      await LiveAudio.openMic();
      if (!handsFree) return;
      mic = new LiveAudio.Mic({
        preroll: false,
        // çeviri sesi çalarken sessizlik gönder → kendi çevirisini tekrar çevirmesin
        onChunk: (u8) => { if (s.isOpen) s.sendAudio(player.playing ? SILENCE : u8); },
        onLevel: (lv) => { const m = $('ltMeter'); if (m) m.style.transform = `scale(${1 + Math.min(0.6, player.playing ? 0 : lv * 2.5)})`; },
      });
      await Promise.all([mic.start(), s.connect()]);
      if (handsFree) setStatus('Dinliyorum — konuşabilirsiniz', true);
    } catch (e) {
      stopHandsFree();
      showErr(e && e.name === 'NotAllowedError' ? 'Mikrofon izni gerekli' : ((e && e.message) || 'Canlı bağlantı kurulamadı'));
    }
  }
  function stopHandsFree() {
    handsFree = false;
    if (mic) { mic.stop(); mic = null; }
    const t = $('ltToggle'); if (t) t.classList.remove('recording');
    const tt = $('ltToggleText'); if (tt) tt.textContent = 'Başlat';
    const s = sessions.both; if (s && s.isOpen) s.streamEnd();
    idle();
  }
  function stopAll() { if (handsFree) stopHandsFree(); if (mic) { mic.stop(); mic = null; } holdDir = null; player.stop(); }

  // ---------------------------------------------------------------- yazılı çeviri (Çeviri sayfası)
  async function translateTyped() {
    const inp = $('translateTextInput');
    const text = (inp.value || '').trim();
    if (!text) return;
    inp.value = '';
    LiveAudio.unlock();
    setStatus('Çeviriliyor…', true);
    try {
      const r = await fetch('/api/translate?' + new URLSearchParams({ q: text, from: prefs.my, to: prefs.other, my: prefs.my, other: prefs.other }));
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Çeviri başarısız');
      const dir = d.from === prefs.my ? 'toOther' : 'toMine';
      const b = { dir, from: d.from, to: d.to, orig: text, trans: d.text, done: true, okunus: '', audio: [], rate: 24000 };
      bubbles.push(b); render();
      // Ses hemen (hızlı TTS); okunuş arka planda — Live oturumuna dokunulmaz
      await playTypedTts(d.text, d.to);
      if (d.to !== 'tr' && (d.text || '').trim()) {
        void fetch('/api/pronounce?' + new URLSearchParams({ q: d.text.trim().slice(0, 400), lang: d.to }))
          .then((r) => r.json())
          .then((p) => { b.okunus = p.phonetic || ''; render(); })
          .catch(() => {});
      }
      idle();
    } catch (e) { showErr(e.message || 'Çeviri başarısız'); idle(); }
  }

  // ---------------------------------------------------------------- boot
  fillSelects();
  render();
  idle();
  if (!(window.WebSocket && window.AudioWorkletNode && navigator.mediaDevices)) {
    showErr('Bu tarayıcı canlı sesi desteklemiyor — Safari/Chrome güncel sürüm gerekir.');
  }
  if (PAGE === 'translate') {
    bindHold($('micBtnMy'), () => 'toOther');
    bindHold($('micBtnOther'), () => 'toMine');
    $('translateSendBtn').addEventListener('click', () => void translateTyped());
    $('translateTextInput').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); void translateTyped(); } });
  } else {
    $('ltToggle').addEventListener('click', () => { if (handsFree) stopHandsFree(); else void startHandsFree(); });
  }
  preconnect();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') stopAll();
    else preconnect();
  });
})();

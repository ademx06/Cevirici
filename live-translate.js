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
    { code: 'id', name: 'Bahasa Indonesia', flag: '🇮🇩' },
  ];
  const HOLD = { tr: 'Basılı tut, konuş', en: 'Hold to speak', de: 'Gedrückt halten', fr: 'Maintenir pour parler',
    es: 'Mantén para hablar', it: 'Tieni premuto', ru: 'Удерживай', ar: 'اضغط مطولاً', zh: '按住说话', ka: 'დააჭირე და ილაპარაკე', id: 'Tahan untuk bicara' };
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
  let lastPlayEnd = 0;
  const player = new LiveAudio.Player({ onStart: () => setStatus('Çeviri seslendiriliyor…', true), onIdle: () => { lastPlayEnd = performance.now(); idle(); } });
  const sessions = {}; // key → Session   (translate: 'toOther' / 'toMine'; talk: 'both')
  const bubbles = []; // {dir, from, to, orig, trans, done, okunus, audio:[], rate, listening}
  const cur = {}; // session key → bubble that receives this session's current turn
  let mic = null;
  let holdDir = null;
  let handsFree = false;
  let turn = null;
  let micBusy = false;

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
    id: /\b(saya|aku|kamu|anda|yang|dan|di|ke|dari|ini|itu|tidak|bukan|ada|apa|bagaimana|dengan|untuk|terima|kasih|selamat|halo|ya|sangat|sudah|bisa|mau)\b/gi,
  };
  const score = (text, code) => ((String(text || '').match(HINTS[code] || /$^/g) || []).length);
  function guessDir(orig, trans) {
    const d = (score(orig, prefs.my) - score(orig, prefs.other)) + (score(trans, prefs.other) - score(trans, prefs.my));
    return d >= 0 ? 'toOther' : 'toMine';
  }

  // Canlı döküm bazı dillerde (özellikle Gürcüce) yanlış alfabede gelir → o konuşmanın kaydı sunucuda yazıya dökülüp orijinal metin düzeltilir
  const SCRIPT = { ka: /[\u10A0-\u10FF]/, ru: /[\u0400-\u04FF]/, ar: /[\u0600-\u06FF]/, zh: /[\u4e00-\u9fff]/ };
  const FOREIGN = /[\u0590-\u05FF\u0900-\u0E7F\u1000-\u109F\u3040-\u30FF\uAC00-\uD7AF]/; // Latin dışı, çiftte hiç olmayan alfabeler (Hintçe, Tayca…)
  const hfBuf = []; // el serbest: {t, u8} son ~40 sn gönderilen ses
  function hfPush(u8) { const n = performance.now(); hfBuf.push({ t: n, u8 }); while (hfBuf.length && n - hfBuf[0].t > 40000) hfBuf.shift(); }
  async function fixOrig(b, chunks) {
    try {
      if (!chunks || !chunks.length) return;
      const pair = [prefs.my, prefs.other];
      let src = '';
      if (b._single) { const s = sourceOf(b.dir); if (SCRIPT[s] && !SCRIPT[s].test(b.orig)) src = s; }
      else if (b.trans.trim()) src = pair.find((x) => SCRIPT[x] && !SCRIPT[x].test(b.orig) && !SCRIPT[x].test(b.trans)) || '';
      if (!src) return;
      const tx = await LiveAudio.sttFallback(src, chunks);
      if (tx && SCRIPT[src].test(tx)) { b.orig = tx.replace(/\s+/g, ' '); lastSig = ''; renderSoon(); }
    } catch { /* ignore */ }
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
        let chunk = String(t || '');
        if (FOREIGN.test(chunk) && ![prefs.my, prefs.other].includes('ar')) chunk = chunk.replace(new RegExp(FOREIGN.source, 'g'), '');
        let b = cur[key];
        if (key === 'both' && (!b || b.trans)) b = newBubble('both', 'toOther');
        if (!b) return;
        if (key !== 'both') b._single = true;
        if (!chunk.trim() && !/\s/.test(chunk)) { b._heard = true; return; }
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
        phoneticSoon(b);
        renderSoon();
      },
      onAudio: (u8, rate) => {
        let b = cur[key];
        if (!b || b.done) b = newBubble(key, key === 'both' ? 'toOther' : key);
        b.audio.push(u8); b.rate = rate;
        b._heard = true;
        player.enqueue(u8, rate);
      },
      // bas-konuşta kesme yalnızca bizim basışımızla olur; sahte 'interrupted' sinyali çeviri sesini ortada kesmesin
      onInterrupted: () => { if (handsFree) player.stop(); },
      // Metin tamamlandı (ses hâlâ çalıyor olabilir) → okunuşu hemen getir; turnComplete ses süresi kadar gecikir
      onGenerationComplete: () => { if (holdDir !== key) finalize(key); },
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
    const b = { dir, from: sourceOf(dir), to: targetOf(dir), orig: '', trans: '', done: false, okunus: '', audio: [], rate: 24000, listening: false, t: Date.now(), _pt: performance.now() };
    bubbles.push(b);
    cur[key] = b;
    renderSoon();
    return b;
  }
  function retarget(b) {
    const dir = guessDir(b.orig, b.trans);
    if (dir !== b.dir) { b.dir = dir; b.from = sourceOf(dir); b.to = targetOf(dir); lastSig = ''; }
  }
  // Okunuş iki aşamalı: çeviri akarken hızlı (LLM'siz) sürüm → bitince kaliteli sürüm. Eski cevap yenisini ezmez.
  const phoneticTimers = new WeakMap();
  async function loadPhonetic(b, fast) {
    const text = b.trans.trim();
    if (b.to === 'tr' || !text) return;
    const seq = (b._pseq = (b._pseq || 0) + 1);
    try {
      const r = await fetch('/api/pronounce?' + new URLSearchParams({ q: text.slice(0, 400), lang: b.to, fast: fast ? '1' : '0' }));
      const d = await r.json();
      if (seq !== b._pseq || (b.done && fast)) return;
      if (d.phonetic) { b.okunus = d.phonetic; lastSig = ''; renderSoon(); }
    } catch { /* ignore */ }
  }
  function phoneticSoon(b) {
    clearTimeout(phoneticTimers.get(b));
    phoneticTimers.set(b, setTimeout(() => { if (!b.done) void loadPhonetic(b, true); }, 450));
  }

  async function finalize(key) {
    const b = cur[key];
    if (!b) return;
    cur[key] = null;
    b.listening = false;
    const orig = (b.orig || '').trim();
    const trans = (b.trans || '').trim();
    // Boş / dolgu turu (¿Qué?) — yalnızca SES YOKSA at (yazı sesten geç gelebilir → çalan çeviriyi kesme)
    const hasAudio = !!(b.audio && b.audio.length);
    const fil = (x) => !!x && FILLER_RE.test(x);
    if (!hasAudio && (!trans || fil(trans)) && (!orig || fil(orig))) {
      const i = bubbles.indexOf(b);
      if (i >= 0) bubbles.splice(i, 1);
      renderSoon();
      return;
    }
    if (isFiller(trans) && orig) b.trans = '';
    b.done = true;
    renderSoon();
    // Bazı dillerde (ör. Gürcüce) Google ses verir ama yazı dökümü göndermez → metni çeviri servisiyle tamamla
    if (!b.trans.trim() && b.orig.trim() && hasAudio) {
      try {
        const r = await fetch('/api/translate?' + new URLSearchParams({ q: b.orig.trim().slice(0, 500), from: b.from, to: b.to, my: b.from, other: b.to }));
        const d = await r.json();
        if (d && d.text) { b.trans = d.text; lastSig = ''; renderSoon(); }
      } catch { /* ignore */ }
    }
    if (b.orig.trim() || b.trans.trim()) {
      const chunks = b._pcm && b._pcm.length ? b._pcm : hfBuf.filter((x) => b._pt && x.t >= b._pt - 2500).map((x) => x.u8);
      void fixOrig(b, chunks);
    }
    void loadPhonetic(b, false);
    // Model bu dilde ses üretmediyse (yalnızca yazı geldiyse) çeviriyi sunucu sesiyle oku → her dilde ses var
    if (!hasAudio && b.trans.trim()) void playTts(b.trans.trim(), b.to);
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
    holdDir = dir;
    btn._holdT0 = performance.now();
    const wasPlaying = player.playing || performance.now() - lastPlayEnd < 600;
    player.stop();
    btn.classList.add('recording');
    setStatus(`Dinliyorum — ${lang(sourceOf(dir)).name} konuş`, true);
    const b = newBubble(dir, dir); b.listening = true; b._heard = false; b._single = true; b._pcm = []; renderSoon();
    const s = session(dir);
    s._activity = false;
    turn = new LiveAudio.Turn(s, s.connect());
    turn.ready.catch((e) => holdAbort(btn, (e && e.message) || 'Canlı bağlantı kurulamadı'));
    const t = turn;
    mic = new LiveAudio.Mic({
      preroll: !wasPlaying,
      onChunk: (u8) => { b._pcm.push(u8); t.chunk(u8); },
      onLevel: (lv) => {
        t.level(lv);
        btn.style.setProperty('--lv', Math.min(1, lv * 3).toFixed(2));
        if (t.voiced && b.listening && !b._heard) { b._heard = true; renderSoon(); }
      },
    });
    mic.start().catch((e) => holdAbort(btn, e && e.name === 'NotAllowedError' ? 'Mikrofon izni gerekli' : 'Mikrofon açılamadı'));
  }
  function dropBubble(b) {
    const i = bubbles.indexOf(b); if (i >= 0) bubbles.splice(i, 1);
    Object.keys(cur).forEach((k) => { if (cur[k] === b) cur[k] = null; });
    lastSig = ''; renderSoon();
  }
  function holdAbort(btn, msg) {
    const d = holdDir; holdDir = null; turn = null;
    if (mic) { mic.stop(); mic = null; }
    btn.classList.remove('recording', 'arming');
    if (d && cur[d]) dropBubble(cur[d]);
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
    const t = turn; turn = null;
    if (m) await m.stop();
    let sent = false;
    try { sent = t ? await t.end() : false; } catch { return; }
    if (!sent) { // ses yok / çok kısa → modele hiçbir şey gitmedi, uydurma cevap (¿Qué?) gelmez
      if (b) dropBubble(b);
      setStatus('Seni duyamadım — basılı tutup konuş');
      setTimeout(() => { if (!holdDir) idle(); }, 2200);
      return;
    }
    setStatus('Çeviriliyor…', true);
    // ses gitti ama yazıya/sese dönüşmediyse kutucuğu kaldır
    setTimeout(() => {
      if (cur[dir] === b && b && !b.orig.trim() && !b.trans.trim() && !(b.audio && b.audio.length)) {
        dropBubble(b);
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
      // Ortam sesi kapısı: zemin gürültüsünü öğrenir; yalnızca belirgin konuşma (+ kısa ön tampon, 600 ms bekleme) gönderilir
      let lastLv = 0, floor = 0.01, openUntil = 0, wasOpen = false;
      const pre = [];
      mic = new LiveAudio.Mic({
        preroll: false,
        // çeviri sesi çalarken sessizlik gönder → kendi çevirisini tekrar çevirmesin
        onChunk: (u8) => {
          if (!s.isOpen) return;
          const now = performance.now();
          if (lastLv < floor * 1.6) floor = floor * 0.95 + lastLv * 0.05; else floor = floor * 0.998 + lastLv * 0.002;
          floor = Math.min(floor, 0.08);
          if (lastLv > Math.max(0.045, floor * 3)) openUntil = now + 600;
          const open = now < openUntil;
          if (player.playing || now - lastPlayEnd < 700) { pre.length = 0; wasOpen = false; s.sendAudio(SILENCE); return; }
          if (open) {
            if (!wasOpen) { pre.forEach((c) => { s.sendAudio(c); hfPush(c); }); pre.length = 0; }
            wasOpen = true; s.sendAudio(u8); hfPush(u8);
          } else {
            wasOpen = false; pre.push(u8); if (pre.length > 3) pre.shift();
            s.sendAudio(SILENCE);
          }
        },
        onLevel: (lv) => { lastLv = lv; const m = $('ltMeter'); if (m) m.style.transform = `scale(${1 + Math.min(0.6, player.playing ? 0 : lv * 2.5)})`; },
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
  // iOS'ta await sonrası new Audio().play() engellenir → kilidi açılmış AudioContext ile çal
  let ttsSrc = null;
  async function playTts(text, tl) {
    try {
      const r = await fetch('/api/tts?' + new URLSearchParams({ q: text.trim().slice(0, 1800), tl }));
      if (!r.ok) throw new Error('tts');
      const buf = await LiveAudio.audioCtx().decodeAudioData(await r.arrayBuffer());
      const c = LiveAudio.unlock();
      player.stop();
      if (ttsSrc) { try { ttsSrc.stop(); } catch { /* ignore */ } }
      ttsSrc = c.createBufferSource(); ttsSrc.buffer = buf; ttsSrc.connect(c.destination); ttsSrc.start();
    } catch { showErr('Ses oluşturulamadı — metin ekranda'); }
  }

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
      const b = { dir, from: d.from, to: d.to, orig: text, trans: d.text, done: true, okunus: '', audio: [], rate: 24000, t: Date.now() };
      bubbles.push(b); render();
      void loadPhonetic(b, false);
      await playTts(d.text, d.to);
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

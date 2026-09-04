const LANGUAGES = [
  { code: 'tr', speech: 'tr-TR', name: 'Türkçe', flag: '🇹🇷' },
  { code: 'en', speech: 'en-US', name: 'English', flag: '🇬🇧' },
  { code: 'ka', speech: 'ka-GE', name: 'ქართული', flag: '🇬🇪' },
  { code: 'de', speech: 'de-DE', name: 'Deutsch', flag: '🇩🇪' },
  { code: 'fr', speech: 'fr-FR', name: 'Français', flag: '🇫🇷' },
  { code: 'es', speech: 'es-ES', name: 'Español', flag: '🇪🇸' },
  { code: 'ar', speech: 'ar-SA', name: 'العربية', flag: '🇸🇦' },
  { code: 'ru', speech: 'ru-RU', name: 'Русский', flag: '🇷🇺' },
  { code: 'it', speech: 'it-IT', name: 'Italiano', flag: '🇮🇹' },
  { code: 'zh', speech: 'zh-CN', name: '中文', flag: '🇨🇳' },
];

const audio = document.createElement('audio');
audio.setAttribute('playsinline', 'true');
audio.setAttribute('webkit-playsinline', 'true');
document.body.appendChild(audio);

const TAIL_MS = 180;
const MIN_HOLD_MS = 180;

const S = {
  my: 'tr', other: 'en', msgs: [],
  holdActive: false, holdGen: 0,
  lastFrom: null, audioReady: false,
  stream: null, recorder: null, chunks: [],
  fingerDownAt: 0, pressMs: 0,
  stopHandled: false, usedTouch: false,
  stopTimer: null, safetyTimer: null,
  busyCount: 0,
  transGen: 0,
  transAbort: null,
};

const $ = (id) => document.getElementById(id);
const getLang = (c) => LANGUAGES.find((l) => l.code === c) || LANGUAGES[0];

const MIC_OPTS = {
  audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};

function setStatus(t, live) {
  $('statusText').textContent = t;
  $('statusDot').classList.toggle('active', !!live);
}

function showErr(t) {
  $('errorBox').textContent = t;
  $('errorBox').className = 'error-box';
  $('errorBox').classList.remove('hidden');
}

function showInfo(t) {
  $('errorBox').textContent = t;
  $('errorBox').className = 'error-box info-box';
  $('errorBox').classList.remove('hidden');
}

function hideErr() {
  $('errorBox').classList.add('hidden');
}

function clearInterim() {
  $('interimBox').classList.add('hidden');
  $('interimText').textContent = '';
}

function showTranslating() {
  $('micBtn').classList.remove('recording');
  $('micTitle').textContent = 'Çevriliyor...';
  setStatus('Çevriliyor...', true);
  $('interimBox').classList.remove('hidden');
  $('interimText').textContent = 'Çevriliyor...';
}

function showSpeaking() {
  $('micBtn').classList.add('recording');
  $('micTitle').textContent = 'Konuşun...';
  setStatus('🎙 Konuşun...', true);
  $('interimBox').classList.remove('hidden');
  $('interimText').textContent = 'Konuşun...';
}

function resetIdle() {
  clearTimeout(S.stopTimer);
  clearTimeout(S.safetyTimer);
  S.stopTimer = null;
  S.safetyTimer = null;
  S.holdActive = false;
  $('micBtn').classList.remove('recording');
  $('micTitle').textContent = 'Basılı Tut ve Konuş';
  clearInterim();
  if (S.busyCount === 0) setStatus('Basılı tut ve konuş', false);
}

function render() {
  const el = $('messages');
  if (!S.msgs.length) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">🎤</div>
      <h2>Basılı tut ve konuş</h2>
      <p>Basılı tut, konuş, bırak. İstediğin kadar tekrarla.</p></div>`;
    $('clearBtn').classList.add('hidden');
    return;
  }
  $('clearBtn').classList.remove('hidden');
  el.innerHTML = S.msgs.map((m, i) => {
    const f = getLang(m.from), t = getLang(m.to);
    return `<article class="bubble ${m.from === S.my ? 'me' : 'other'}">
      <div class="bubble-label">${f.flag} ${f.name}</div>
      <div class="bubble-original">${m.orig}</div>
      <div class="bubble-divider"></div>
      <div class="bubble-label">${t.flag} ${t.name} 🔊</div>
      <div class="bubble-translated">${m.trans}</div>
      ${m.phonetic ? `<div class="bubble-phonetic">🔊 ${m.phonetic}</div>` : ''}
      ${m.audio ? `<button type="button" class="replay-btn" data-idx="${i}">🔊 Tekrar dinle</button>` : ''}</article>`;
  }).join('');
  el.querySelectorAll('.replay-btn').forEach((btn) => {
    btn.onclick = (e) => {
      e.preventDefault();
      unlockAudioSync();
      const m = S.msgs[parseInt(btn.dataset.idx, 10)];
      if (m?.audio) playB64(m.audio);
    };
  });
  el.scrollTop = 0;
}

function unlockAudioSync() {
  if (S.audioReady) return;
  try {
    audio.volume = 1;
    audio.src = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAZGF0YQQAAAA=';
    const p = audio.play();
    if (p?.then) {
      p.then(() => {
        audio.pause();
        audio.currentTime = 0;
        S.audioReady = true;
      }).catch(() => {});
    }
  } catch { /* ignore */ }
}

function stopTts() {
  audio.pause();
  audio.currentTime = 0;
}

async function playB64(b64) {
  if (!b64) return;
  stopTts();
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const blob = new Blob([bytes], { type: 'audio/mpeg' });
  const u = URL.createObjectURL(blob);
  audio.volume = 1;
  audio.src = u;
  const done = () => URL.revokeObjectURL(u);
  audio.onended = done;
  audio.onerror = done;
  try {
    await audio.play();
  } catch {
    showInfo('🔊 Sesi dinlemek için "Tekrar dinle"ye basın');
  }
}

function nextTransGen() {
  S.transGen += 1;
  if (S.transAbort) {
    try { S.transAbort.abort(); } catch { /* ignore */ }
  }
  S.transAbort = new AbortController();
  return { gen: S.transGen, signal: S.transAbort.signal };
}

function isAbortError(e) {
  return e && (e.name === 'AbortError' || e.message === 'The user aborted a request.');
}

async function fetchListen(blob, my, other, last) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 30000);
  try {
    const r = await fetch(`/api/listen?${new URLSearchParams({ my, other, last: last || '' })}`, {
      method: 'POST',
      body: blob,
      headers: { 'Content-Type': blob.type || 'audio/mp4' },
      signal: ctrl.signal,
    });
    const raw = await r.text();
    let d = {};
    try { d = raw ? JSON.parse(raw) : {}; } catch {
      throw new Error(r.ok ? 'Sunucu yanıtı okunamadı' : `Sunucu hatası (${r.status})`);
    }
    if (!r.ok) throw new Error(d.error || 'Ses anlaşılamadı — tekrar deneyin');
    return d;
  } finally {
    clearTimeout(timer);
  }
}

async function fetchProcess(blob, my, other, last, signal) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 45000);
  const onAbort = () => { try { ctrl.abort(); } catch { /* ignore */ } };
  if (signal) {
    if (signal.aborted) ctrl.abort();
    else signal.addEventListener('abort', onAbort, { once: true });
  }
  try {
    const r = await fetch(`/api/process?${new URLSearchParams({ my, other, last: last || '' })}`, {
      method: 'POST',
      body: blob,
      headers: { 'Content-Type': blob.type || 'audio/mp4' },
      signal: ctrl.signal,
    });
    const raw = await r.text();
    let d = {};
    try { d = raw ? JSON.parse(raw) : {}; } catch {
      throw new Error(r.ok ? 'Sunucu yanıtı okunamadı' : `Sunucu hatası (${r.status})`);
    }
    if (!r.ok) throw new Error(d.error || 'Ses işlenemedi — tekrar deneyin');
    return d;
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener('abort', onAbort);
  }
}

function looksLikeLangClient(text, lang) {
  const t = (text || '').trim();
  if (!t) return false;
  if (lang === 'tr') {
    if (/[ğüşıöçĞÜŞİÖÇ]/.test(t)) return true;
    return /\b(neler|yapıyor|nasıl|merhaba|nasılsın|teşekkür|evet|hayır|tamam|güzel|ben|sen|ne|neden|günaydın|lütfen|bugün|yarın)\b/i.test(t);
  }
  if (lang === 'en') {
    return /\b(what|how|are|you|doing|hello|thanks|thank|yes|no|good|please|fine|where|when|who|why|the|this|that|is|was|were|i'm|i|a|an|book|today|want|need|have|did|don't|very|hello|hi|bye|sorry|okay|ok)\b/i.test(t)
      || (/^[a-zA-Z0-9',.\-!? ]+$/.test(t) && t.split(/\s+/).length <= 3 && !/[ğüşıöçĞÜŞİÖÇ]/.test(t));
  }
  if (lang === 'ka') return /[\u10A0-\u10FF]/.test(t);
  if (lang === 'ru') return /[\u0400-\u04FF]/.test(t);
  if (lang === 'ar') return /[\u0600-\u06FF]/.test(t);
  if (lang === 'zh') return /[\u4e00-\u9fff]/.test(t);
  if (lang === 'de') return /[äöüÄÖÜß]/.test(t) || /\b(hallo|guten|danke|bitte|ja|nein|wie|geht|ich|sie|und|nicht|heute|morgen|bitte|schön)\b/i.test(t);
  if (lang === 'fr') return /[àâçéèêëîïôùûüœæ]/i.test(t) || /\b(bonjour|merci|oui|non|comment|je|vous|avec|pour|aujourd)\b/i.test(t);
  if (lang === 'es') return /[áéíóúñ¿¡]/i.test(t) || /\b(hola|gracias|buenos|sí|si|no|cómo|como|usted|por|favor)\b/i.test(t);
  if (lang === 'it') return /[àèéìòù]/i.test(t) || /\b(ciao|grazie|buongiorno|si|no|come|per|favore|oggi)\b/i.test(t);
  return false;
}

function detectTextFromLang(text, my, other) {
  const t = (text || '').trim();
  if (!t) return my;
  const myLike = looksLikeLangClient(t, my);
  const otherLike = looksLikeLangClient(t, other);
  if (otherLike && !myLike) return other;
  if (myLike && !otherLike) return my;
  if (otherLike && myLike) {
    // Yazı farklıysa karşı dil öncelikli (kullanıcı karşı tarafa yazıyor)
    if (my === 'tr' && otherLike) return other;
    return my;
  }
  // Script / Latin: Türkçe belirteç yoksa ve other Latin dilse other
  if (my === 'tr' && !/[ğüşıöçĞÜŞİÖÇ]/.test(t) && !looksLikeLangClient(t, 'tr')) {
    if (['ka', 'ru', 'ar', 'zh'].includes(other) && looksLikeLangClient(t, other)) return other;
    if (['en', 'de', 'fr', 'es', 'it'].includes(other) && /^[a-zA-ZÀ-ÿ0-9',.\-!? ¿¡äöüßœæç\s]+$/i.test(t)) {
      if (looksLikeLangClient(t, other) || (other === 'en' && /^[a-zA-Z0-9',.\-!? ]+$/.test(t))) return other;
    }
  }
  return my;
}

async function fetchTranslateText(text, from, to, signal) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 30000);
  const onAbort = () => { try { ctrl.abort(); } catch { /* ignore */ } };
  if (signal) {
    if (signal.aborted) ctrl.abort();
    else signal.addEventListener('abort', onAbort, { once: true });
  }
  try {
    const r = await fetch(`/api/translate?${new URLSearchParams({
      q: text, from, to, my: S.my, other: S.other,
    })}`, {
      signal: ctrl.signal,
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || 'Çeviri başarısız');
    return { text: d.text || '', from: d.from || from, to: d.to || to };
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener('abort', onAbort);
  }
}

async function fetchPronunciation(text, lang) {
  const phrase = (text || '').trim();
  if (!phrase || lang === 'tr') return '';
  try {
    const r = await fetch(`/api/pronounce?${new URLSearchParams({ q: phrase.slice(0, 2500), lang })}`);
    const d = await r.json().catch(() => ({}));
    return d.phonetic || '';
  } catch {
    return '';
  }
}

async function processAudio(blob) {
  const { gen, signal } = nextTransGen();
  const t0 = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
  const data = await fetchProcess(blob, S.my, S.other, S.lastFrom, signal);
  if (gen !== S.transGen) return;
  S.lastFrom = data.from;
  const toLang = data.to;
  const msg = {
    orig: data.original,
    trans: data.translated,
    from: data.from,
    to: toLang,
    audio: null,
    phonetic: '',
    gen,
  };
  S.msgs.unshift(msg);
  render();
  clearInterim();
  setStatus('Çeviri hazır', false);
  if (typeof console !== 'undefined' && console.debug) {
    const dt = ((typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now()) - t0;
    console.debug('speech_end→UI_ms', Math.round(dt));
  }
  void fetchTranslateTts(data.translated, toLang, gen);
  if (toLang !== 'tr') {
    void fetchPronunciation(data.translated, toLang).then((ph) => {
      if (gen !== S.transGen || !ph) return;
      const m = S.msgs.find((x) => x.gen === gen);
      if (m) {
        m.phonetic = ph;
        render();
      }
    });
  }
  return { original: data.original, translated: data.translated, from: data.from, to: toLang };
}

async function processText(text) {
  const trimmed = (text || '').trim();
  if (!trimmed) return;
  const { gen, signal } = nextTransGen();
  S.busyCount += 1;
  setStatus('Çevriliyor…', true);
  try {
    let fromLang = detectTextFromLang(trimmed, S.my, S.other);
    if (fromLang !== S.my && fromLang !== S.other) fromLang = S.my;
    const toLang = fromLang === S.my ? S.other : S.my;
    const result = await fetchTranslateText(trimmed, fromLang, toLang, signal);
    if (gen !== S.transGen) return;
    fromLang = result.from === S.my || result.from === S.other ? result.from : fromLang;
    const finalTo = fromLang === S.my ? S.other : S.my;
    const translated = result.text;
    S.lastFrom = fromLang;
    const msg = {
      orig: trimmed,
      trans: translated,
      from: fromLang,
      to: finalTo,
      audio: null,
      phonetic: '',
      gen,
    };
    S.msgs.unshift(msg);
    render();
    setStatus('Çeviri hazır', false);
    void fetchTranslateTts(translated, finalTo, gen);
    if (finalTo !== 'tr') {
      void fetchPronunciation(translated, finalTo).then((ph) => {
        if (gen !== S.transGen || !ph) return;
        const m = S.msgs.find((x) => x.gen === gen);
        if (m) {
          m.phonetic = ph;
          render();
        }
      }).catch(() => {});
    }
  } catch (e) {
    if (isAbortError(e) || gen !== S.transGen) return;
    showErr(e.message || 'Çeviri başarısız');
  } finally {
    S.busyCount -= 1;
    if (S.busyCount === 0) resetIdle();
  }
}

async function fetchTranslateTts(text, lang, gen) {
  const phrase = (text || '').trim().slice(0, 2500);
  if (!phrase) return;
  try {
    const r = await fetch(`/api/tts?${new URLSearchParams({ q: phrase, tl: lang })}`);
    if (!r.ok) return;
    if (gen != null && gen !== S.transGen) return;
    const blob = await r.blob();
    if (gen != null && gen !== S.transGen) return;
    const buf = await blob.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let bin = '';
    const chunk = 8192;
    for (let i = 0; i < bytes.length; i += chunk) {
      bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
    }
    const b64 = btoa(bin);
    const m = (gen != null) ? S.msgs.find((x) => x.gen === gen) : S.msgs[0];
    if (m) {
      m.audio = b64;
      render();
    }
    if (gen != null && gen !== S.transGen) return;
    stopTts();
    const u = URL.createObjectURL(blob);
    audio.volume = 1;
    audio.src = u;
    const done = () => URL.revokeObjectURL(u);
    audio.onended = done;
    audio.onerror = done;
    await audio.play();
  } catch { /* ignore */ }
}

const mic = MicHold.create({
  state: S,
  tailMs: TAIL_MS,
  minHoldMs: MIN_HOLD_MS,
  minBlobBytes: 20,
  micOpts: MIC_OPTS,
  onHideError: hideErr,
  onSpeaking: () => {
    hideErr();
    showSpeaking();
    unlockAudioSync();
    stopTts();
  },
  onProcessing: showTranslating,
  onIdle: () => {
    if (S.busyCount === 0) resetIdle();
  },
  onError: showErr,
  isBusy: () => S.busyCount > 0,
  onBlob: (blob) => {
    S.busyCount += 1;
    showTranslating();
    processAudio(blob)
      .catch((e) => {
        if (isAbortError(e)) return;
        showErr(e.message || 'Anlaşılamadı');
      })
      .finally(() => {
        S.busyCount -= 1;
        if (!S.holdActive && !mic.isRecording() && S.busyCount === 0) resetIdle();
      });
  },
});

function isRecording() {
  return mic.isRecording();
}

LANGUAGES.forEach((l) => {
  [$('myLang'), $('otherLang')].forEach((sel) => {
    const o = document.createElement('option');
    o.value = l.code;
    o.textContent = `${l.flag} ${l.name}`;
    sel.appendChild(o);
  });
});

function syncLang() {
  $('myLang').value = S.my;
  $('otherLang').value = S.other;
  $('conversationSubtitle').textContent =
    `${getLang(S.my).flag} ${getLang(S.my).name} ↔ ${getLang(S.other).flag} ${getLang(S.other).name}`;
}

mic.bindHold($('micBtn'));

/* Yazı ile çeviri */
const _txtInput = $('translateTextInput');
const _txtSend = $('translateSendBtn');
if (_txtInput && _txtSend) {
  _txtSend.onclick = () => {
    const v = _txtInput.value.trim();
    if (v) { _txtInput.value = ''; processText(v); }
  };
  _txtInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const v = _txtInput.value.trim();
      if (v) { _txtInput.value = ''; processText(v); }
    }
  });
}

$('testBtn').onclick = async () => {
  if (isRecording()) return;
  S.busyCount += 1;
  try {
    const r = await fetch(`/api/translate?${new URLSearchParams({ q: 'Merhaba nasılsın', from: 'tr', to: 'en' })}`);
    const d = await r.json();
    const tts = await fetch(`/api/tts?${new URLSearchParams({ tl: 'en', q: d.text })}`);
    const blob = await tts.blob();
    S.msgs.unshift({ orig: 'Merhaba nasılsın', trans: d.text, from: 'tr', to: 'en' });
    S.lastFrom = null;
    render();
    await new Promise((ok, no) => {
      const u = URL.createObjectURL(blob);
      audio.onended = () => { URL.revokeObjectURL(u); ok(); };
      audio.src = u; audio.play().catch(no);
    });
  } finally { S.busyCount -= 1; }
};

$('swapBtn').onclick = () => {
  if (isRecording()) return;
  [S.my, S.other] = [S.other, S.my];
  S.lastFrom = null;
  syncLang();
};

$('myLang').onchange = (e) => {
  if (!isRecording()) {
    S.my = e.target.value;
    S.lastFrom = null;
  } else e.target.value = S.my;
};
$('otherLang').onchange = (e) => { if (!isRecording()) S.other = e.target.value; else e.target.value = S.other; };
$('clearBtn').onclick = () => {
  if (!isRecording() && S.busyCount === 0) {
    S.msgs = [];
    S.lastFrom = null;
    render();
  }
};

syncLang();
render();
resetIdle();

if (!navigator.mediaDevices?.getUserMedia) {
  showErr('Safari gerekli');
  $('micBtn').disabled = true;
}

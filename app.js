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

const TAIL_MS = 100;
const MIN_HOLD_MS = 280;

const S = {
  my: 'tr', other: 'en', msgs: [],
  holdActive: false, holdGen: 0,
  lastFrom: 'tr', audioReady: false,
  stream: null, recorder: null, chunks: [],
  fingerDownAt: 0, pressMs: 0,
  stopHandled: false, usedTouch: false,
  stopTimer: null, safetyTimer: null,
  busyCount: 0,
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

async function fetchProcess(blob, my, other, last) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 45000);
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
  }
}

async function fetchTranslateText(text, from, to) {
  const r = await fetch(`/api/translate?${new URLSearchParams({ q: text, from, to })}`);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'Çeviri başarısız');
  return d.text || '';
}

async function fetchPronunciation(text, lang) {
  const phrase = (text || '').trim();
  if (!phrase || lang === 'tr') return '';
  try {
    const r = await fetch(`/api/pronounce?${new URLSearchParams({ q: phrase.slice(0, 300), lang })}`);
    const d = await r.json().catch(() => ({}));
    return d.phonetic || '';
  } catch {
    return '';
  }
}

async function processAudio(blob) {
  /* Tek istek: STT + çeviri birlikte — ikinci tur beklemeyi kaldırır */
  const data = await fetchProcess(blob, S.my, S.other, S.lastFrom);
  S.lastFrom = data.from;
  const toLang = data.to;
  const msg = {
    orig: data.original,
    trans: data.translated,
    from: data.from,
    to: toLang,
    audio: null,
    phonetic: '',
  };
  S.msgs.unshift(msg);
  render();
  clearInterim();
  setStatus('Çeviri hazır', false);
  void fetchTranslateTts(data.translated, toLang, 0);
  void fetchPronunciation(data.translated, toLang).then((ph) => {
    if (S.msgs[0]?.orig === data.original && ph) {
      S.msgs[0].phonetic = ph;
      render();
    }
  });
  return { original: data.original, translated: data.translated, from: data.from, to: toLang };
}

async function fetchTranslateTts(text, lang, msgIndex) {
  const phrase = (text || '').trim().slice(0, 500);
  if (!phrase) return;
  try {
    const r = await fetch(`/api/tts?${new URLSearchParams({ q: phrase, tl: lang })}`);
    if (!r.ok) return;
    const blob = await r.blob();
    const buf = await blob.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let bin = '';
    const chunk = 8192;
    for (let i = 0; i < bytes.length; i += chunk) {
      bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
    }
    const b64 = btoa(bin);
    if (S.msgs[msgIndex]) {
      S.msgs[msgIndex].audio = b64;
      render();
    }
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
  minBlobBytes: 200,
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
      .catch((e) => showErr(e.message || 'Anlaşılamadı'))
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

$('testBtn').onclick = async () => {
  if (isRecording()) return;
  S.busyCount += 1;
  try {
    const r = await fetch(`/api/translate?${new URLSearchParams({ q: 'Merhaba nasılsın', from: 'tr', to: 'en' })}`);
    const d = await r.json();
    const tts = await fetch(`/api/tts?${new URLSearchParams({ tl: 'en', q: d.text })}`);
    const blob = await tts.blob();
    S.msgs.unshift({ orig: 'Merhaba nasılsın', trans: d.text, from: 'tr', to: 'en' });
    S.lastFrom = 'tr';
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
  S.lastFrom = S.my;
  syncLang();
};

$('myLang').onchange = (e) => {
  if (!isRecording()) {
    S.my = e.target.value;
    S.lastFrom = S.my;
  } else e.target.value = S.my;
};
$('otherLang').onchange = (e) => { if (!isRecording()) S.other = e.target.value; else e.target.value = S.other; };
$('clearBtn').onclick = () => {
  if (!isRecording() && S.busyCount === 0) {
    S.msgs = [];
    S.lastFrom = S.my;
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

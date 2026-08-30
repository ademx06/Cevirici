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

const TAIL_MS = 450;
const MIN_HOLD_MS = 450;

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

function isRecording() {
  return S.recorder?.state === 'recording';
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

function releaseMic() {
  clearTimeout(S.stopTimer);
  clearTimeout(S.safetyTimer);
  S.stopTimer = null;
  S.safetyTimer = null;
  if (S.recorder) {
    S.recorder.ondataavailable = null;
    S.recorder.onstop = null;
    if (S.recorder.state === 'recording') {
      try { S.recorder.stop(); } catch { /* ignore */ }
    }
    S.recorder = null;
  }
  if (S.stream) {
    S.stream.getTracks().forEach((t) => t.stop());
    S.stream = null;
  }
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

async function processAudio(blob) {
  const r = await fetch(`/api/process?${new URLSearchParams({ my: S.my, other: S.other, last: S.lastFrom })}`, {
    method: 'POST',
    body: blob,
    headers: { 'Content-Type': blob.type || 'audio/mp4' },
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'Ses işlenemedi — tekrar deneyin');
  return d;
}

function handleResult(d) {
  S.lastFrom = d.from;
  S.msgs.unshift({
    orig: d.original, trans: d.translated, from: d.from, to: d.to, audio: d.audio || null,
  });
  render();
  if (d.audio) playB64(d.audio);
}

function pickMime() {
  if (typeof MediaRecorder === 'undefined') return '';
  for (const m of ['audio/mp4', 'audio/aac', 'audio/webm;codecs=opus', 'audio/webm']) {
    if (MediaRecorder.isTypeSupported(m)) return m;
  }
  return '';
}

async function openFreshMic() {
  releaseMic();
  S.stream = await navigator.mediaDevices.getUserMedia(MIC_OPTS);
  return S.stream;
}

function startRecorder(gen) {
  const mime = pickMime();
  S.chunks = [];
  S.stopHandled = false;

  S.recorder = mime
    ? new MediaRecorder(S.stream, { mimeType: mime, audioBitsPerSecond: 192000 })
    : new MediaRecorder(S.stream);

  S.recorder.ondataavailable = (e) => {
    if (e.data?.size > 0) S.chunks.push(e.data);
  };

  S.recorder.onstop = () => {
    if (S.stopHandled) return;
    S.stopHandled = true;
    clearTimeout(S.stopTimer);
    clearTimeout(S.safetyTimer);
    S.stopTimer = null;
    S.safetyTimer = null;

    const mimeType = S.recorder?.mimeType || mime || 'audio/mp4';
    const chunks = S.chunks.slice();
    const pressMs = S.pressMs || 0;
    S.chunks = [];
    releaseMic();

    if (pressMs < MIN_HOLD_MS) {
      if (!S.holdActive && S.busyCount === 0) resetIdle();
      return;
    }

    const blob = new Blob(chunks, { type: mimeType });
    if (blob.size < 400) {
      if (!S.holdActive && S.busyCount === 0) resetIdle();
      return;
    }

    S.busyCount += 1;
    showTranslating();

    processAudio(blob)
      .then(handleResult)
      .catch((e) => showErr(e.message || 'Anlaşılamadı'))
      .finally(() => {
        S.busyCount -= 1;
        if (!S.holdActive && !isRecording() && S.busyCount === 0) resetIdle();
      });
  };

  S.recorder.start(100);
  if (!S.holdActive || S.holdGen !== gen) {
    finishRecording();
  }
}

function finishRecording() {
  if (!isRecording()) {
    if (!S.holdActive && S.busyCount === 0) resetIdle();
    return;
  }
  clearTimeout(S.stopTimer);
  S.stopTimer = setTimeout(() => {
    if (isRecording()) {
      try {
        S.recorder.requestData();
        S.recorder.stop();
      } catch {
        releaseMic();
        if (!S.holdActive && S.busyCount === 0) resetIdle();
      }
    }
  }, TAIL_MS);
}

async function beginHold() {
  const gen = ++S.holdGen;
  S.holdActive = true;
  S.fingerDownAt = Date.now();
  hideErr();
  showSpeaking();

  unlockAudioSync();
  stopTts();

  if (!navigator.mediaDevices?.getUserMedia) {
    showErr('Safari gerekli');
    resetIdle();
    return;
  }

  if (isRecording()) return;

  try {
    await openFreshMic();

    if (!S.holdActive || S.holdGen !== gen) {
      releaseMic();
      resetIdle();
      return;
    }

    startRecorder(gen);
  } catch {
    releaseMic();
    showErr('Mikrofon izni: Ayarlar → Safari → Mikrofon');
    resetIdle();
  }
}

function endHold() {
  if (S.fingerDownAt) S.pressMs = Date.now() - S.fingerDownAt;
  S.holdActive = false;

  if (!isRecording()) {
    resetIdle();
    return;
  }

  showTranslating();

  clearTimeout(S.safetyTimer);
  S.safetyTimer = setTimeout(() => {
    releaseMic();
    if (S.busyCount === 0) resetIdle();
  }, 5000);

  finishRecording();
}

function bindHold(el) {
  const down = (e) => { e.preventDefault(); beginHold(); };
  const up = (e) => { e.preventDefault(); endHold(); };

  el.addEventListener('touchstart', (e) => {
    S.usedTouch = true;
    down(e);
  }, { passive: false });
  el.addEventListener('touchend', up, { passive: false });
  el.addEventListener('touchcancel', up, { passive: false });

  el.addEventListener('mousedown', (e) => {
    if (S.usedTouch) return;
    down(e);
  });
  el.addEventListener('mouseup', (e) => {
    if (S.usedTouch) return;
    up(e);
  });
  el.addEventListener('mouseleave', (e) => {
    if (S.usedTouch || !isRecording()) return;
    up(e);
  });
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

bindHold($('micBtn'));

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

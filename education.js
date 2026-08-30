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

const LEARN_LANGS = LANGUAGES.filter((l) => l.code !== 'tr');
const PROFILE_KEY = 'edu_profile_v2';
const HISTORY_KEY = 'edu_history_v2';

const STATES = {
  IDLE: { text: 'Konuşmak için basılı tut', mic: 'Basılı Tut ve Konuş', live: false },
  LISTENING: { text: 'Dinleniyor...', mic: 'Konuşun...', live: true },
  PROCESSING: { text: 'Düşünüyor...', mic: 'Düşünüyor...', live: true },
  SPEAKING: { text: 'Öğretmen konuşuyor...', mic: 'Dinleyin...', live: true },
  ERROR: { text: 'Tekrar deneyin', mic: 'Basılı Tut ve Konuş', live: false },
};

const audio = document.createElement('audio');
audio.setAttribute('playsinline', 'true');
audio.setAttribute('webkit-playsinline', 'true');
document.body.appendChild(audio);

const TAIL_MS = 450;
const MIN_HOLD_MS = 450;

const S = {
  learnLang: 'en',
  roleplay: '',
  speakSlow: false,
  msgs: [],
  history: [],
  profile: null,
  sessionStart: null,
  uiState: 'IDLE',
  holdActive: false,
  holdGen: 0,
  audioReady: false,
  stream: null,
  recorder: null,
  chunks: [],
  fingerDownAt: 0,
  pressMs: 0,
  stopHandled: false,
  usedTouch: false,
  stopTimer: null,
  safetyTimer: null,
  busyCount: 0,
  lastAudio: null,
  greetingLoaded: false,
};

const $ = (id) => document.getElementById(id);
const getLang = (c) => LANGUAGES.find((l) => l.code === c) || LANGUAGES[0];

const MIC_OPTS = {
  audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};

function loadProfile() {
  try {
    const raw = localStorage.getItem(PROFILE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { targetLang: S.learnLang, currentLevel: 'A1', dailyGoalMinutes: 10, todayMinutes: 0 };
}

function saveProfile() {
  if (!S.profile) return;
  try {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(S.profile));
  } catch { /* ignore */ }
}

function loadHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return [];
}

function saveHistory() {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(S.history.slice(0, 24)));
  } catch { /* ignore */ }
}

function setUiState(name) {
  S.uiState = name;
  const st = STATES[name] || STATES.IDLE;
  $('statusText').textContent = st.text;
  $('statusDot').classList.toggle('active', st.live);
  $('micTitle').textContent = st.mic;
}

function showErr(t) {
  $('errorBox').textContent = t;
  $('errorBox').className = 'error-box';
  $('errorBox').classList.remove('hidden');
  setUiState('ERROR');
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

function showThinking() {
  $('micBtn').classList.remove('recording');
  $('interimBox').classList.remove('hidden');
  $('interimText').textContent = 'Düşünüyor...';
  setUiState('PROCESSING');
}

function showSpeaking() {
  $('micBtn').classList.add('recording');
  $('interimBox').classList.remove('hidden');
  $('interimText').textContent = 'Konuşun...';
  setUiState('LISTENING');
}

function resetIdle() {
  clearTimeout(S.stopTimer);
  clearTimeout(S.safetyTimer);
  S.stopTimer = null;
  S.safetyTimer = null;
  S.holdActive = false;
  $('micBtn').classList.remove('recording');
  clearInterim();
  if (S.busyCount === 0 && S.uiState !== 'SPEAKING') setUiState('IDLE');
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

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function updateLevelBadge() {
  const lvl = S.profile?.currentLevel || 'A1';
  $('levelBadge').textContent = lvl;
}

function updateDailyGoal() {
  const goal = S.profile?.dailyGoalMinutes || 10;
  const mins = S.profile?.todayMinutes || 0;
  const pct = Math.min(100, Math.round((mins / goal) * 100));
  $('goalText').textContent = `${goal} dk konuşma`;
  $('goalMeta').textContent = `${mins.toFixed ? mins.toFixed(1) : mins} / ${goal} dk`;
  $('goalProgress').style.width = `${pct}%`;
}

function render() {
  const el = $('messages');
  if (!S.msgs.length) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">🤖</div>
      <h2>Robot öğretmenin hazır</h2>
      <p>İngilizce konuş — robot doğal cevap verir.<br>
      Gerekirse düzeltir. "Türkçe açıkla" diyebilirsin.</p></div>`;
    $('clearBtn').classList.add('hidden');
    return;
  }
  $('clearBtn').classList.remove('hidden');
  el.innerHTML = S.msgs.map((m, i) => {
    if (m.role === 'user') {
      const lg = getLang(m.lang || S.learnLang);
      return `<article class="bubble me edu-user">
        <div class="bubble-label">Sen ${lg.flag}</div>
        <div class="bubble-original">${esc(m.text)}</div></article>`;
    }
    const lg = getLang(m.targetLang || S.learnLang);
    const explain = m.explain ? `<div class="bubble-divider"></div>
      <div class="bubble-label">🇹🇷 Açıklama</div>
      <div class="bubble-translated edu-explain">${esc(m.explain).replace(/\n/g, '<br>')}</div>` : '';
    const corr = m.correction && m.correctionLevel >= 2
      ? `<div class="edu-correction">✏️ ${esc(m.correction)}</div>` : '';
    return `<article class="bubble other edu-robot">
      <div class="bubble-label">🤖 Öğretmen · ${lg.flag} ${lg.name}</div>
      <div class="bubble-original edu-teacher-text">${esc(m.teacher).replace(/\n/g, '<br>')}</div>
      ${corr}${explain}
      ${m.audio ? `<button type="button" class="replay-btn" data-idx="${i}">🔊 Tekrar dinle</button>` : ''}</article>`;
  }).join('');
  el.querySelectorAll('.replay-btn').forEach((btn) => {
    btn.onclick = (e) => {
      e.preventDefault();
      unlockAudioSync();
      playB64(S.msgs[parseInt(btn.dataset.idx, 10)].audio);
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
  if (S.uiState === 'SPEAKING') setUiState('IDLE');
}

async function playB64(b64) {
  if (!b64) return;
  stopTts();
  S.lastAudio = b64;
  setUiState('SPEAKING');
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const blob = new Blob([bytes], { type: 'audio/mpeg' });
  const u = URL.createObjectURL(blob);
  audio.volume = 1;
  audio.src = u;
  const done = () => {
    URL.revokeObjectURL(u);
    if (!S.holdActive && !isRecording() && S.busyCount === 0) setUiState('IDLE');
  };
  audio.onended = done;
  audio.onerror = done;
  try { await audio.play(); } catch { done(); }
}

function pushHistory(role, text) {
  S.history.unshift({ role, text });
  S.history = S.history.slice(0, 24);
  saveHistory();
}

function handleEducationResult(d) {
  if (d.profile) {
    S.profile = d.profile;
    saveProfile();
    updateLevelBadge();
    updateDailyGoal();
  }
  if (d.user_text) {
    S.msgs.unshift({
      role: 'user',
      text: d.user_text,
      lang: d.user_lang || S.learnLang,
    });
    pushHistory('user', d.user_text);
  }
  const teacher = d.teacher_text || d.robot_target || '';
  S.msgs.unshift({
    role: 'teacher',
    teacher,
    explain: d.explain_tr || '',
    correction: d.correction || '',
    correctionLevel: d.correction_level || 1,
    targetLang: d.target_lang || S.learnLang,
    audio: d.audio || null,
    type: d.type,
  });
  pushHistory('teacher', teacher);
  render();
  if (d.audio) playB64(d.audio);
}

async function processEducationVoice(blob) {
  const state = JSON.stringify({
    profile: S.profile,
    history: S.history,
    roleplay: S.roleplay || null,
    speak_slow: S.speakSlow,
  });
  const r = await fetch(`/api/education/voice?${new URLSearchParams({ lang: S.learnLang })}`, {
    method: 'POST',
    body: blob,
    headers: {
      'Content-Type': blob.type || 'audio/mp4',
      'X-Education-State': state,
    },
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'Bağlantı sorunu. Tekrar dene.');
  return d;
}

async function fetchGreeting() {
  if (S.greetingLoaded || S.msgs.length > 0) return;
  S.busyCount += 1;
  showThinking();
  try {
    const params = new URLSearchParams({
      lang: S.learnLang,
      profile: JSON.stringify(S.profile || {}),
    });
    const r = await fetch(`/api/education/greeting?${params}`);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || 'Karşılama yüklenemedi');
    handleEducationResult(d);
    S.greetingLoaded = true;
    S.sessionStart = Date.now();
  } catch (e) {
    showErr(e.message || 'Bağlantı sorunu. Tekrar dene.');
  } finally {
    S.busyCount -= 1;
    resetIdle();
  }
}

async function loadLesson(id) {
  if (isRecording() || S.busyCount > 0) return;
  S.busyCount += 1;
  showThinking();
  try {
    const r = await fetch(`/api/tutor/lesson?${new URLSearchParams({ id, lang: S.learnLang })}`);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || 'Ders yüklenemedi');
    S.msgs.unshift({
      role: 'teacher',
      teacher: d.robot_target,
      explain: d.robot_tr,
      targetLang: d.target_lang,
      audio: d.audio,
      type: 'lesson',
    });
    render();
    if (d.audio) playB64(d.audio);
  } catch (e) {
    showErr(e.message);
  } finally {
    S.busyCount -= 1;
    resetIdle();
  }
}

function showReport() {
  const mins = S.sessionStart ? (Date.now() - S.sessionStart) / 60000 : (S.profile?.todayMinutes || 0);
  const total = Math.max(S.profile?.totalSentences || 0, 1);
  const correct = S.profile?.correctSentences || 0;
  const corrections = S.profile?.totalCorrections || 0;
  const grammar = Math.min(100, Math.round((correct / total) * 100));
  const weak = (S.profile?.weakAreas || []).slice(0, 3).map((w) => w.replace(/_/g, ' ')).join(', ') || '—';
  $('reportContent').innerHTML = `
    <div class="report-row"><span>Konuşma süresi</span><strong>${mins.toFixed(1)} dk</strong></div>
    <div class="report-row"><span>Cümleler</span><strong>${total}</strong></div>
    <div class="report-row"><span>Doğru cümleler</span><strong>${correct}</strong></div>
    <div class="report-row"><span>Düzeltmeler</span><strong>${corrections}</strong></div>
    <div class="report-row"><span>Gramer</span><strong>${grammar}%</strong></div>
    <div class="report-row"><span>Tahmini seviye</span><strong>${S.profile?.currentLevel || 'A1'}</strong></div>
    <div class="report-row"><span>Zayıf alanlar</span><strong>${esc(weak)}</strong></div>`;
  $('reportModal').classList.remove('hidden');
  if (S.profile) {
    S.profile.todayMinutes = (S.profile.todayMinutes || 0) + mins;
    saveProfile();
    updateDailyGoal();
  }
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
    showThinking();

    processEducationVoice(blob)
      .then(handleEducationResult)
      .catch((e) => showErr(e.message || 'Duyamadım — tekrar dene'))
      .finally(() => {
        S.busyCount -= 1;
        if (!S.holdActive && !isRecording() && S.busyCount === 0) resetIdle();
      });
  };

  try {
    S.recorder.start(100);
  } catch (e) {
    S.recorder = null;
    throw e;
  }

  if (!S.holdActive || S.holdGen !== gen) finishRecording();
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
    showErr('Mikrofon için Safari gerekli');
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
    showErr('Mikrofon izni gerekli. Ayarlar → Safari → Mikrofon');
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

  showThinking();

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
  el.addEventListener('mousedown', (e) => { if (!S.usedTouch) down(e); });
  el.addEventListener('mouseup', (e) => { if (!S.usedTouch) up(e); });
  el.addEventListener('mouseleave', (e) => {
    if (S.usedTouch || !isRecording()) return;
    up(e);
  });
}

function syncLearnLang() {
  const lg = getLang(S.learnLang);
  $('learnLang').value = S.learnLang;
  $('robotName').textContent = `${lg.flag} ${lg.name} Öğretmeni`;
  $('conversationSubtitle').textContent = `${lg.name} konuş · robot cevap verir`;
  if (S.profile) {
    S.profile.targetLang = S.learnLang;
    saveProfile();
  }
}

LEARN_LANGS.forEach((l) => {
  const o = document.createElement('option');
  o.value = l.code;
  o.textContent = `${l.flag} ${l.name}`;
  $('learnLang').appendChild(o);
});

$('learnLang').onchange = (e) => {
  if (!isRecording()) {
    S.learnLang = e.target.value;
    S.greetingLoaded = false;
    syncLearnLang();
    fetchGreeting();
  } else {
    e.target.value = S.learnLang;
  }
};

$('roleplaySelect').onchange = (e) => {
  S.roleplay = e.target.value;
};

$('speedNormal').onclick = () => {
  S.speakSlow = false;
  $('speedNormal').classList.add('active');
  $('speedSlow').classList.remove('active');
};

$('speedSlow').onclick = () => {
  S.speakSlow = true;
  $('speedSlow').classList.add('active');
  $('speedNormal').classList.remove('active');
};

$('repeatBtn').onclick = async () => {
  unlockAudioSync();
  if (S.lastAudio) {
    playB64(S.lastAudio);
    return;
  }
  const last = S.msgs.find((m) => m.role === 'teacher');
  if (!last) return;
  try {
    const r = await fetch(`/api/tts?${new URLSearchParams({
      q: last.teacher.slice(0, 400),
      tl: S.learnLang,
    })}`);
    if (!r.ok) return;
    const buf = await r.arrayBuffer();
    const b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));
    playB64(b64);
  } catch { /* ignore */ }
};

$('lessonChips').querySelectorAll('.chip').forEach((chip) => {
  chip.onclick = () => loadLesson(chip.dataset.lesson);
});

$('clearBtn').onclick = () => {
  if (!isRecording() && S.busyCount === 0) {
    S.msgs = [];
    S.history = [];
    saveHistory();
    S.greetingLoaded = false;
    render();
    fetchGreeting();
  }
};

$('reportBtn').onclick = () => showReport();
$('closeReport').onclick = () => $('reportModal').classList.add('hidden');
$('reportModal').querySelector('.edu-modal-backdrop').onclick = () => $('reportModal').classList.add('hidden');

bindHold($('micBtn'));

S.profile = loadProfile();
S.history = loadHistory();
S.learnLang = S.profile.targetLang || 'en';
syncLearnLang();
updateLevelBadge();
updateDailyGoal();
render();
resetIdle();
fetchGreeting();

if (!navigator.mediaDevices?.getUserMedia) {
  showErr('Mikrofon için Safari gerekli');
  $('micBtn').disabled = true;
}

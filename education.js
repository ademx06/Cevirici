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
const CHAT_KEY = 'edu_chat_v3';

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
  weeklyProgress: null,
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
  sessionSaved: false,
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
  return {
    targetLang: 'en', currentLevel: 'A1', dailyGoalMinutes: 10,
    todayMinutes: 0, dailyStats: [], sessionLog: [], srsItems: [], vocabularyBank: [],
  };
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

function saveChat() {
  try {
    localStorage.setItem(CHAT_KEY, JSON.stringify(S.msgs.slice(-80)));
  } catch { /* ignore */ }
}

function loadChat() {
  try {
    const raw = localStorage.getItem(CHAT_KEY);
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

function showTyping() {
  $('typingIndicator').classList.remove('hidden');
}

function hideTyping() {
  $('typingIndicator').classList.add('hidden');
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
  showTyping();
  setUiState('PROCESSING');
}

function showSpeaking() {
  $('micBtn').classList.add('recording');
  hideTyping();
  setUiState('LISTENING');
}

function resetIdle() {
  clearTimeout(S.stopTimer);
  clearTimeout(S.safetyTimer);
  S.stopTimer = null;
  S.safetyTimer = null;
  S.holdActive = false;
  $('micBtn').classList.remove('recording');
  hideTyping();
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
  d.textContent = s ?? '';
  return d.innerHTML;
}

function formatDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(`${dateStr}T12:00:00`);
  return d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'long' });
}

function updateLevelBadge() {
  $('levelBadge').textContent = S.profile?.currentLevel || 'A1';
}

function updateDailyGoal() {
  const goal = S.profile?.dailyGoalMinutes || 10;
  const mins = S.profile?.todayMinutes || 0;
  const pct = Math.min(100, Math.round((mins / goal) * 100));
  $('goalText').textContent = `${goal} dk konuşma`;
  $('goalMeta').textContent = `${Number(mins).toFixed(1)} / ${goal} dk`;
  $('goalProgress').style.width = `${pct}%`;
}

function updatePersonalLesson(lesson) {
  if (!lesson) return;
  $('lessonWeak').textContent = lesson.mainWeakness || '—';
  $('lessonVocab').textContent = lesson.vocabulary || '—';
  $('lessonTopic').textContent = lesson.conversation || '—';
  $('lessonPractice').textContent = `${lesson.practiceMinutes || 10} dk`;
  const srs = lesson.srsReviewsDue || 0;
  const vocab = lesson.vocabReviewsDue || 0;
  if (srs + vocab > 0) {
    $('lessonSrsMeta').textContent = `🔄 Tekrar bekleyen: ${srs} gramer · ${vocab} kelime`;
  } else {
    $('lessonSrsMeta').textContent = '✓ Tekrar konuları güncel';
  }
}

function showMotivation(text) {
  const el = $('motivationBanner');
  if (!text) {
    el.classList.add('hidden');
    return;
  }
  el.textContent = text;
  el.classList.remove('hidden');
}

function renderProgressBar(label, pct, color) {
  return `<div class="prog-row">
    <div class="prog-label"><span>${label}</span><span>${pct}%</span></div>
    <div class="prog-bar"><div class="prog-fill" style="width:${pct}%;background:${color}"></div></div>
  </div>`;
}

function renderWeekProgress(data) {
  if (!data) return '<p class="empty-hint">Henüz yeterli veri yok.</p>';
  const wp = data.weeklyProgress || data;
  let html = `
    ${renderProgressBar('Konuşma', wp.speaking || 0, 'linear-gradient(90deg,#38BDF8,#6366F1)')}
    ${renderProgressBar('Gramer', wp.grammar || 0, '#A78BFA')}
    ${renderProgressBar('Kelime', wp.vocabulary || 0, '#34D399')}
    ${renderProgressBar('Akıcılık', wp.fluency || 0, '#FBBF24')}
  `;
  if (wp.days?.length) {
    html += '<div class="week-days"><span class="week-days-title">Günlük dakika</span><div class="week-chart">';
    const maxMin = Math.max(...wp.days.map((d) => d.minutes || 0), 1);
    wp.days.forEach((d) => {
      const h = Math.max(4, Math.round(((d.minutes || 0) / maxMin) * 48));
      const dayLabel = d.date.slice(5);
      html += `<div class="week-bar-col" title="${d.date}: ${d.minutes || 0} dk">
        <div class="week-bar" style="height:${h}px"></div>
        <span>${dayLabel}</span>
      </div>`;
    });
    html += '</div></div>';
  }
  return html;
}

function renderSessionLog(log) {
  const items = log || S.profile?.sessionLog || [];
  if (!items.length) return '<p class="empty-hint">Henüz kayıtlı konuşma yok.</p>';
  return items.slice(0, 15).map((s) => `
    <article class="history-item">
      <div class="history-item-top">
        <strong>${formatDate(s.date)}</strong>
        <span class="history-level">${esc(s.level || 'A1')}</span>
      </div>
      <div class="history-item-meta">
        <span>⏱ ${s.minutes || 0} dk</span>
        <span>💬 ${s.sentences || '—'} cümle</span>
        ${s.corrections != null ? `<span>✏️ ${s.corrections} düzeltme</span>` : ''}
      </div>
      <div class="history-item-topic">${esc(s.topic || s.weakArea || 'Konuşma')}</div>
    </article>`).join('');
}

function renderCorrectionCard(detail) {
  if (!detail) return '';
  const parts = [];
  if (detail.userSaid) {
    parts.push(`<div class="corr-row corr-wrong"><span>❌ Senin cümlen</span><p>${esc(detail.userSaid)}</p></div>`);
  }
  if (detail.correctEn) {
    parts.push(`<div class="corr-row corr-right"><span>✅ Doğrusu (EN)</span><p>${esc(detail.correctEn)}</p></div>`);
  }
  if (detail.explainTr) {
    parts.push(`<div class="corr-row corr-tip"><span>💡 Türkçe</span><p>${esc(detail.explainTr)}</p></div>`);
  } else if (detail.explainEn) {
    parts.push(`<div class="corr-row corr-tip"><span>💡 Açıklama</span><p>${esc(detail.explainEn)}</p></div>`);
  }
  return `<div class="correction-card">${parts.join('')}</div>`;
}

function render() {
  const el = $('messages');
  if (!S.msgs.length) {
    el.innerHTML = `<div class="chat-welcome">
      <div class="chat-welcome-avatar">🤖</div>
      <p>Merhaba! Ben senin öğretmeninim.<br>
      <strong>İngilizce konuş</strong> veya <strong>yaz</strong> — hatalarını Türkçe açıklarım,<br>
      cevabımı hem Türkçe hem İngilizce görürsün.</p></div>`;
    $('clearBtn').classList.add('hidden');
    return;
  }
  $('clearBtn').classList.remove('hidden');
  const lg = getLang(S.learnLang);
  el.innerHTML = S.msgs.map((m, i) => {
    const time = m.time ? `<span class="chat-time">${m.time}</span>` : '';
    if (m.role === 'user') {
      return `<div class="chat-row chat-row-user">
        <div class="chat-bubble chat-bubble-user">
          <div class="chat-meta">Sen · ${time}</div>
          <div class="chat-text">${esc(m.text)}</div>
        </div></div>`;
    }
    const teacherEn = m.teacherEn || m.teacher || '';
    const teacherTr = m.teacherTr || m.explain || '';
    let corr = m.correctionDetail ? renderCorrectionCard(m.correctionDetail) : '';
    if (!corr && m.correction && m.correctionLevel >= 2) {
      corr = renderCorrectionCard({
        userSaid: m.userSaid,
        correctEn: m.correction,
        explainTr: m.explain,
      });
    }
    const vocab = m.newWord
      ? `<div class="chat-vocab">📚 <strong>${esc(m.newWord.word)}</strong> = ${esc(m.newWord.meaningTr)}</div>` : '';
    return `<div class="chat-row chat-row-teacher">
        <div class="chat-avatar">🤖</div>
        <div class="chat-bubble chat-bubble-teacher">
          <div class="chat-meta">Öğretmen · ${lg.flag} ${lg.name} · ${time}</div>
          ${teacherEn ? `<div class="chat-lang-block chat-en"><span>${lg.flag} ${lg.name}</span><p>${esc(teacherEn).replace(/\n/g, '<br>')}</p></div>` : ''}
          ${teacherTr ? `<div class="chat-lang-block chat-tr"><span>🇹🇷 Türkçe</span><p>${esc(teacherTr).replace(/\n/g, '<br>')}</p></div>` : ''}
          ${corr}${vocab}
          ${m.audio ? `<button type="button" class="replay-btn chat-replay" data-idx="${i}">🔊 Dinle</button>` : ''}
        </div></div>`;
  }).join('');
  el.querySelectorAll('.chat-replay').forEach((btn) => {
    btn.onclick = (e) => {
      e.preventDefault();
      unlockAudioSync();
      playB64(S.msgs[parseInt(btn.dataset.idx, 10)].audio);
    };
  });
  requestAnimationFrame(() => {
    el.scrollTop = el.scrollHeight;
  });
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

function chatTime() {
  return new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
}

function appendUserMsg(text, lang) {
  S.msgs.push({ role: 'user', text, lang: lang || S.learnLang, time: chatTime() });
  saveChat();
  pushHistory('user', text);
}

function appendTeacherMsg(d) {
  const teacherEn = d.teacher_en || d.robot_target || d.teacher_text || '';
  const teacherTr = d.teacher_tr || d.explain_tr || '';
  S.msgs.push({
    role: 'teacher',
    teacher: d.teacher_text || teacherEn,
    teacherEn,
    teacherTr,
    explain: teacherTr,
    correction: d.correction || '',
    correctionLevel: d.correction_level || 1,
    correctionDetail: d.correction_detail || null,
    userSaid: d.user_text || '',
    targetLang: d.target_lang || S.learnLang,
    audio: d.audio || null,
    type: d.type,
    newWord: d.new_word || null,
    time: chatTime(),
  });
  saveChat();
  pushHistory('teacher', teacherEn);
}

function handleEducationResult(d) {
  if (d.profile) {
    S.profile = d.profile;
    saveProfile();
    updateLevelBadge();
    updateDailyGoal();
  }
  if (d.weekly_progress || d.weeklyProgress) {
    S.weeklyProgress = d.weekly_progress || d.weeklyProgress;
  }
  if (d.daily_lesson) updatePersonalLesson(d.daily_lesson);
  if (d.motivation) showMotivation(d.motivation);

  if (d.user_text) appendUserMsg(d.user_text, d.user_lang);
  appendTeacherMsg(d);
  hideTyping();
  render();
  if (d.audio) playB64(d.audio);
}

async function processEducationChat(text) {
  const r = await fetch(`/api/education/chat?${new URLSearchParams({ lang: S.learnLang })}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      profile: S.profile,
      history: S.history,
      roleplay: S.roleplay || null,
      speak_slow: S.speakSlow,
      user_lang: 'tr',
    }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'Bağlantı sorunu. Tekrar dene.');
  return d;
}

async function sendTextMessage() {
  const input = $('textInput');
  const text = input.value.trim();
  if (!text || S.busyCount > 0 || isRecording()) return;
  input.value = '';
  hideErr();
  S.busyCount += 1;
  showTyping();
  setUiState('PROCESSING');
  try {
    const d = await processEducationChat(text);
    handleEducationResult(d);
  } catch (e) {
    hideTyping();
    showErr(e.message || 'Gönderilemedi');
  } finally {
    S.busyCount -= 1;
    resetIdle();
  }
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

async function fetchLessonPlan() {
  try {
    const params = new URLSearchParams({ profile: JSON.stringify(S.profile || {}) });
    const r = await fetch(`/api/education/lesson-plan?${params}`);
    const d = await r.json().catch(() => ({}));
    if (r.ok) updatePersonalLesson(d);
  } catch { /* ignore */ }
}

async function fetchGreeting() {
  if (S.greetingLoaded && S.msgs.length > 0) return;
  S.busyCount += 1;
  showTyping();
  setUiState('PROCESSING');
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
    S.sessionSaved = false;
  } catch (e) {
    hideTyping();
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
    S.msgs.push({
      role: 'teacher',
      teacher: d.robot_target,
      teacherEn: d.robot_target,
      teacherTr: d.robot_tr,
      explain: d.robot_tr,
      targetLang: d.target_lang,
      audio: d.audio,
      type: 'lesson',
      time: chatTime(),
    });
    saveChat();
    render();
    if (d.audio) playB64(d.audio);
  } catch (e) {
    showErr(e.message);
  } finally {
    S.busyCount -= 1;
    resetIdle();
  }
}

function getSessionMinutes() {
  return S.sessionStart ? (Date.now() - S.sessionStart) / 60000 : 0;
}

async function endSession() {
  const mins = getSessionMinutes();
  if (mins < 0.3 || S.sessionSaved) return;
  S.sessionSaved = true;
  try {
    const weak = (S.profile?.weakAreas || ['conversation'])[0];
    const r = await fetch('/api/education/session-end', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        profile: S.profile,
        minutes: mins,
        topic: weak.replace(/_/g, ' '),
      }),
    });
    const d = await r.json().catch(() => ({}));
    if (r.ok && d.profile) {
      S.profile = d.profile;
      saveProfile();
      updateDailyGoal();
      S.weeklyProgress = d.weeklyProgress;
    }
  } catch { /* ignore */ }
}

function switchReportTab(tab) {
  document.querySelectorAll('.modal-tab').forEach((t) => {
    t.classList.toggle('active', t.dataset.tab === tab);
  });
  $('tabToday').classList.toggle('hidden', tab !== 'today');
  $('tabWeek').classList.toggle('hidden', tab !== 'week');
  $('tabHistory').classList.toggle('hidden', tab !== 'history');
}

async function showReport() {
  switchReportTab('today');
  const mins = getSessionMinutes();
  const total = Math.max(S.profile?.totalSentences || 0, 1);
  const correct = S.profile?.correctSentences || 0;
  const corrections = S.profile?.sessionCorrections ?? S.profile?.totalCorrections ?? 0;
  const grammar = Math.min(100, Math.round((correct / total) * 100));
  const vocab = Math.min(100, 50 + (S.profile?.newWords?.length || 0) * 5);
  const fluency = Math.min(100, Math.round(40 + mins * 3));
  const weak = (S.profile?.weakAreas || []).slice(0, 3).map((w) => w.replace(/_/g, ' ')).join(', ') || '—';
  const strong = (S.profile?.strongAreas || ['Konuşma isteği']).slice(0, 2).join(', ');

  $('reportContent').innerHTML = `
    <div class="report-row"><span>Konuşma süresi</span><strong>${mins.toFixed(1)} dk</strong></div>
    <div class="report-row"><span>Cümleler</span><strong>${total}</strong></div>
    <div class="report-row"><span>Doğru cümleler</span><strong>${correct}</strong></div>
    <div class="report-row"><span>Düzeltmeler</span><strong>${corrections}</strong></div>
    <div class="report-row"><span>Yeni kelimeler</span><strong>${S.profile?.newWords?.length || 0}</strong></div>
    <div class="report-row"><span>Gramer</span><strong>${grammar}%</strong></div>
    <div class="report-row"><span>Kelime</span><strong>${vocab}%</strong></div>
    <div class="report-row"><span>Akıcılık</span><strong>${fluency}%</strong></div>
    <div class="report-row"><span>Tahmini seviye</span><strong>${S.profile?.currentLevel || 'A1'}</strong></div>
    <div class="report-row"><span>Zayıf alanlar</span><strong>${esc(weak)}</strong></div>
    <div class="report-row"><span>Güçlü alanlar</span><strong>${esc(strong)}</strong></div>`;

  $('weekProgress').innerHTML = renderWeekProgress(S.weeklyProgress || { weeklyProgress: S.weeklyProgress });
  $('historyContent').innerHTML = renderSessionLog();
  $('reportModal').classList.remove('hidden');

  await endSession();
  if (S.weeklyProgress) {
    $('weekProgress').innerHTML = renderWeekProgress({ weeklyProgress: S.weeklyProgress });
  }
  $('historyContent').innerHTML = renderSessionLog();
}

function showHistoryModal() {
  $('historyModalContent').innerHTML = renderSessionLog();
  $('historyModal').classList.remove('hidden');
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
  $('conversationSubtitle').textContent = `${lg.name} konuş veya yaz`;
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
    fetchLessonPlan();
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
    const bytes = new Uint8Array(buf);
    let b64 = '';
    const chunk = 8192;
    for (let i = 0; i < bytes.length; i += chunk) {
      b64 += String.fromCharCode(...bytes.subarray(i, i + chunk));
    }
    playB64(btoa(b64));
  } catch { /* ignore */ }
};

$('lessonChips').querySelectorAll('.chip').forEach((chip) => {
  chip.onclick = () => loadLesson(chip.dataset.lesson);
});

$('clearBtn').onclick = () => {
  if (!isRecording() && S.busyCount === 0) {
    endSession();
    S.msgs = [];
    saveChat();
    S.history = [];
    saveHistory();
    S.greetingLoaded = false;
    S.sessionStart = null;
    render();
    fetchGreeting();
  }
};

$('sendBtn').onclick = () => sendTextMessage();
$('textInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    sendTextMessage();
  }
});

document.querySelectorAll('.modal-tab').forEach((tab) => {
  tab.onclick = () => switchReportTab(tab.dataset.tab);
});

$('reportBtn').onclick = () => showReport();
$('historyBtn').onclick = () => showHistoryModal();
$('closeReport').onclick = () => $('reportModal').classList.add('hidden');
$('closeHistory').onclick = () => $('historyModal').classList.add('hidden');
$('reportModal').querySelector('.edu-modal-backdrop').onclick = () => $('reportModal').classList.add('hidden');
$('historyModal').querySelector('.edu-modal-backdrop').onclick = () => $('historyModal').classList.add('hidden');

bindHold($('micBtn'));

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') endSession();
});
window.addEventListener('pagehide', () => endSession());

S.profile = loadProfile();
S.history = loadHistory();
S.msgs = loadChat();
S.learnLang = S.profile.targetLang || 'en';
syncLearnLang();
updateLevelBadge();
updateDailyGoal();
fetchLessonPlan();
render();
if (S.msgs.length > 0) {
  S.greetingLoaded = true;
  S.sessionStart = Date.now();
} else {
  resetIdle();
  fetchGreeting();
}

if (!navigator.mediaDevices?.getUserMedia) {
  showErr('Mikrofon için Safari gerekli');
  $('micBtn').disabled = true;
}

/**
 * Kendini Test Et — profesyonel UI
 */
(function () {
  'use strict';

  const LS = window.LearnStorage;
  const TAIL_MS = 280;
  const MIN_HOLD_MS = 350;
  const MIN_BLOB_BYTES = 400;

  const audio = document.createElement('audio');
  audio.setAttribute('playsinline', 'true');
  document.body.appendChild(audio);

  const S = {
    learnLang: LS.getLang(),
    tab: 'word',
    quizCount: 10,
    hardOnly: false,
    queue: [],
    index: 0,
    current: null,
    lastResult: null,
    holdActive: false,
    holdGen: 0,
    stream: null,
    recorder: null,
    chunks: [],
    fingerDownAt: 0,
    stopHandled: false,
    usedTouch: false,
    stopTimer: null,
    safetyTimer: null,
    micOpening: false,
    micOpenGen: 0,
    pendingEndHold: false,
    busy: false,
  };

  let mic;

  const $ = (id) => document.getElementById(id);

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  function setQuizStatus(text, live) {
    const el = $('quizStatus');
    const dot = $('quizStatusDot');
    if (el) el.textContent = text || '';
    if (dot) dot.classList.toggle('active', !!live);
  }

  function setMicLabel(title, sub) {
    const t = $('micTitle');
    const s = $('micSubtitle');
    if (t) t.textContent = title;
    if (s) s.textContent = sub || '';
  }

  function initLangSelect() {
    const sel = $('learnLang');
    if (!sel) return;
    sel.innerHTML = LS.LANGUAGES.map(
      (l) => `<option value="${l.code}">${l.flag} ${l.name}</option>`,
    ).join('');
    sel.value = LS.getLang();
    S.learnLang = sel.value;
    updateLangLabel();
    sel.addEventListener('change', () => {
      LS.setLang(sel.value);
      S.learnLang = sel.value;
      updateLangLabel();
      updateEmptyHint();
      renderSavedSummary();
    });
  }

  function updateLangLabel() {
    const info = LS.langInfo(S.learnLang);
    const el = $('langLabel');
    if (el) el.textContent = `${info.flag} ${info.name}`;
  }

  function switchTab(tab) {
    S.tab = tab;
    document.querySelectorAll('.mod-tab').forEach((b) => {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    updateEmptyHint();
  }

  function updateEmptyHint() {
    const items = S.tab === 'word' ? LS.getWords(S.learnLang) : LS.getSentences(S.learnLang);
    $('quizEmptyHint')?.classList.toggle('hidden', items.length > 0);
  }

  function renderSavedSummary() {
    const words = LS.getWords(S.learnLang);
    const sentences = LS.getSentences(S.learnLang);
    const box = $('savedSummary');
    if (!box) return;
    const wLines = words.slice(0, 6).map(
      (w) => `<div class="mod-saved-item-static"><span>☕ ${esc(w.word_tr)}</span><small>${LS.learningLevel(w.stats)} · ${w.stats?.attempts || 0} deneme</small></div>`,
    ).join('');
    const sLines = sentences.slice(0, 6).map(
      (s) => `<div class="mod-saved-item-static"><span>"${esc(s.tr_sentence)}"</span><small>${LS.learningLevel(s.stats)}</small></div>`,
    ).join('');
    box.innerHTML = `
      <p class="mod-summary-count">${words.length} kelime · ${sentences.length} cümle</p>
      ${wLines || ''}${sLines || ''}`;
  }

  function showSetup() {
    $('quizSetup')?.classList.remove('hidden');
    $('quizActive')?.classList.add('hidden');
    $('quizDock')?.classList.add('hidden');
    S.queue = [];
    S.index = 0;
    S.current = null;
    updateEmptyHint();
  }

  function showActive() {
    $('quizSetup')?.classList.add('hidden');
    $('quizActive')?.classList.remove('hidden');
    $('quizDock')?.classList.remove('hidden');
    $('quizResult')?.classList.add('hidden');
    $('quizActions')?.classList.add('hidden');
  }

  function startQuiz() {
    const items = LS.pickQuizItems(S.tab, S.quizCount, S.learnLang, S.hardOnly);
    if (!items.length) {
      setQuizStatus('Önce Cümle Kur ile kayıt ekle', false);
      return;
    }
    S.queue = items;
    S.index = 0;
    showActive();
    showQuestion();
  }

  function showQuestion() {
    S.current = S.queue[S.index];
    S.lastResult = null;
    $('quizResult')?.classList.add('hidden');
    $('quizActions')?.classList.add('hidden');
    setQuizStatus('Basılı tut ve hedef dilde konuş', false);
    setMicLabel('Basılı Tut ve Konuş', 'Hedef dilde cevap ver');

    $('quizProgress').textContent = `${S.index + 1} / ${S.queue.length}`;
    $('quizModeLabel').textContent = S.tab === 'word' ? 'Kelime testi' : 'Cümle testi';

    const prompt = $('quizPrompt');
    if (!prompt || !S.current) return;

    if (S.tab === 'word') {
      prompt.innerHTML = `
        <div class="mod-quiz-word">${esc(S.current.word_tr.toUpperCase())}</div>
        <p class="mod-quiz-instr">Bu kelimeyi kullanarak hedef dilde bir cümle kur.</p>`;
    } else {
      prompt.innerHTML = `
        <div class="mod-quiz-sent">${esc(S.current.tr_sentence)}</div>
        <p class="mod-quiz-instr">Bu cümleyi hedef dilde söyle.</p>`;
    }
  }

  function scoreIcon(ok) {
    if (ok === true) return '✅';
    if (ok === false) return '❌';
    return '⚠️';
  }

  function renderResult(result) {
    S.lastResult = result;
    const box = $('quizResult');
    if (!box) return;
    box.classList.remove('hidden');
    $('quizActions')?.classList.remove('hidden');

    const pronIssues = (result.pronunciation_issues || []).map(
      (p) => `<li>${esc(p.word)} — <em>${esc(p.hint_tr)}</em></li>`,
    ).join('');

    box.innerHTML = `
      <h3>🎯 ${result.score || 0} / 100</h3>
      <p class="mod-result-you"><strong>Sen:</strong> ${esc(result.user_answer)}</p>
      ${result.correct_answer ? `<p class="mod-result-ok"><strong>Doğrusu:</strong> ${esc(result.correct_answer)}</p>` : ''}
      <div class="mod-score-grid">
        <span>Cümle ${scoreIcon(result.sentence_ok)}</span>
        <span>Gramer ${scoreIcon(result.grammar_ok)}</span>
        <span>Kelime ${scoreIcon(result.vocabulary_ok)}</span>
        <span>Telaffuz ${result.pronunciation_ok === null || result.pronunciation_ok === undefined ? '⚠️' : scoreIcon(result.pronunciation_ok)}</span>
        <span>Doğallık ${scoreIcon(result.naturalness_ok)}</span>
      </div>
      ${result.feedback_tr ? `<p class="mod-detail-text">${esc(result.feedback_tr)}</p>` : ''}
      ${result.why_tr ? `<p class="mod-warn">${esc(result.why_tr)}</p>` : ''}
      ${result.tense_note_tr ? `<p class="mod-warn">${esc(result.tense_note_tr)}</p>` : ''}
      ${result.pronunciation_note_tr ? `<p class="mod-pron-note">${esc(result.pronunciation_note_tr)}</p>` : ''}
      ${pronIssues ? `<ul class="mod-parts">${pronIssues}</ul>` : ''}`;

    LS.recordPractice(S.tab, S.current.id, result);
    renderSavedSummary();
    $('modScroll')?.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function playTts(text, lang) {
    const q = (text || '').trim().slice(0, 600);
    if (!q) return;
    const r = await fetch(`/api/tts?${new URLSearchParams({ q, tl: lang })}`);
    if (!r.ok) return;
    const blob = await r.blob();
    if (!blob.size) return;
    const u = URL.createObjectURL(blob);
    audio.src = u;
    try { await audio.play(); } catch { /* ignore */ }
  }

  async function gradeAnswer(text) {
    if (!text || !S.current) return;
    S.busy = true;
    setQuizStatus('🔄 Analiz ediliyor…', true);

    const body = S.tab === 'word'
      ? { word_tr: S.current.word_tr, target_word: S.current.target_word, user_answer: text, lang: S.learnLang }
      : { tr_sentence: S.current.tr_sentence, expected_target: S.current.target_sentence, alternatives: S.current.alternatives || [], user_answer: text, lang: S.learnLang };

    const endpoint = S.tab === 'word' ? '/api/builder/grade-word' : '/api/builder/grade-sentence';

    try {
      const r = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok || data.error_tr) {
        setQuizStatus(data.error_tr || 'Değerlendirme yapılamadı', false);
        return;
      }
      setQuizStatus('Sonuç hazır', false);
      renderResult(data);
      setMicLabel('Tekrar konuşabilirsin', 'veya Sonraki');
    } catch {
      setQuizStatus('Bağlantı hatası', false);
    } finally {
      S.busy = false;
    }
  }

  async function onMicBlob(blob) {
    if (S.busy || !blob || blob.size < MIN_BLOB_BYTES) {
      setQuizStatus('Kayıt kısa — basılı tut', false);
      return;
    }
    setQuizStatus('🔄 Dinleniyor…', true);
    try {
      const r = await fetch(`/api/stt?lang=${encodeURIComponent(S.learnLang)}`, { method: 'POST', body: blob });
      const data = await r.json();
      const text = (data.text || '').trim();
      if (!text) {
        setQuizStatus('Anlaşılamadı — tekrar dene', false);
        return;
      }
      await gradeAnswer(text);
    } catch {
      setQuizStatus('Ses algılanamadı', false);
    }
  }

  function initMic() {
    if (!window.MicHold) return;
    mic = MicHold.create({
      state: S,
      tailMs: TAIL_MS,
      minHoldMs: MIN_HOLD_MS,
      minBlobBytes: MIN_BLOB_BYTES,
      onSpeaking: () => {
        setQuizStatus('🎤 Dinleniyor…', true);
        setMicLabel('Konuşun…', 'Bırakınca analiz');
      },
      onProcessing: () => setQuizStatus('🔄 Analiz ediliyor…', true),
      onIdle: () => { if (!S.busy) setQuizStatus('Basılı tut ve hedef dilde konuş', false); },
      onError: (msg) => setQuizStatus(msg || 'Tekrar dene', false),
      isBusy: () => S.busy,
      canBegin: () => !S.busy,
      onBlob: (blob) => { void onMicBlob(blob); },
    });
    mic.bindHold($('micBtn'));
  }

  function nextQuestion() {
    S.index += 1;
    if (S.index >= S.queue.length) {
      setQuizStatus('🎉 Test tamamlandı!', false);
      showSetup();
      renderSavedSummary();
      return;
    }
    showQuestion();
  }

  function init() {
    initLangSelect();
    renderSavedSummary();
    initMic();

    document.querySelectorAll('.mod-tab').forEach((btn) => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    document.querySelectorAll('.mod-chip[data-count]').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.mod-chip[data-count]').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        S.quizCount = Number(btn.dataset.count) || 10;
      });
    });

    $('hardOnly')?.addEventListener('change', (e) => { S.hardOnly = e.target.checked; });
    $('startQuizBtn')?.addEventListener('click', startQuiz);
    $('retryBtn')?.addEventListener('click', () => {
      $('quizResult')?.classList.add('hidden');
      $('quizActions')?.classList.add('hidden');
      setQuizStatus('Basılı tut ve tekrar dene', false);
      setMicLabel('Basılı Tut ve Konuş', 'Tekrar dene');
    });
    $('nextBtn')?.addEventListener('click', nextQuestion);
    $('listenCorrectBtn')?.addEventListener('click', () => {
      const ans = S.lastResult?.correct_answer
        || (S.tab === 'sentence' ? S.current?.target_sentence : null);
      if (ans) playTts(ans, S.learnLang);
    });

    updateEmptyHint();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());

/**
 * Cümle Kur — Kelime + Cümle (profesyonel UI + bas-konuş giriş)
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

  const micS = {
    holdActive: false, holdGen: 0, stream: null, recorder: null, chunks: [],
    fingerDownAt: 0, pressMs: 0, stopHandled: false, usedTouch: false,
    stopTimer: null, safetyTimer: null, micOpening: false, micOpenGen: 0, pendingEndHold: false,
  };

  let currentWordLesson = null;
  let currentSentence = null;
  let activeTab = 'word';
  let busy = false;
  let wordMic = null;
  let sentenceMic = null;
  let searchTimer = null;

  const $ = (id) => document.getElementById(id);

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  function setUi(text, live) {
    const dot = $('statusDot');
    const st = $('statusText');
    if (st) st.textContent = text;
    if (dot) dot.classList.toggle('active', !!live);
  }

  function initLangSelect() {
    const sel = $('learnLang');
    if (!sel) return;
    sel.innerHTML = LS.LANGUAGES.map(
      (l) => `<option value="${l.code}">${l.flag} ${l.name}</option>`,
    ).join('');
    sel.value = LS.getLang();
    updateLangLabel();
    sel.addEventListener('change', () => {
      LS.setLang(sel.value);
      updateLangLabel();
      renderSavedLists();
    });
  }

  function updateLangLabel() {
    const info = LS.langInfo(LS.getLang());
    const el = $('langLabel');
    if (el) el.textContent = `${info.flag} ${info.name}`;
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
    audio.onended = () => URL.revokeObjectURL(u);
    audio.onerror = () => URL.revokeObjectURL(u);
    try { await audio.play(); } catch { /* ignore */ }
  }

  function renderWordBreakdown(ex) {
    const items = ex.word_breakdown || ex.parts || [];
    if (!items.length) return '';
    return `<ul class="mod-parts">${items.map((p) => {
      const tok = p.token || p.tr || '';
      const role = p.role_tr ? `<small>${esc(p.role_tr)}</small>` : '';
      return `<li><span class="mod-part-tr">${esc(tok)}</span>${role}<span class="mod-part-mean">${esc(p.meaning_tr || '')}</span></li>`;
    }).join('')}</ul>`;
  }

  function renderPatternBlock(ex) {
    if (!ex.pattern_tr && !(ex.pattern_examples || []).length) return '';
    const examples = (ex.pattern_examples || []).map((p) => `<li>${esc(p)}</li>`).join('');
    return `
      <div class="mod-pattern">
        <strong>🎯 ${esc(ex.pattern_tr || 'Bu kalıbı unutma')}</strong>
        ${examples ? `<ul class="mod-pattern-examples">${examples}</ul>` : ''}
      </div>`;
  }

  function renderPronunciationBlock(ex, lang, cardId) {
    const ipa = ex.ipa || '';
    const words = ex.word_pronunciations || [];
    const wordRows = words.map((w) => `
      <div class="mod-word-pron">
        <span class="mod-word-pron-en">${esc(w.word)}</span>
        <span class="mod-word-pron-tr">${esc(w.pronunciation_tr)}</span>
        ${w.ipa ? `<span class="mod-word-pron-ipa hidden" data-ipa-for="${cardId}">${esc(w.ipa)}</span>` : ''}
      </div>`).join('');
    return `
      <div class="mod-pron-block">
        <div class="mod-pron-row">
          <span class="mod-pron-label">🗣️ Okunuş</span>
          <span class="mod-pron-value">${esc(ex.pronunciation_tr || '')}</span>
        </div>
        ${ipa ? `<div class="mod-ipa-row hidden" data-ipa-panel="${cardId}"><span class="mod-ipa-label">IPA</span> ${esc(ipa)}</div>` : ''}
        ${wordRows ? `<div class="mod-word-pron-list">${wordRows}</div>` : ''}
        ${ipa ? `<button type="button" class="mod-ipa-toggle" data-ipa-toggle="${cardId}">IPA göster</button>` : ''}
      </div>`;
  }

  function bindIpaToggles(root) {
    root?.querySelectorAll('.mod-ipa-toggle').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.ipaToggle;
        const panel = root.querySelector(`[data-ipa-panel="${id}"]`);
        const wordIpas = root.querySelectorAll(`[data-ipa-for="${id}"]`);
        const show = panel?.classList.contains('hidden');
        panel?.classList.toggle('hidden', !show);
        wordIpas.forEach((el) => el.classList.toggle('hidden', !show));
        btn.textContent = show ? 'IPA gizle' : 'IPA göster';
      });
    });
  }

  function renderTeachingBlock(ex) {
    const how = ex.how_it_is_formed_tr || ex.explanation_tr || '';
    const why = ex.why_this_structure_tr || '';
    const note = ex.important_note_tr || '';
    const label = ex.structure_label_tr || '';
    return `
      <details class="mod-details" open>
        <summary>🧠 Nasıl kuruldu?</summary>
        <div class="mod-detail-text mod-detail-pre">${esc(how)}</div>
        ${why ? `<p class="mod-detail-why">${esc(why)}</p>` : ''}
        ${note ? `<p class="mod-warn">${esc(note)}</p>` : ''}
        ${ex.structure_tr ? `<p class="mod-structure">📚 ${esc(ex.structure_tr)}</p>` : ''}
        ${label ? `<p class="mod-structure-label">${esc(label)}</p>` : ''}
        ${renderWordBreakdown(ex)}
        ${renderPatternBlock(ex)}
      </details>`;
  }

  function renderExampleCard(ex, lang, idx) {
    const cardId = `ex-${idx}`;
    const typeBadge = ex.sentence_type ? `<span class="mod-badge">${esc(ex.sentence_type)}</span>` : '';
    return `
      <article class="mod-card" data-idx="${idx}">
        ${typeBadge}
        <div class="mod-card-line mod-card-tr"><span class="mod-flag">🇹🇷</span>${esc(ex.tr)}</div>
        <div class="mod-card-line mod-card-target"><span class="mod-flag">🌍</span>${esc(ex.target)}</div>
        <button type="button" class="mod-listen-btn builder-listen" data-text="${esc(ex.target)}" data-lang="${lang}">🔊 Cümleyi dinle</button>
        ${renderPronunciationBlock(ex, lang, cardId)}
        ${renderTeachingBlock(ex)}
      </article>`;
  }

  function bindListenButtons(root) {
    root?.querySelectorAll('.builder-listen').forEach((btn) => {
      btn.addEventListener('click', () => playTts(btn.dataset.text, btn.dataset.lang));
    });
  }

  function renderWordLesson(data) {
    const box = $('wordResult');
    if (!box || !data?.ok) return;
    currentWordLesson = data;
    const lang = data.target_lang;
    const usage = data.usage || {};
    const patterns = (usage.patterns || []).map((p) => `<li>${esc(p)}</li>`).join('');
    const examples = (data.examples || []).map((ex, i) => renderExampleCard(ex, lang, i)).join('');
    box.innerHTML = `
      <div class="mod-hero mod-hero-green">
        <div class="mod-hero-icon">☕</div>
        <div>
          <h2>${esc(data.word_tr)}</h2>
          <p class="mod-hero-sub">${esc(data.target_word)}</p>
        </div>
      </div>
      ${data.word_explanation_tr ? `<p class="mod-lead">${esc(data.word_explanation_tr)}</p>` : ''}
      <div class="mod-info-card">
        <h3>Kelime kullanımı</h3>
        ${usage.noun_tr ? `<p><strong>İsim:</strong> ${esc(usage.noun_tr)}</p>` : ''}
        ${usage.verb_tr ? `<p><strong>Fiil:</strong> ${esc(usage.verb_tr)}</p>` : ''}
        ${usage.formal_tr ? `<p><strong>Resmi:</strong> ${esc(usage.formal_tr)}</p>` : ''}
        ${usage.informal_tr ? `<p><strong>Samimi:</strong> ${esc(usage.informal_tr)}</p>` : ''}
        ${patterns ? `<ul class="mod-tags">${patterns}</ul>` : ''}
        ${usage.common_mistakes_tr ? `<p class="mod-warn">⚠️ ${esc(usage.common_mistakes_tr)}</p>` : ''}
      </div>
      <h3 class="mod-section-title">Örnek cümleler</h3>
      ${examples}
      <button type="button" id="saveWordBtn" class="mod-action-btn mod-action-save">⭐ Öğrendiklerime Ekle</button>`;
    box.querySelector('#saveWordBtn')?.addEventListener('click', saveCurrentWord);
    bindListenButtons(box);
    bindIpaToggles(box);
    $('modScroll')?.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function saveCurrentWord() {
    if (!currentWordLesson) return;
    const saved = LS.saveWord({
      word_tr: currentWordLesson.word_tr,
      target_word: currentWordLesson.target_word,
      target_lang: currentWordLesson.target_lang,
      word_explanation_tr: currentWordLesson.word_explanation_tr,
      usage: currentWordLesson.usage,
      examples: currentWordLesson.examples,
    });
    setUi(`✅ "${saved.word_tr}" kaydedildi`, false);
    renderSavedLists();
  }

  function renderSentenceResult(data) {
    const box = $('sentenceResult');
    if (!box || !data?.ok) return;
    currentSentence = data;
    const cardId = 'sent-0';
    const chunks = (data.pronunciation_chunks || []).map(
      (c) => `<div class="mod-chunk"><span>${esc(c.target)}</span><em>${esc(c.pronunciation_tr)}</em>${c.ipa ? `<small class="mod-chunk-ipa hidden" data-ipa-for="${cardId}">${esc(c.ipa)}</small>` : ''}</div>`,
    ).join('');
    box.innerHTML = `
      <div class="mod-hero mod-hero-blue">
        <div class="mod-hero-icon">💬</div>
        <div><h2>Cümle analizi</h2></div>
      </div>
      <article class="mod-card mod-card-featured">
        <div class="mod-card-line mod-card-tr"><span class="mod-flag">🇹🇷</span>${esc(data.tr_sentence)}</div>
        <div class="mod-card-line mod-card-target"><span class="mod-flag">🌍</span>${esc(data.target_sentence)}</div>
        <button type="button" class="mod-listen-btn builder-listen" data-text="${esc(data.target_sentence)}" data-lang="${data.target_lang}">🔊 Cümleyi dinle</button>
        ${renderPronunciationBlock(data, data.target_lang, cardId)}
        ${chunks ? `<div class="mod-chunks"><h4>Telaffuz parçaları</h4>${chunks}</div>` : ''}
        ${renderTeachingBlock(data)}
      </article>
      <button type="button" id="saveSentenceBtn" class="mod-action-btn mod-action-save">⭐ Kaydet</button>`;
    box.querySelector('#saveSentenceBtn')?.addEventListener('click', saveCurrentSentence);
    bindListenButtons(box);
    bindIpaToggles(box);
    $('modScroll')?.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function saveCurrentSentence() {
    if (!currentSentence) return;
    LS.saveSentence({
      tr_sentence: currentSentence.tr_sentence,
      target_sentence: currentSentence.target_sentence,
      target_lang: currentSentence.target_lang,
      pronunciation_tr: currentSentence.pronunciation_tr,
      ipa: currentSentence.ipa,
      word_pronunciations: currentSentence.word_pronunciations,
      how_it_is_formed_tr: currentSentence.how_it_is_formed_tr,
      grammar_explanation_tr: currentSentence.grammar_explanation_tr,
      structure_tr: currentSentence.structure_tr,
      phrase_pairs: currentSentence.phrase_pairs,
      alternatives: currentSentence.alternatives,
      pronunciation_chunks: currentSentence.pronunciation_chunks,
    });
    setUi('✅ Cümle kaydedildi', false);
    renderSavedLists();
  }

  function showLoading(msg) {
    const id = activeTab === 'word' ? 'wordResult' : 'sentenceResult';
    const box = $(id);
    if (box) {
      box.innerHTML = `<div class="mod-loading"><span class="mod-spinner"></span><p>${esc(msg)}</p></div>`;
    }
    setUi(msg, true);
  }

  async function buildWord() {
    const word = ($('wordInput')?.value || '').trim();
    if (word.length < 2) {
      setUi('En az 2 harfli bir kelime gir veya söyle', false);
      return;
    }
    if (busy) return;
    busy = true;
    showLoading('Cümleler oluşturuluyor…');
    try {
      const r = await fetch('/api/builder/word', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ word, lang: LS.getLang() }),
      });
      const data = await r.json();
      if (!r.ok || !data.ok) {
        $('wordResult').innerHTML = '';
        setUi(data.error_tr || 'Bir hata oluştu', false);
        return;
      }
      setUi('Hazır — dinle ve kaydet', false);
      renderWordLesson(data);
    } catch {
      $('wordResult').innerHTML = '';
      setUi('Bağlantı hatası — tekrar dene', false);
    } finally {
      busy = false;
    }
  }

  async function buildSentence() {
    const sentence = ($('sentenceInput')?.value || '').trim();
    if (sentence.length < 4) {
      setUi('En az 4 karakterli cümle gir veya söyle', false);
      return;
    }
    if (busy) return;
    busy = true;
    showLoading('Cümle analiz ediliyor…');
    try {
      const r = await fetch('/api/builder/sentence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sentence, lang: LS.getLang() }),
      });
      const data = await r.json();
      if (!r.ok || !data.ok) {
        $('sentenceResult').innerHTML = '';
        setUi(data.error_tr || 'Bir hata oluştu', false);
        return;
      }
      setUi('Hazır — dinle ve kaydet', false);
      renderSentenceResult(data);
    } catch {
      $('sentenceResult').innerHTML = '';
      setUi('Bağlantı hatası — tekrar dene', false);
    } finally {
      busy = false;
    }
  }

  async function sttTurkish(blob, targetInputId, thenSubmit) {
    if (!blob || blob.size < MIN_BLOB_BYTES) {
      setUi('Kayıt kısa — basılı tutup konuş', false);
      return;
    }
    setUi('🔄 Dinleniyor…', true);
    try {
      const r = await fetch('/api/stt?lang=tr', { method: 'POST', body: blob });
      const data = await r.json();
      const text = (data.text || '').trim();
      if (!text) {
        setUi('Anlaşılamadı — tekrar dene', false);
        return;
      }
      const input = $(targetInputId);
      if (input) input.value = text;
      setUi(`✓ "${text.slice(0, 40)}${text.length > 40 ? '…' : ''}"`, false);
      if (thenSubmit) {
        if (targetInputId === 'wordInput') await buildWord();
        else await buildSentence();
      }
    } catch {
      setUi('Ses algılanamadı', false);
    }
  }

  function makeInputMic(btnId, inputId, thenSubmit) {
    if (!window.MicHold) return null;
    const localS = { ...micS };
    const mic = MicHold.create({
      state: localS,
      tailMs: TAIL_MS,
      minHoldMs: MIN_HOLD_MS,
      minBlobBytes: MIN_BLOB_BYTES,
      onSpeaking: () => setUi('🎤 Dinleniyor…', true),
      onProcessing: () => setUi('🔄 Yazıya çevriliyor…', true),
      onIdle: () => { if (!busy) setUi('Kelime veya cümle yaz — veya 🎤 ile söyle', false); },
      onError: (m) => setUi(m || 'Tekrar dene', false),
      isBusy: () => busy,
      canBegin: () => !busy,
      onBlob: (blob) => { void sttTurkish(blob, inputId, thenSubmit); },
    });
    mic.bindHold($(btnId));
    return mic;
  }

  function renderSavedLists() {
    const lang = LS.getLang();
    const wordQ = ($('wordSearch')?.value || '').trim();
    const sentQ = ($('sentenceSearch')?.value || '').trim();
    const words = wordQ ? LS.searchItems(wordQ, lang).words : LS.getWords(lang);
    const sentences = sentQ ? LS.searchItems(sentQ, lang).sentences : LS.getSentences(lang);

    const wBox = $('savedWords');
    if (wBox) {
      wBox.innerHTML = words.length
        ? words.map((w) => `
          <button type="button" class="mod-saved-item" data-word-id="${w.id}">
            <span class="mod-saved-icon">☕</span>
            <span class="mod-saved-text">${esc(w.word_tr)}<small>${LS.learningLevel(w.stats)}</small></span>
          </button>`).join('')
        : '<p class="mod-empty">Henüz kelime yok</p>';
      wBox.querySelectorAll('[data-word-id]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const w = LS.getWordById(btn.dataset.wordId);
          if (w) {
            switchTab('word');
            currentWordLesson = { ok: true, ...w };
            renderWordLesson(currentWordLesson);
            $('wordInput').value = w.word_tr;
          }
        });
      });
    }

    const sBox = $('savedSentences');
    if (sBox) {
      sBox.innerHTML = sentences.length
        ? sentences.map((s) => `
          <button type="button" class="mod-saved-item" data-sent-id="${s.id}">
            <span class="mod-saved-icon">💬</span>
            <span class="mod-saved-text">${esc(s.tr_sentence)}<small>${LS.learningLevel(s.stats)}</small></span>
          </button>`).join('')
        : '<p class="mod-empty">Henüz cümle yok</p>';
      sBox.querySelectorAll('[data-sent-id]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const s = LS.getSentenceById(btn.dataset.sentId);
          if (s) {
            switchTab('sentence');
            currentSentence = { ok: true, ...s };
            renderSentenceResult(currentSentence);
            $('sentenceInput').value = s.tr_sentence;
          }
        });
      });
    }
  }

  function switchTab(tab) {
    activeTab = tab;
    document.querySelectorAll('.mod-tab').forEach((b) => {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    $('panelWord')?.classList.toggle('hidden', tab !== 'word');
    $('panelSentence')?.classList.toggle('hidden', tab !== 'sentence');
    $('wordComposer')?.classList.toggle('hidden', tab !== 'word');
    $('sentenceComposer')?.classList.toggle('hidden', tab !== 'sentence');
    setUi(tab === 'word' ? 'Türkçe kelime yaz veya 🎤 ile söyle' : 'Türkçe cümle yaz veya 🎤 ile söyle', false);
  }

  function debouncedSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderSavedLists, 200);
  }

  function init() {
    initLangSelect();
    renderSavedLists();
    wordMic = makeInputMic('wordMicBtn', 'wordInput', true);
    sentenceMic = makeInputMic('sentenceMicBtn', 'sentenceInput', true);

    $('wordGoBtn')?.addEventListener('click', buildWord);
    $('sentenceGoBtn')?.addEventListener('click', buildSentence);
    $('wordInput')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') buildWord(); });
    $('sentenceInput')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') buildSentence(); });
    $('wordSearch')?.addEventListener('input', debouncedSearch);
    $('sentenceSearch')?.addEventListener('input', debouncedSearch);

    document.querySelectorAll('.mod-tab').forEach((btn) => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());

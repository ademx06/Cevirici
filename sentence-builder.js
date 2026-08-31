/**
 * Cümle Kur — Kelime + Cümle modülleri
 */
(function () {
  'use strict';

  const LS = window.LearnStorage;
  const audio = document.createElement('audio');
  audio.setAttribute('playsinline', 'true');
  document.body.appendChild(audio);

  let currentWordLesson = null;
  let currentSentence = null;

  const $ = (id) => document.getElementById(id);

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  function setStatus(el, text, type) {
    if (!el) return;
    el.textContent = text || '';
    el.classList.toggle('hidden', !text);
    el.classList.toggle('builder-status-error', type === 'error');
    el.classList.toggle('builder-status-busy', type === 'busy');
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

  function renderExampleCard(ex, lang, idx) {
    const parts = (ex.parts || []).map(
      (p) => `<li><strong>${esc(p.tr)}</strong> → ${esc(p.meaning_tr)}</li>`,
    ).join('');
    return `
      <article class="builder-card" data-idx="${idx}">
        <div class="builder-card-row">🇹🇷 ${esc(ex.tr)}</div>
        <div class="builder-card-row builder-card-target">🌍 ${esc(ex.target)}</div>
        <button type="button" class="ghost-btn builder-listen" data-text="${esc(ex.target)}" data-lang="${lang}">🔊 Dinle</button>
        <div class="builder-pron">🗣️ ${esc(ex.pronunciation_tr || '')}</div>
        <details class="builder-details">
          <summary>🧠 Nasıl kuruldu?</summary>
          <p>${esc(ex.explanation_tr || '')}</p>
          ${ex.structure_tr ? `<p class="builder-structure">📚 ${esc(ex.structure_tr)}</p>` : ''}
          ${parts ? `<ul class="builder-parts">${parts}</ul>` : ''}
        </details>
      </article>`;
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
      <div class="builder-lesson-head">
        <h2>☕ ${esc(data.word_tr)} → ${esc(data.target_word)}</h2>
        <p>${esc(data.word_explanation_tr || '')}</p>
      </div>
      <div class="builder-usage">
        <h3>📚 Kelime kullanımı</h3>
        ${usage.noun_tr ? `<p><strong>İsim:</strong> ${esc(usage.noun_tr)}</p>` : ''}
        ${usage.verb_tr ? `<p><strong>Fiil:</strong> ${esc(usage.verb_tr)}</p>` : ''}
        ${usage.formal_tr ? `<p><strong>Resmi:</strong> ${esc(usage.formal_tr)}</p>` : ''}
        ${usage.informal_tr ? `<p><strong>Samimi:</strong> ${esc(usage.informal_tr)}</p>` : ''}
        ${patterns ? `<ul>${patterns}</ul>` : ''}
        ${usage.common_mistakes_tr ? `<p class="builder-mistake">⚠️ ${esc(usage.common_mistakes_tr)}</p>` : ''}
      </div>
      <div class="builder-examples">${examples}</div>
      <button type="button" id="saveWordBtn" class="primary-btn builder-save-btn">⭐ Öğrendiklerime Ekle</button>`;
    box.querySelector('#saveWordBtn')?.addEventListener('click', saveCurrentWord);
    box.querySelectorAll('.builder-listen').forEach((btn) => {
      btn.addEventListener('click', () => playTts(btn.dataset.text, btn.dataset.lang));
    });
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
    setStatus($('wordStatus'), `✅ "${saved.word_tr}" kaydedildi!`, 'ok');
    renderSavedLists();
  }

  function renderSentenceResult(data) {
    const box = $('sentenceResult');
    if (!box || !data?.ok) return;
    currentSentence = data;
    const pairs = (data.phrase_pairs || []).map(
      (p) => `<li>${esc(p.tr)} → ${esc(p.en)}</li>`,
    ).join('');
    const chunks = (data.pronunciation_chunks || []).map(
      (c) => `<div class="builder-chunk"><span>${esc(c.target)}</span><em>${esc(c.pronunciation_tr)}</em></div>`,
    ).join('');
    box.innerHTML = `
      <article class="builder-card builder-card-sentence">
        <div class="builder-card-row">🇹🇷 ${esc(data.tr_sentence)}</div>
        <div class="builder-card-row builder-card-target">🌍 ${esc(data.target_sentence)}</div>
        <button type="button" class="ghost-btn builder-listen" data-text="${esc(data.target_sentence)}" data-lang="${data.target_lang}">🔊 Dinle</button>
        <div class="builder-pron">🗣️ ${esc(data.pronunciation_tr || '')}</div>
        ${chunks ? `<div class="builder-chunks"><h4>Telaffuz parçaları</h4>${chunks}</div>` : ''}
        <details class="builder-details" open>
          <summary>🧠 Cümle nasıl kuruldu?</summary>
          <p>${esc(data.grammar_explanation_tr || data.why_tr || '')}</p>
          ${data.structure_tr ? `<p class="builder-structure">📚 ${esc(data.structure_tr)}</p>` : ''}
          ${pairs ? `<ul class="builder-parts">${pairs}</ul>` : ''}
        </details>
        <button type="button" id="saveSentenceBtn" class="primary-btn builder-save-btn">⭐ Kaydet</button>
      </article>`;
    box.querySelector('#saveSentenceBtn')?.addEventListener('click', saveCurrentSentence);
    box.querySelector('.builder-listen')?.addEventListener('click', (e) => {
      const btn = e.currentTarget;
      playTts(btn.dataset.text, btn.dataset.lang);
    });
  }

  function saveCurrentSentence() {
    if (!currentSentence) return;
    const saved = LS.saveSentence({
      tr_sentence: currentSentence.tr_sentence,
      target_sentence: currentSentence.target_sentence,
      target_lang: currentSentence.target_lang,
      pronunciation_tr: currentSentence.pronunciation_tr,
      grammar_explanation_tr: currentSentence.grammar_explanation_tr,
      structure_tr: currentSentence.structure_tr,
      phrase_pairs: currentSentence.phrase_pairs,
      alternatives: currentSentence.alternatives,
      pronunciation_chunks: currentSentence.pronunciation_chunks,
    });
    setStatus($('sentenceStatus'), `✅ Cümle kaydedildi!`, 'ok');
    renderSavedLists();
  }

  async function buildWord() {
    const word = ($('wordInput')?.value || '').trim();
    if (word.length < 2) {
      setStatus($('wordStatus'), 'En az 2 harfli bir kelime gir.', 'error');
      return;
    }
    setStatus($('wordStatus'), '⏳ Cümleler oluşturuluyor...', 'busy');
    $('wordResult').innerHTML = '';
    try {
      const r = await fetch('/api/builder/word', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ word, lang: LS.getLang() }),
      });
      const data = await r.json();
      if (!r.ok || !data.ok) {
        setStatus($('wordStatus'), data.error_tr || 'Bir hata oluştu.', 'error');
        return;
      }
      setStatus($('wordStatus'), '');
      renderWordLesson(data);
    } catch {
      setStatus($('wordStatus'), 'Bağlantı hatası — tekrar dene.', 'error');
    }
  }

  async function buildSentence() {
    const sentence = ($('sentenceInput')?.value || '').trim();
    if (sentence.length < 4) {
      setStatus($('sentenceStatus'), 'En az 4 karakterli bir cümle gir.', 'error');
      return;
    }
    setStatus($('sentenceStatus'), '⏳ Cümle analiz ediliyor...', 'busy');
    $('sentenceResult').innerHTML = '';
    try {
      const r = await fetch('/api/builder/sentence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sentence, lang: LS.getLang() }),
      });
      const data = await r.json();
      if (!r.ok || !data.ok) {
        setStatus($('sentenceStatus'), data.error_tr || 'Bir hata oluştu.', 'error');
        return;
      }
      setStatus($('sentenceStatus'), '');
      renderSentenceResult(data);
    } catch {
      setStatus($('sentenceStatus'), 'Bağlantı hatası — tekrar dene.', 'error');
    }
  }

  function renderSavedLists() {
    const lang = LS.getLang();
    const wordQ = ($('wordSearch')?.value || '').trim();
    const sentQ = ($('sentenceSearch')?.value || '').trim();
    const words = wordQ
      ? LS.searchItems(wordQ, lang).words
      : LS.getWords(lang);
    const sentences = sentQ
      ? LS.searchItems(sentQ, lang).sentences
      : LS.getSentences(lang);

    const wBox = $('savedWords');
    if (wBox) {
      wBox.innerHTML = words.length
        ? words.map((w) => `
          <button type="button" class="builder-saved-item" data-word-id="${w.id}">
            ☕ ${esc(w.word_tr)} <small>${LS.learningLevel(w.stats)}</small>
          </button>`).join('')
        : '<p class="builder-empty">Henüz kelime kaydedilmedi.</p>';
      wBox.querySelectorAll('[data-word-id]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const w = LS.getWordById(btn.dataset.wordId);
          if (w) {
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
          <button type="button" class="builder-saved-item" data-sent-id="${s.id}">
            "${esc(s.tr_sentence)}" <small>${LS.learningLevel(s.stats)}</small>
          </button>`).join('')
        : '<p class="builder-empty">Henüz cümle kaydedilmedi.</p>';
      sBox.querySelectorAll('[data-sent-id]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const s = LS.getSentenceById(btn.dataset.sentId);
          if (s) {
            currentSentence = { ok: true, ...s };
            renderSentenceResult(currentSentence);
            $('sentenceInput').value = s.tr_sentence;
          }
        });
      });
    }
  }

  function switchTab(tab) {
    document.querySelectorAll('.builder-tab').forEach((b) => {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    $('panelWord')?.classList.toggle('hidden', tab !== 'word');
    $('panelSentence')?.classList.toggle('hidden', tab !== 'sentence');
  }

  function init() {
    initLangSelect();
    renderSavedLists();

    $('wordGoBtn')?.addEventListener('click', buildWord);
    $('sentenceGoBtn')?.addEventListener('click', buildSentence);
    $('wordInput')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') buildWord();
    });
    $('sentenceInput')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') buildSentence();
    });
    $('wordSearch')?.addEventListener('input', renderSavedLists);
    $('sentenceSearch')?.addEventListener('input', renderSavedLists);

    document.querySelectorAll('.builder-tab').forEach((btn) => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());

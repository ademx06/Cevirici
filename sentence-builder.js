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
  let wordRequestSeq = 0;
  let sentenceRequestSeq = 0;

  const $ = (id) => document.getElementById(id);

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  const GENERIC_ICONS = new Set(['📖', '📚', '📦', '']);
  const CATEGORY_ICONS = {
    beverage: '🥤', furniture: '🛋️', plumbing: '🚰', vehicle: '🚗',
    adjective: '😊', place: '📍', footwear: '👟',
    food: '🍽️', fruit: '🍎', vegetable: '🥕', animal: '🐾', drinkware: '🥛',
    abstract: '🌱', tobacco: '🚬', eyewear: '👓', snack: '🍬', document: '🧾',
  };

  function resolveWordIcon(wordOrData, apiIcon) {
    const data = typeof wordOrData === 'object' && wordOrData ? wordOrData : null;
    const word = data ? (data.word_tr || data.word || '') : String(wordOrData || '');
    const target = data?.target_word || '';
    const key = String(word || '').trim().toLowerCase();
    const targetKey = String(target || '').trim().toLowerCase();
    // Backend tek kaynak — API ikonu öncelikli
    const apiResolved = apiIcon || data?.word_icon || '';
    if (apiResolved && !GENERIC_ICONS.has(apiResolved)) return apiResolved;
    const map = {
      kahve: '☕', coffee: '☕', çay: '🍵', tea: '🍵',
      musluk: '🚰', faucet: '🚰', tap: '🚰',
      kapı: '🚪', kapi: '🚪', door: '🚪', araba: '🚗', car: '🚗',
      ev: '🏠', house: '🏠', home: '🏠', telefon: '📱', phone: '📱',
      kitap: '📚', book: '📚', masa: '🍽️', table: '🍽️',
      sandalye: '💺', chair: '💺', pencere: '🪟', window: '🪟',
      su: '💧', water: '💧', kalem: '✏️', pen: '✏️',
      mutlu: '😊', happy: '😊',
      ayakkabı: '👟', ayakkabi: '👟', shoe: '👟', shoes: '👟',
      soda: '🥤', gazoz: '🥤', kola: '🥤', cola: '🥤',
      bardak: '🥛', glass: '🥛', glasses: '🥛', fincan: '☕', cup: '☕',
      süt: '🥛', milk: '🥛', ekmek: '🍞', bread: '🍞',
      mısır: '🌽', misir: '🌽', corn: '🌽', sweetcorn: '🌽',
      kedi: '🐱', cat: '🐱', köpek: '🐶', dog: '🐶',
    };
    if (map[key]) return map[key];
    if (map[targetKey]) return map[targetKey];
    const cat = data?.word_profile?.semantic_category;
    if (cat && CATEGORY_ICONS[cat]) return CATEGORY_ICONS[cat];
    const keywordIcons = [
      [['mısır', 'misir', 'corn', 'sweetcorn'], '🌽'],
      [['kahve', 'çay', 'gazoz', 'kola', 'soda', 'su', 'süt'], '🥤'],
      [['masa', 'table'], '🍽️'],
      [['sandalye', 'chair'], '💺'],
      [['ayakkabı', 'ayakkabi', 'bot'], '👟'],
      [['araba', 'otomobil', 'bisiklet'], '🚗'],
      [['musluk', 'lavabo', 'duş'], '🚰'],
      [['kapı', 'kapi', 'pencere'], '🪟'],
      [['kitap', 'defter', 'gazete'], '📚'],
      [['telefon', 'bilgisayar', 'tablet'], '📱'],
      [['mutlu', 'üzgün', 'yorgun'], '😊'],
      [['çalış', 'calis', 'koş'], '💼'],
      [['ev', 'market', 'okul', 'hastane'], '📍'],
      [['yemek', 'ekmek', 'peynir'], '🍽️'],
      [['bardak', 'fincan', 'tabak'], '🥛'],
      [['kedi', 'köpek', 'kuş'], '🐾'],
    ];
    for (const [keys, em] of keywordIcons) {
      if (keys.some((k) => key.includes(k))) return em;
    }
    return '🏷️';
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

  function formatIpa(ipa) {
    const raw = (ipa || '').trim();
    if (!raw) return '';
    return raw.startsWith('/') ? raw : `/${raw}/`;
  }

  function formatPronLine(pron, ipa) {
    const ipaStr = formatIpa(ipa);
    if (ipaStr && pron) return `🗣️ ${ipaStr} (${pron})`;
    if (ipaStr) return `🗣️ ${ipaStr}`;
    if (pron) return `🗣️ ${pron}`;
    return '';
  }

  function renderCardActions(ex, lang, idx) {
    return `
      <div class="mod-card-actions">
        <button type="button" class="mod-listen-btn builder-listen" data-text="${esc(ex.target)}" data-lang="${lang}">🔊 Dinle</button>
        <button type="button" class="mod-detail-btn builder-sentence-detail" data-ex-idx="${idx}" data-lang="${lang}">📖 Cümle detay</button>
      </div>`;
  }

  function mergeDetailWordRows(ex) {
    const breakdown = ex.word_breakdown || [];
    const pronList = ex.word_pronunciations || [];
    const byToken = Object.fromEntries(
      breakdown.map((p) => [(p.token || '').toLowerCase(), p]),
    );
    if (pronList.length) {
      return pronList.map((w) => {
        const key = (w.word || '').toLowerCase();
        const meta = byToken[key] || {};
        return {
          token: w.word,
          pronunciation_tr: w.pronunciation_tr || meta.pronunciation_tr || '',
          ipa: w.ipa || meta.ipa || '',
          meaning_tr: meta.meaning_tr || w.meaning_tr || '',
          role_tr: meta.role_tr || '',
        };
      });
    }
    return breakdown;
  }

  function buildDetailFallback(ex) {
    const parts = mergeDetailWordRows(ex).map((p) => {
      const tok = p.token || '';
      const mean = p.meaning_tr || '';
      const role = p.role_tr || '';
      if (!tok) return '';
      return `• «${tok}»${mean ? ` = ${mean}` : ''}${role ? ` (${role})` : ''}`;
    }).filter(Boolean);
    if (!parts.length) return '';
    return 'Kelime kelime:\n' + parts.join('\n');
  }

  function showSentenceDetailModal(ex, lang) {
    const existing = document.querySelector('.mod-sentence-detail-overlay');
    if (existing) existing.remove();
    const how = ex.how_it_is_formed_tr || ex.explanation_tr || buildDetailFallback(ex);
    const why = ex.why_this_structure_tr || '';
    const note = ex.important_note_tr || '';
    const structure = ex.structure_tr || ex.structure_label_tr || '';
    const typeLabel = ex.scenario_badge || ex.sentence_type_label || ex.sentence_type || '';
    const cardId = `detail-${Date.now()}`;
    const detailRows = mergeDetailWordRows(ex);
    const wbHtml = renderWordBreakdown({ ...ex, word_breakdown: detailRows });
    const wbLines = detailRows.map((p) => {
      const tok = p.token || '';
      const pron = formatPronLine(p.pronunciation_tr || p.pronunciation_hint, p.ipa);
      const mean = p.meaning_tr || '';
      const role = p.role_tr || '';
      if (!tok) return '';
      return `<div class="mod-detail-word-row">
        <strong>${esc(tok)}</strong>
        ${pron ? `<span class="mod-pron-inline">${pron}</span>` : ''}
        ${mean ? `<span>→ ${esc(mean)}</span>` : ''}
        ${role ? `<small>(${esc(role)})</small>` : ''}
        <button type="button" class="mod-listen-btn builder-listen mod-listen-sm" data-text="${esc(tok)}" data-lang="${lang}">🔊</button>
      </div>`;
    }).join('');
    const overlay = document.createElement('div');
    overlay.className = 'mod-sentence-detail-overlay';
    overlay.innerHTML = `
      <div class="mod-sentence-detail mod-sentence-detail-rich" role="dialog" aria-label="Cümle detayı">
        <button type="button" class="mod-popup-close" aria-label="Kapat">×</button>
        <h3>📖 Cümle detayı</h3>
        <p class="mod-detail-lead">Sıfırdan öğrenen birine anlatır gibi — kelime kelime, neden böyle kuruldu</p>
        ${typeLabel ? `<span class="mod-badge">${esc(typeLabel)}</span>` : ''}
        <div class="mod-card-line mod-card-tr"><span class="mod-flag">🇹🇷</span>${esc(ex.tr || '')}</div>
        <div class="mod-card-line mod-card-target"><span class="mod-flag">🇺🇸</span>${esc(ex.target || '')}</div>
        ${renderPronunciationBlock(ex, lang, cardId)}
        <div class="mod-card-actions mod-card-actions-inline">
          <button type="button" class="mod-listen-btn builder-listen" data-text="${esc(ex.target)}" data-lang="${lang}">🔊 Cümleyi dinle</button>
        </div>
        ${how ? `<div class="mod-detail-section"><h4>🧠 Adım adım açıklama</h4><div class="mod-detail-text mod-teach-body">${formatTeachingText(how)}</div></div>` : ''}
        ${wbLines ? `<div class="mod-detail-section"><h4>🔤 Kelime kelime</h4><div class="mod-detail-words">${wbLines}</div></div>` : ''}
        ${wbHtml && !wbLines ? `<div class="mod-detail-section"><h4>🔤 Kelimeler</h4>${wbHtml}</div>` : ''}
        ${structure ? `<div class="mod-detail-section"><h4>📐 Cümle formülü</h4><code class="mod-detail-formula">${esc(structure)}</code></div>` : ''}
        ${why ? `<div class="mod-detail-section"><h4>💡 Neden böyle?</h4><p>${esc(why)}</p></div>` : ''}
        ${ex.pattern_tr ? `<div class="mod-detail-section"><h4>🎯 Kalıp</h4><p>${esc(ex.pattern_tr)}</p></div>` : ''}
        ${note ? `<p class="mod-warn">⚠️ ${esc(note)}</p>` : ''}
      </div>`;
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay || e.target.closest('.mod-popup-close')) overlay.remove();
    });
    document.body.appendChild(overlay);
    bindListenButtons(overlay);
    bindIpaToggles(overlay);
  }

  async function refreshLessonPronunciation(lesson) {
    if (!lesson?.examples?.length) return lesson;
    const texts = new Set();
    if (lesson.target_word) texts.add(lesson.target_word);
    lesson.examples.forEach((ex) => { if (ex?.target) texts.add(ex.target); });
    try {
      const { ok, data } = await ApiClient.fetchJson('/api/pronounce/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ texts: [...texts], lang: lesson.target_lang || 'en' }),
      }, { wakeFirst: false, retries: 1, timeoutMs: 12000 });
      if (!ok || !data?.bundles) return lesson;
      const bundles = data.bundles;
      if (lesson.target_word && bundles[lesson.target_word]) {
        const hero = bundles[lesson.target_word];
        lesson.pronunciation_tr = hero.pronunciation_tr;
        lesson.ipa = hero.ipa;
      }
      lesson.examples = lesson.examples.map((ex) => {
        const bundle = bundles[ex.target];
        if (!bundle) return ex;
        const pronMap = Object.fromEntries(
          (bundle.word_pronunciations || []).map((w) => [(w.word || '').toLowerCase(), w]),
        );
        const wordBreakdown = (ex.word_breakdown || []).map((p) => {
          const wp = pronMap[(p.token || '').toLowerCase()];
          if (!wp) return p;
          return {
            ...p,
            pronunciation_tr: wp.pronunciation_tr,
            ipa: wp.ipa || p.ipa,
          };
        });
        return {
          ...ex,
          pronunciation_tr: bundle.pronunciation_tr,
          ipa: bundle.ipa,
          word_pronunciations: bundle.word_pronunciations,
          word_breakdown: wordBreakdown.length ? wordBreakdown : ex.word_breakdown,
        };
      });
    } catch {
      /* kayıtlı ders — eski telaffuz kalsın */
    }
    return lesson;
  }

  function bindSentenceDetailButtons(root) {
    root?.querySelectorAll('.builder-sentence-detail').forEach((btn) => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.exIdx, 10);
        const lang = btn.dataset.lang || 'en';
        const ex = currentWordLesson?.examples?.[idx];
        if (ex) showSentenceDetailModal(ex, lang);
      });
    });
  }

  function renderUsageLineItem(item, lang, opts = {}) {
    if (!item?.en) return '';
    const listen = opts.listen !== false;
    const pronLine = formatPronLine(item.pronunciation_tr, item.ipa)
      || (item.pronunciation_tr ? `🗣️ ${esc(item.pronunciation_tr)}` : '');
    return `
      <div class="mod-phrase-item">
        <div class="mod-card-line"><span class="mod-flag">🇺🇸</span>${esc(item.en)}</div>
        ${item.tr ? `<div class="mod-card-line"><span class="mod-flag">🇹🇷</span>${esc(item.tr)}</div>` : ''}
        ${pronLine ? `<div class="mod-pron-row"><span class="mod-pron-label">${pronLine}</span></div>` : ''}
        ${listen ? `<button type="button" class="mod-listen-btn builder-listen mod-listen-sm" data-text="${esc(item.en)}" data-lang="${lang || 'en'}">🔊 Dinle</button>` : ''}
      </div>`;
  }

  function renderUsageVerbs(verbs, lang) {
    if (!verbs?.length) return '';
    return `<div class="mod-verb-list-wrap"><strong>Yaygın fiiller</strong><ul class="mod-verb-list">${
      verbs.map((v) => {
        const pronLine = formatPronLine(v.pronunciation_tr, v.ipa);
        return `<li>${esc(v.en)} → ${esc(v.tr || '')}${pronLine ? `<span class="mod-pron-inline">${pronLine}</span>` : ''}</li>`;
      }).join('')
    }</ul></div>`;
  }

  function renderUsagePatterns(patterns, lang) {
    if (!patterns?.length) return '';
    return `<div class="mod-patterns-usage"><strong>Örnek kalıplar</strong>${
      patterns.map((p) => renderUsageLineItem(p, lang)).join('')
    }</div>`;
  }
  function renderWordBreakdown(ex) {
    const items = ex.word_breakdown || ex.parts || [];
    if (!items.length) return '';
    const hasPron = items.some((p) => p.pronunciation_tr || p.pronunciation_hint || p.ipa);
    if (hasPron) {
      return `<table class="mod-wb-table"><thead><tr><th>İngilizce</th><th>Okunuş / IPA</th><th>Türkçesi</th><th>Görevi</th></tr></thead><tbody>${
        items.map((p) => {
          const tok = p.token || p.tr || '';
          const pron = p.pronunciation_tr || p.pronunciation_hint || '';
          const ipa = formatIpa(p.ipa);
          const pronCell = ipa && pron ? `${esc(pron)} ${esc(ipa)}` : esc(pron || ipa);
          return `<tr><td>${esc(tok)}</td><td>${pronCell}</td><td>${esc(p.meaning_tr || '')}</td><td>${esc(p.role_tr || '')}</td></tr>`;
        }).join('')
      }</tbody></table>`;
    }
    return `<ul class="mod-parts">${items.map((p) => {
      const tok = p.token || p.tr || '';
      const role = p.role_tr ? `<small>${esc(p.role_tr)}</small>` : '';
      return `<li><span class="mod-part-tr">${esc(tok)}</span>${role}<span class="mod-part-mean">${esc(p.meaning_tr || '')}</span></li>`;
    }).join('')}</ul>`;
  }

  function renderPatternBlock(ex, lang) {
    if (!ex.pattern_tr && !(ex.pattern_examples || []).length) return '';
    const examples = (ex.pattern_examples || []).map((p, i) => {
      if (typeof p === 'string') {
        return `<li>${esc(p)}</li>`;
      }
      const cardId = `pat-${i}`;
      const nw = (p.new_words || []).map((w) => `
        <button type="button" class="mod-nw-chip builder-word-chip" data-word="${esc(w.word)}" data-meaning="${esc(w.meaning_tr || '')}" data-pron="${esc(w.pronunciation_tr || '')}" data-example-target="${esc(w.example_target || '')}" data-example-tr="${esc(w.example_tr || '')}" data-lang="${lang}">
          ${esc(w.word)} → ${esc(w.meaning_tr || '')}${w.pronunciation_tr ? ` → ${esc(w.pronunciation_tr)}` : ''}
        </button>`).join('');
      return `
        <li class="mod-pattern-card">
          ${p.tr ? `<div class="mod-card-line mod-card-tr"><span class="mod-flag">🇹🇷</span>${esc(p.tr)}</div>` : ''}
          <div class="mod-card-line mod-card-target"><span class="mod-flag">🇺🇸</span>${esc(p.target)}</div>
          ${p.pronunciation_tr ? `<div class="mod-pron-row"><span class="mod-pron-label">🗣️ Okunuş</span><span class="mod-pron-value">${esc(p.pronunciation_tr)}</span></div>` : ''}
          <button type="button" class="mod-listen-btn builder-listen mod-listen-sm" data-text="${esc(p.target)}" data-lang="${lang}">🔊 Dinle</button>
          ${nw ? `<div class="mod-new-words"><strong>📖 Yeni kelimeler</strong>${nw}</div>` : ''}
        </li>`;
    }).join('');
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
        <span class="mod-word-pron-tr">${formatPronLine(w.pronunciation_tr, w.ipa) || esc(w.pronunciation_tr)}</span>
      </div>`).join('');
    return `
      <div class="mod-pron-block">
        <div class="mod-pron-row">
          <span class="mod-pron-label">${formatPronLine(ex.pronunciation_tr, ipa) || '🗣️ Okunuş'}</span>
          ${!formatPronLine(ex.pronunciation_tr, ipa) ? `<span class="mod-pron-value">${esc(ex.pronunciation_tr || '')}</span>` : ''}
        </div>
        ${ipa && !formatPronLine(ex.pronunciation_tr, ipa) ? `<div class="mod-ipa-row" data-ipa-panel="${cardId}"><span class="mod-ipa-label">IPA</span> ${esc(formatIpa(ipa))}</div>` : ''}
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

  function isMobileView() {
    return window.matchMedia('(max-width: 520px)').matches;
  }

  function formatTeachingText(text) {
    const raw = String(text || '').trim();
    if (!raw) return '';
    return raw.split(/\n+/).map((line) => {
      const t = line.trim();
      if (!t) return '';
      if (/^[1-9]️⃣/.test(t) || t.startsWith('❌')) {
        return `<p class="mod-teach-step mod-teach-heading">${esc(t)}</p>`;
      }
      return `<p class="mod-teach-step">${esc(t)}</p>`;
    }).filter(Boolean).join('');
  }

  function renderTeachingBlock(ex, lang, opts = {}) {
    const how = ex.how_it_is_formed_tr || ex.explanation_tr || buildDetailFallback(ex);
    const why = ex.why_this_structure_tr || '';
    const note = ex.important_note_tr || '';
    const label = ex.structure_label_tr || '';
    const pattern = ex.pattern_tr || '';
    // Cümle modülünde varsayılan açık — detay kaybolmasın
    const forceOpen = opts.open !== false;
    const open = (opts.open || (forceOpen && how)) ? ' open' : '';
    if (!how && !why && !note && !ex.structure_tr) {
      return '';
    }
    return `
      <details class="mod-details mod-teach-details"${open}>
        <summary>🧠 Nasıl kuruldu? <span class="mod-teach-hint">dil bilgisi adım adım</span></summary>
        <div class="mod-detail-text mod-teach-body">${formatTeachingText(how)}</div>
        ${why ? `<p class="mod-detail-why">💡 ${esc(why)}</p>` : ''}
        ${note ? `<p class="mod-warn">⚠️ ${esc(note)}</p>` : ''}
        ${ex.structure_tr ? `<p class="mod-structure">📐 Formül: <code>${esc(ex.structure_tr)}</code></p>` : ''}
        ${label && !label.includes(ex.structure_tr || '___') ? `<p class="mod-structure-label">${esc(label)}</p>` : ''}
        ${pattern ? `<p class="mod-pattern-tr">${esc(pattern)}</p>` : ''}
        ${renderWordBreakdown(ex)}
        ${renderPatternBlock(ex, lang)}
      </details>`;
  }

  function renderExampleCard(ex, lang, idx, compact) {
    const cardId = `ex-${idx}`;
    const typeLabel = ex.scenario_badge || ex.sentence_type_label || ex.sentence_type || '';
    const typeBadge = typeLabel ? `<span class="mod-badge">${esc(typeLabel)}</span>` : '';
    const pronLine = formatPronLine(ex.pronunciation_tr, ex.ipa)
      || (ex.pronunciation_tr ? `🗣️ ${esc(ex.pronunciation_tr)}` : '');
    const useCompact = compact || (isMobileView() && idx > 0);
    if (useCompact) {
      return `
      <article class="mod-card mod-card-compact" data-idx="${idx}">
        ${typeBadge}
        <div class="mod-card-line mod-card-tr"><span class="mod-flag">🇹🇷</span>${esc(ex.tr)}</div>
        <div class="mod-card-line mod-card-target"><span class="mod-flag">🇺🇸</span>${esc(ex.target)}</div>
        ${pronLine ? `<p class="mod-pron-inline">${pronLine}</p>` : ''}
        ${renderCardActions(ex, lang, idx)}
      </article>`;
    }
    return `
      <article class="mod-card" data-idx="${idx}">
        ${typeBadge}
        <div class="mod-card-line mod-card-tr"><span class="mod-flag">🇹🇷</span>${esc(ex.tr)}</div>
        <div class="mod-card-line mod-card-target"><span class="mod-flag">🌍</span>${esc(ex.target)}</div>
        ${pronLine ? `<p class="mod-pron-inline">${pronLine}</p>` : ''}
        ${renderCardActions(ex, lang, idx)}
        ${renderPronunciationBlock(ex, lang, cardId)}
      </article>`;
  }

  function bindWordChips(root, lang) {
    root?.querySelectorAll('.builder-word-chip').forEach((btn) => {
      btn.addEventListener('click', () => showWordPopup(btn, lang));
    });
  }

  function showWordPopup(btn, lang) {
    const existing = document.querySelector('.mod-word-popup-overlay');
    if (existing) existing.remove();
    const word = btn.dataset.word || '';
    const meaning = btn.dataset.meaning || '';
    const pron = btn.dataset.pron || '';
    const exTarget = btn.dataset.exampleTarget || '';
    const exTr = btn.dataset.exampleTr || '';
    const overlay = document.createElement('div');
    overlay.className = 'mod-word-popup-overlay';
    overlay.innerHTML = `
      <div class="mod-word-popup" role="dialog">
        <button type="button" class="mod-popup-close" aria-label="Kapat">×</button>
        <h4>${esc(word)}</h4>
        ${meaning ? `<p><strong>Türkçesi:</strong> ${esc(meaning)}</p>` : ''}
        ${pron ? `<p><strong>Okunuş:</strong> ${esc(pron)}</p>` : ''}
        <button type="button" class="mod-listen-btn builder-listen" data-text="${esc(word)}" data-lang="${lang}">🔊 Dinle</button>
        ${exTarget ? `<div class="mod-popup-example"><span class="mod-flag">🇺🇸</span>${esc(exTarget)}</div>` : ''}
        ${exTr ? `<div class="mod-popup-example"><span class="mod-flag">🇹🇷</span>${esc(exTr)}</div>` : ''}
      </div>`;
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay || e.target.closest('.mod-popup-close')) overlay.remove();
    });
    document.body.appendChild(overlay);
    bindListenButtons(overlay);
  }

  function bindListenButtons(root) {
    root?.querySelectorAll('.builder-listen').forEach((btn) => {
      btn.addEventListener('click', () => playTts(btn.dataset.text, btn.dataset.lang));
    });
  }

  function renderUsageMap(usage, lang) {
    if (!usage || typeof usage !== 'object') return '';
    const rows = [];
    if (usage.english_variant_tr) rows.push(`<p class="mod-variant">${esc(usage.english_variant_tr)}</p>`);
    if (usage.meaning_tr) rows.push(`<p><strong>Anlam:</strong> ${esc(usage.meaning_tr)}</p>`);
    if (usage.usage_notes_tr) rows.push(`<p class="mod-usage-note">${esc(usage.usage_notes_tr)}</p>`);
    if (usage.common_verbs?.length) {
      rows.push(renderUsageVerbs(usage.common_verbs, lang));
    } else if (usage.common_verbs_tr) {
      rows.push(`<p><strong>Yaygın fiiller:</strong> ${esc(usage.common_verbs_tr)}</p>`);
    }
    if (usage.common_phrases?.length) {
      rows.push(`<div class="mod-phrases-block"><strong>Yaygın ifadeler</strong>${
        usage.common_phrases.map((p) => renderUsageLineItem(p, lang)).join('')
      }</div>`);
    } else if (usage.collocations_tr) {
      rows.push(`<p><strong>Yaygın ifadeler:</strong> ${esc(usage.collocations_tr)}</p>`);
    }
    if (usage.article_notes_items?.length) {
      rows.push(`<div class="mod-article-notes"><strong>Artikel/Konteyner Notu</strong>${
        usage.article_notes_items.map((item) => renderUsageLineItem(item, lang, { listen: true })).join('')
      }</div>`);
    } else if (usage.article_notes_tr) {
      rows.push(`<p><strong>Artikel/Konteyner Notu:</strong> ${esc(usage.article_notes_tr)}</p>`);
    }
    if (usage.pattern_examples?.length) {
      rows.push(renderUsagePatterns(usage.pattern_examples, lang));
    } else if (usage.patterns?.length) {
      rows.push(`<ul class="mod-tags">${usage.patterns.map((p) => `<li>${esc(typeof p === 'string' ? p : p.en || '')}</li>`).join('')}</ul>`);
    }
    if (usage.alternative_terms_tr?.length) {
      rows.push(`<div class="mod-alt-terms"><strong>💡 Alternatif ifadeler</strong>${
        usage.alternative_terms_tr.map((t) => `
          <div class="mod-alt-term-item">
            <div class="mod-card-line"><span class="mod-flag">🇺🇸</span><strong>${esc(t.en)}</strong> → ${esc(t.tr || '')}</div>
            ${formatPronLine(t.pronunciation_tr, t.ipa) ? `<div class="mod-pron-row mod-pron-inline">${formatPronLine(t.pronunciation_tr, t.ipa)}</div>` : ''}
            ${t.note_tr ? `<p class="mod-alt-note">${esc(t.note_tr)}</p>` : ''}
          </div>`).join('')
      }</div>`);
    }
    if (usage.regional_note_tr) rows.push(`<p class="mod-regional">${esc(usage.regional_note_tr)}</p>`);
    return rows.length ? rows.join('') : '';
  }

  function renderImportantPatterns(patterns, lang) {
    if (!patterns?.length) return '';
    const blocks = patterns.map((p) => {
      const exs = (p.examples || []).map((e) => `
        <div class="mod-pattern-mini">
          <span class="mod-flag">🇺🇸</span>${esc(e.target)}
          ${e.tr ? `<br><span class="mod-flag">🇹🇷</span>${esc(e.tr)}` : ''}
        </div>`).join('');
      return `
        <div class="mod-pattern-item">
          <strong>⭐ ${esc(p.pattern_tr)}</strong>
          ${p.explanation_tr ? `<p>${esc(p.explanation_tr)}</p>` : ''}
          ${exs}
        </div>`;
    }).join('');
    return `<div class="mod-patterns-block"><h4>⭐ Bu cümleden öğrenilecek kalıplar</h4>${blocks}</div>`;
  }

  function renderClauseBreakdown(clauses) {
    if (!clauses?.length) return '';
    const rows = clauses.map((c) => `
      <div class="mod-clause">
        <div><span class="mod-flag">🇹🇷</span>${esc(c.clause_tr)}</div>
        <div><span class="mod-flag">🇺🇸</span>${esc(c.target)}</div>
        ${c.role_tr ? `<small>${esc(c.role_tr)}</small>` : ''}
      </div>`).join('');
    return `<div class="mod-clauses"><h4>Cümle parçaları</h4>${rows}</div>`;
  }

  function renderNewWordsList(words, lang) {
    if (!words?.length) return '';
    const chips = words.map((w) => `
      <button type="button" class="mod-nw-chip builder-word-chip" data-word="${esc(w.word)}" data-meaning="${esc(w.meaning_tr || '')}" data-pron="${esc(w.pronunciation_tr || '')}" data-example-target="${esc(w.example_target || '')}" data-example-tr="${esc(w.example_tr || '')}" data-lang="${lang}">
        ${esc(w.word)} → ${esc(w.meaning_tr || '')}
      </button>`).join('');
    return `<div class="mod-new-words"><strong>📖 Yeni kelimeler</strong>${chips}</div>`;
  }

  function renderWordLesson(data, expectedWord) {
    const box = $('wordResult');
    if (!box || !data?.ok) return;
    const inputWord = ($('wordInput')?.value || '').trim().toLowerCase();
    const wordKey = String(expectedWord || data.word_tr || '').trim().toLowerCase();
    if (wordKey && inputWord && wordKey !== inputWord) return;
    currentWordLesson = data;
    const lang = data.target_lang;
    const usage = data.usage || {};
    const usageMap = renderUsageMap(usage, lang);
    const icon = resolveWordIcon(data, data.word_icon);
    const examples = (data.examples || []).map((ex, i) => renderExampleCard(ex, lang, i, false)).join('');
    const heroPron = formatPronLine(data.pronunciation_tr, data.ipa);
    box.innerHTML = `
      <div class="mod-hero mod-hero-green">
        <div class="mod-hero-icon" id="wordHeroIcon">${icon}</div>
        <div>
          <h2>${esc(data.word_tr)}</h2>
          <p class="mod-hero-sub">${esc(data.target_word)}${heroPron ? ` · ${heroPron}` : ''}</p>
        </div>
      </div>
      ${data.word_explanation_tr ? `<p class="mod-lead">${esc(data.word_explanation_tr)}</p>` : ''}
      <div class="mod-info-card mod-info-collapsible">
        <details>
          <summary>📖 Kelime kullanım haritası</summary>
          <div class="mod-info-body">
            ${usageMap || (usage.noun_tr ? `<p>${esc(usage.noun_tr)}</p>` : '')}
            ${usage.common_mistakes_tr ? `<p class="mod-warn">⚠️ ${esc(usage.common_mistakes_tr)}</p>` : ''}
          </div>
        </details>
      </div>
      <h3 class="mod-section-title">13 örnek cümle <small class="mod-section-hint">AI · doğal kullanım</small></h3>
      ${examples}
      <button type="button" id="saveWordBtn" class="mod-action-btn mod-action-save">⭐ Öğrendiklerime Ekle</button>`;
    box.querySelector('#saveWordBtn')?.addEventListener('click', saveCurrentWord);
    bindListenButtons(box);
    bindIpaToggles(box);
    bindWordChips(box, lang);
    bindSentenceDetailButtons(box);
    $('modScroll')?.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function saveCurrentWord() {
    if (!currentWordLesson) return;
    const saved = LS.saveWord({
      word_tr: currentWordLesson.word_tr,
      target_word: currentWordLesson.target_word,
      word_icon: resolveWordIcon(currentWordLesson, currentWordLesson.word_icon),
      pronunciation_tr: currentWordLesson.pronunciation_tr,
      ipa: currentWordLesson.ipa,
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
    const inferred = data.inferred_turkish_tr ? `<p class="mod-inferred">💡 Sanırım demek istediğin: «${esc(data.inferred_turkish_tr)}»</p>` : '';
    const meaning = data.meaning_summary_tr ? `<p class="mod-lead">${esc(data.meaning_summary_tr)}</p>` : '';
    const alts = (data.alternatives || []).filter(Boolean);
    const altBlock = alts.length ? `<div class="mod-alts"><strong>Alternatif:</strong> ${alts.map((a) => esc(a)).join(' · ')}</div>` : '';
    const grammarBadge = data.grammar_topic || data.sentence_type
      ? `<span class="mod-badge mod-badge-grammar">${esc(data.structure_label_tr || data.grammar_topic || '')}</span>`
      : '';
    box.innerHTML = `
      <div class="mod-hero mod-hero-blue">
        <div class="mod-hero-icon">💬</div>
        <div><h2>Cümle analizi</h2>${grammarBadge}</div>
      </div>
      ${inferred}
      ${meaning}
      <article class="mod-card mod-card-featured">
        <div class="mod-card-line mod-card-tr"><span class="mod-flag">🇹🇷</span>${esc(data.tr_sentence)}</div>
        <div class="mod-card-line mod-card-target"><span class="mod-flag">🌍</span>${esc(data.target_sentence)}</div>
        ${altBlock}
        <button type="button" class="mod-listen-btn builder-listen" data-text="${esc(data.target_sentence)}" data-lang="${data.target_lang}">🔊 Cümleyi dinle</button>
        ${renderPronunciationBlock(data, data.target_lang, cardId)}
        ${chunks ? `<div class="mod-chunks"><h4>Telaffuz parçaları</h4>${chunks}</div>` : ''}
        ${renderClauseBreakdown(data.clause_breakdown)}
        ${renderImportantPatterns(data.important_patterns, data.target_lang)}
        ${renderNewWordsList(data.new_words, data.target_lang)}
        ${renderTeachingBlock(data, data.target_lang, { open: true })}
      </article>
      <button type="button" id="saveSentenceBtn" class="mod-action-btn mod-action-save">⭐ Kaydet</button>`;
    box.querySelector('#saveSentenceBtn')?.addEventListener('click', saveCurrentSentence);
    bindListenButtons(box);
    bindIpaToggles(box);
    bindWordChips(box, data.target_lang);
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
      meaning_summary_tr: currentSentence.meaning_summary_tr,
      clause_breakdown: currentSentence.clause_breakdown,
      important_patterns: currentSentence.important_patterns,
      new_words: currentSentence.new_words,
      inferred_turkish_tr: currentSentence.inferred_turkish_tr,
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
    const reqId = ++wordRequestSeq;
    currentWordLesson = null;
    busy = true;
    showLoading('AI ders hazırlıyor…');
    try {
      const { ok, data } = await ApiClient.fetchWordLesson('/api/builder/word', {
        word,
        lang: LS.getLang(),
      }, {
        onWake: (sec) => showLoading(`Sunucu uyanıyor… (${sec} sn)`),
        onProgress: (sec) => showLoading(`AI ders hazırlıyor… (${sec} sn)`),
      });
      if (reqId !== wordRequestSeq) return;
      if (!ok || !data.ok) {
        const retry = data.ai_retry
          ? `<button type="button" class="mod-retry-btn" id="retryWordBtn">🔄 Tekrar dene</button>`
          : '';
        $('wordResult').innerHTML = `<div class="mod-error-card"><p>${esc(data.error_tr || 'Bir hata oluştu')}</p>${retry}</div>`;
        $('retryWordBtn')?.addEventListener('click', buildWord);
        setUi(data.error_tr || 'Bir hata oluştu', false);
        return;
      }
      setUi('Hazır — dinle ve kaydet', false);
      if ($('wordInput')) $('wordInput').value = '';
      renderWordLesson(data, word);
    } catch (err) {
      $('wordResult').innerHTML = `<div class="mod-error-card"><p>${esc(ApiClient.connectionErrorMessage(err))}</p><button type="button" class="mod-retry-btn" id="retryWordBtn">🔄 Tekrar dene</button></div>`;
      $('retryWordBtn')?.addEventListener('click', buildWord);
      setUi(ApiClient.connectionErrorMessage(err), false);
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
    const reqId = ++sentenceRequestSeq;
    currentSentence = null;
    busy = true;
    showLoading('Cümle analiz ediliyor…');
    try {
      const { ok, data } = await ApiClient.fetchJson('/api/builder/sentence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sentence, lang: LS.getLang() }),
      }, {
        timeoutMs: 60000,
        retries: 2,
        onRetry: (n, max) => showLoading(`Tekrar deneniyor (${n}/${max})…`),
      });
      if (reqId !== sentenceRequestSeq) return;
      if (!ok || !data.ok) {
        $('sentenceResult').innerHTML = '';
        setUi(data.error_tr || 'Bir hata oluştu', false);
        return;
      }
      setUi('Hazır — dinle ve kaydet', false);
      if ($('sentenceInput')) $('sentenceInput').value = '';
      renderSentenceResult(data);
    } catch (err) {
      $('sentenceResult').innerHTML = '';
      setUi(ApiClient.connectionErrorMessage(err), false);
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
          <div class="mod-saved-row">
            <button type="button" class="mod-saved-item" data-word-id="${w.id}">
              <span class="mod-saved-icon">${resolveWordIcon(w, w.word_icon)}</span>
              <span class="mod-saved-text">${esc(w.word_tr)}<small>${LS.learningLevel(w.stats)}</small></span>
            </button>
            <button type="button" class="mod-saved-delete" data-delete-word="${w.id}" title="Sil" aria-label="Sil">🗑️</button>
          </div>`).join('')
        : '<p class="mod-empty">Henüz kelime yok</p>';
      wBox.querySelectorAll('[data-delete-word]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const id = btn.dataset.deleteWord;
          const item = LS.getWordById(id);
          const label = item?.word_tr || 'bu kelime';
          if (window.confirm(`"${label}" kaydını silmek istiyor musun?`)) {
            LS.deleteWord(id);
            if (currentWordLesson?.word_tr === item?.word_tr) {
              currentWordLesson = null;
              const wr = $('wordResult');
              if (wr) wr.innerHTML = '';
            }
            renderSavedLists();
            setUi('Kayıt silindi', false);
          }
        });
      });
      wBox.querySelectorAll('[data-word-id]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const w = LS.getWordById(btn.dataset.wordId);
          if (w) {
            switchTab('word');
            $('wordInput').value = w.word_tr;
            refreshLessonPronunciation({ ok: true, ...w }).then((lesson) => {
              currentWordLesson = lesson;
              renderWordLesson(lesson, w.word_tr);
            });
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

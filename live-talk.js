/**
 * Eşzamanlı Konuşma — bağımsız iki yönlü canlı çeviri modülü.
 * Yeniden kullanır: MicHold + /api/process?source= + /api/tts
 * Eğitim / klasik çeviri / cümle kur koduna dokunmaz.
 */
(function () {
  'use strict';

  const LANGS = [
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

  const TAIL_MS = 180;
  const MIN_HOLD_MS = 180;
  const MIC_OPTS = {
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  };

  const audioEl = document.createElement('audio');
  audioEl.setAttribute('playsinline', 'true');
  audioEl.setAttribute('webkit-playsinline', 'true');
  document.body.appendChild(audioEl);

  const S = {
    my: 'tr',
    other: 'en',
    msgs: [],
    holdActive: false,
    holdGen: 0,
    lastFrom: null,
    forcedSource: null,
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
    pendingEndHold: false,
    micOpening: false,
    micOpenGen: 0,
    busyCount: 0,
    transGen: 0,
    transAbort: null,
    autoSpeak: true,
  };

  const $ = (id) => document.getElementById(id);
  const langOf = (c) => LANGS.find((l) => l.code === c) || LANGS[0];

  function speakLabel(code) {
    return code === 'en' ? 'PRESS TO SPEAK' : 'BAS VE KONUŞ';
  }

  function setStatus(text, live) {
    $('ltStatusText').textContent = text;
    $('ltStatusDot').classList.toggle('active', !!live);
  }

  function showError(msg) {
    const box = $('ltErrorBox');
    box.textContent = msg;
    box.className = 'error-box';
    box.classList.remove('hidden');
  }

  function showInfo(msg) {
    const box = $('ltErrorBox');
    box.textContent = msg;
    box.className = 'error-box info-box';
    box.classList.remove('hidden');
  }

  function hideError() {
    $('ltErrorBox').classList.add('hidden');
  }

  function clearInterim() {
    $('ltInterimBox').classList.add('hidden');
    $('ltInterimText').textContent = '';
  }

  function micButtons() {
    return [$('ltMicMe'), $('ltMicOther')].filter(Boolean);
  }

  function clearRecordingClass() {
    micButtons().forEach((b) => {
      b.classList.remove('recording');
      b.classList.remove('processing');
    });
  }

  function markRecording() {
    clearRecordingClass();
    const btn = S.forcedSource === S.other ? $('ltMicOther') : $('ltMicMe');
    if (btn) btn.classList.add('recording');
  }

  function showListening() {
    markRecording();
    const src = langOf(S.forcedSource || S.my);
    const label = src.flag + ' ' + src.name.toUpperCase() + ' DİNLENİYOR…';
    setStatus('🎙️ ' + label, true);
    $('ltInterimBox').classList.remove('hidden');
    $('ltInterimText').textContent = label;
  }

  function showTranslating() {
    clearRecordingClass();
    const src = langOf(S.forcedSource || S.my);
    const tgt = langOf(S.forcedSource === S.my ? S.other : S.my);
    const btn = src.code === S.other ? $('ltMicOther') : $('ltMicMe');
    if (btn) btn.classList.add('processing');
    setStatus('✍️ ' + src.flag + '→' + tgt.flag + ' çevriliyor…', true);
    $('ltInterimBox').classList.remove('hidden');
    $('ltInterimText').textContent = src.name + ' → ' + tgt.name;
  }

  function resetIdle() {
    clearTimeout(S.stopTimer);
    clearTimeout(S.safetyTimer);
    S.stopTimer = null;
    S.safetyTimer = null;
    S.holdActive = false;
    if (S.busyCount === 0) S.forcedSource = null;
    clearRecordingClass();
    syncUi();
    clearInterim();
    if (S.busyCount === 0) {
      setStatus('Hangi taraf konuşacaksa o butona bas', false);
    }
  }

  function unlockAudio() {
    if (S.audioReady) return;
    try {
      audioEl.volume = 1;
      audioEl.src = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAZGF0YQQAAAA=';
      const p = audioEl.play();
      if (p && p.then) {
        p.then(function () {
          audioEl.pause();
          audioEl.currentTime = 0;
          S.audioReady = true;
        }).catch(function () {});
      }
    } catch (e) { /* ignore */ }
  }

  function stopTts() {
    try {
      audioEl.pause();
      audioEl.currentTime = 0;
    } catch (e) { /* ignore */ }
  }

  async function playB64(b64) {
    if (!b64) return;
    stopTts();
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const blob = new Blob([bytes], { type: 'audio/mpeg' });
    const url = URL.createObjectURL(blob);
    audioEl.volume = 1;
    audioEl.src = url;
    const done = function () { URL.revokeObjectURL(url); };
    audioEl.onended = done;
    audioEl.onerror = done;
    try {
      await audioEl.play();
    } catch (e) {
      showInfo('🔊 Sesi dinlemek için “Tekrar dinle”ye bas');
    }
  }

  function nextGen() {
    S.transGen += 1;
    if (S.transAbort) {
      try { S.transAbort.abort(); } catch (e) { /* ignore */ }
    }
    S.transAbort = new AbortController();
    return { gen: S.transGen, signal: S.transAbort.signal };
  }

  function isAbort(e) {
    return e && (e.name === 'AbortError' || e.message === 'The user aborted a request.');
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function fetchProcess(blob, my, other, source, signal) {
    const ctrl = new AbortController();
    const timer = setTimeout(function () { ctrl.abort(); }, 45000);
    const onAbort = function () { try { ctrl.abort(); } catch (e) { /* ignore */ } };
    if (signal) {
      if (signal.aborted) ctrl.abort();
      else signal.addEventListener('abort', onAbort, { once: true });
    }
    try {
      const params = { my: my, other: other, last: '', source: source || '' };
      if (typeof console !== 'undefined' && console.debug) {
        console.debug('LIVE_TALK_REQUEST', {
          BUTTON_LANGUAGE: source,
          SOURCE_LANGUAGE: source,
          TARGET_LANGUAGE: source === my ? other : my,
          AUTO_DETECT: false,
          MODULE: 'live-talk',
        });
      }
      const r = await fetch('/api/process?' + new URLSearchParams(params), {
        method: 'POST',
        body: blob,
        headers: { 'Content-Type': blob.type || 'audio/mp4' },
        signal: ctrl.signal,
      });
      const raw = await r.text();
      let d = {};
      try { d = raw ? JSON.parse(raw) : {}; } catch (e) {
        throw new Error(r.ok ? 'Sunucu yanıtı okunamadı' : 'Sunucu hatası (' + r.status + ')');
      }
      if (!r.ok) {
        throw new Error(d.error || 'Konuşma anlaşılamadı. Lütfen tekrar konuşun.');
      }
      return d;
    } finally {
      clearTimeout(timer);
      if (signal) signal.removeEventListener('abort', onAbort);
    }
  }

  async function fetchTts(text, lang, gen) {
    const phrase = (text || '').trim().slice(0, 2500);
    if (!phrase) return;
    try {
      const r = await fetch('/api/tts?' + new URLSearchParams({ q: phrase, tl: lang }));
      if (!r.ok) return;
      if (gen != null && gen !== S.transGen) return;
      const blob = await r.blob();
      if (gen != null && gen !== S.transGen) return;
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let bin = '';
      const chunk = 8192;
      for (let i = 0; i < bytes.length; i += chunk) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
      }
      const b64 = btoa(bin);
      const m = (gen != null) ? S.msgs.find(function (x) { return x.gen === gen; }) : S.msgs[0];
      if (m) {
        m.audio = b64;
        render();
      }
      if (!S.autoSpeak) return;
      if (gen != null && gen !== S.transGen) return;
      await playB64(b64);
    } catch (e) { /* ignore */ }
  }

  function render() {
    const el = $('ltMessages');
    if (!S.msgs.length) {
      el.innerHTML = '<div class="empty-state">' +
        '<div class="empty-icon">🗣️</div>' +
        '<h2>Eşzamanlı konuşmaya başla</h2>' +
        '<p>Üst buton: sen · Alt buton: karşı taraf. Basılı tut, cümleyi bitir, bırak.</p>' +
        '</div>';
      $('ltClearBtn').classList.add('hidden');
      return;
    }
    $('ltClearBtn').classList.remove('hidden');
    el.innerHTML = S.msgs.map(function (m, i) {
      const from = langOf(m.from);
      const to = langOf(m.to);
      const side = m.from === S.my ? 'me' : 'other';
      const who = side === 'me' ? 'BEN' : 'KARŞI TARAF';
      return '<article class="live-talk-bubble ' + side + '">' +
        '<div class="live-talk-bubble-meta">' + from.flag + ' ' + who + ' · ' + from.name + '</div>' +
        '<div class="live-talk-bubble-orig">' + escapeHtml(m.orig) + '</div>' +
        '<div class="live-talk-bubble-divider"></div>' +
        '<div class="live-talk-bubble-meta">' + to.flag + ' ÇEVİRİ · ' + to.name + '</div>' +
        '<div class="live-talk-bubble-trans">' + escapeHtml(m.trans) + '</div>' +
        '<div class="live-talk-bubble-actions">' +
        (m.audio ? '<button type="button" class="live-talk-replay" data-idx="' + i + '">🔊 Tekrar dinle</button>' : '') +
        '</div></article>';
    }).join('');
    el.querySelectorAll('.live-talk-replay').forEach(function (btn) {
      btn.onclick = function (e) {
        e.preventDefault();
        unlockAudio();
        const m = S.msgs[parseInt(btn.dataset.idx, 10)];
        if (m && m.audio) playB64(m.audio);
      };
    });
    el.scrollTop = 0;
  }

  async function processAudio(blob) {
    const g = nextGen();
    const gen = g.gen;
    const signal = g.signal;
    const source = S.forcedSource;
    if (!source || (source !== S.my && source !== S.other)) {
      throw new Error('Konuşma dili seçilmedi — dil butonuna basılı tutun');
    }
    const data = await fetchProcess(blob, S.my, S.other, source, signal);
    if (gen !== S.transGen) return;
    const original = (data.original || '').trim();
    const translated = (data.translated || '').trim();
    if (!original) {
      throw new Error('Konuşma anlaşılamadı. Lütfen tekrar konuşun.');
    }
    S.lastFrom = data.from || source;
    const toLang = data.to || (source === S.my ? S.other : S.my);
    S.msgs.unshift({
      orig: original,
      trans: translated,
      from: data.from || source,
      to: toLang,
      audio: null,
      gen: gen,
      speaker: source === S.my ? 'me' : 'other',
    });
    render();
    clearInterim();
    S.forcedSource = null;
    setStatus('Çeviri hazır', false);
    void fetchTts(translated, toLang, gen);
  }

  function syncUi() {
    const my = langOf(S.my);
    const other = langOf(S.other);
    $('ltMyLang').value = S.my;
    $('ltOtherLang').value = S.other;
    $('ltMeBadge').textContent = my.flag + ' BEN';
    $('ltOtherBadge').textContent = other.flag + ' KARŞI TARAF';
    $('ltMeLangName').textContent = my.name;
    $('ltOtherLangName').textContent = other.name;
    $('ltMicTitleMe').textContent = speakLabel(S.my);
    $('ltMicTitleOther').textContent = speakLabel(S.other);
    $('ltMicHintMe').textContent = my.name;
    $('ltMicHintOther').textContent = other.name;
  }

  if (typeof MicHold === 'undefined' || typeof MicHold.create !== 'function') {
    showError('Mikrofon modülü yüklenemedi — sayfayı yenileyin');
    return;
  }

  const mic = MicHold.create({
    state: S,
    tailMs: TAIL_MS,
    minHoldMs: MIN_HOLD_MS,
    minBlobBytes: 200,
    micOpts: MIC_OPTS,
    onHideError: hideError,
    onSpeaking: function () {
      hideError();
      showListening();
      unlockAudio();
      stopTts();
    },
    onProcessing: showTranslating,
    onIdle: function () {
      if (S.busyCount === 0) resetIdle();
    },
    onError: showError,
    isBusy: function () { return S.busyCount > 0; },
    onBlob: function (blob) {
      S.busyCount += 1;
      showTranslating();
      processAudio(blob)
        .catch(function (e) {
          if (isAbort(e)) return;
          showError(e.message || 'Konuşma anlaşılamadı. Lütfen tekrar konuşun.');
        })
        .finally(function () {
          S.busyCount -= 1;
          if (!S.holdActive && !mic.isRecording() && S.busyCount === 0) resetIdle();
        });
    },
  });

  LANGS.forEach(function (l) {
    [$('ltMyLang'), $('ltOtherLang')].forEach(function (sel) {
      const o = document.createElement('option');
      o.value = l.code;
      o.textContent = l.flag + ' ' + l.name;
      sel.appendChild(o);
    });
  });

  function bindMic(btn, getCode) {
    if (!btn) return;
    const arm = function () { S.forcedSource = getCode(); };
    btn.addEventListener('touchstart', arm, { passive: true, capture: true });
    btn.addEventListener('mousedown', arm, { capture: true });
    btn.addEventListener('pointerdown', arm, { capture: true });
    mic.bindHold(btn);
  }

  bindMic($('ltMicMe'), function () { return S.my; });
  bindMic($('ltMicOther'), function () { return S.other; });

  $('ltMyLang').onchange = function () {
    const v = $('ltMyLang').value;
    if (v === S.other) S.other = S.my;
    S.my = v;
    S.lastFrom = null;
    S.forcedSource = null;
    syncUi();
  };

  $('ltOtherLang').onchange = function () {
    const v = $('ltOtherLang').value;
    if (v === S.my) S.my = S.other;
    S.other = v;
    S.lastFrom = null;
    S.forcedSource = null;
    syncUi();
  };

  $('ltSwapBtn').onclick = function () {
    const tmp = S.my;
    S.my = S.other;
    S.other = tmp;
    S.lastFrom = null;
    S.forcedSource = null;
    syncUi();
  };

  $('ltClearBtn').onclick = function () {
    S.msgs = [];
    S.lastFrom = null;
    render();
    hideError();
    setStatus('Hangi taraf konuşacaksa o butona bas', false);
  };

  $('ltAutoSpeak').onchange = function () {
    S.autoSpeak = !!$('ltAutoSpeak').checked;
  };

  syncUi();
  render();
  setStatus('Hangi taraf konuşacaksa o butona bas', false);
})();

/**
 * Eşzamanlı Konuşma — konuşurken canlı STT + artımlı çeviri.
 * Klasik çeviri (translate.html / mic-hold.js / /api/process) dokunulmaz.
 *
 * hold → MediaRecorder timeslice (webm) veya ~2sn rolling segment (mp4/iOS)
 *      → /api/stt?lang=SOURCE (+ Web Speech interim)
 *      → anlamlı bölümde /api/translate → canlı UI
 * release → son STT + nihai çeviri (+ isteğe bağlı TTS)
 */
(function () {
  'use strict';

  var LANGS = [
    { code: 'tr', speech: 'tr-TR', name: 'Türkçe', flag: '🇹🇷' },
    { code: 'en', speech: 'en-US', name: 'English', flag: '🇬🇧' },
    { code: 'ka', speech: 'ka-GE', name: 'ქართული', flag: '🇬🇪' },
    { code: 'de', speech: 'de-DE', name: 'Deutsch', flag: '🇩🇪' },
    { code: 'fr', speech: 'fr-FR', name: 'Français', flag: '🇫🇷' },
    { code: 'es', speech: 'es-ES', name: 'Español', flag: '🇪🇸' },
    { code: 'ar', speech: 'ar-SA', name: 'العربية', flag: '🇸🇦' },
    { code: 'ru', speech: 'ru-RU', name: 'Русский', flag: '🇷🇺' },
    { code: 'it', speech: 'it-IT', name: 'Italiano', flag: '🇮🇹' },
    { code: 'zh', speech: 'zh-CN', name: '中文', flag: '🇨🇳' }
  ];

  var SLICE_MS = 1100;
  var ROLL_MS = 2000;
  var STT_GAP_MS = 900;
  var TR_DEBOUNCE_MS = 280;
  var TR_MAX_WAIT_MS = 900;
  var RELEASE_TAIL_MS = 220;
  var MIN_HOLD_MS = 220;
  var MIN_BLOB_BYTES = 900;

  var MIC_OPTS = {
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
  };

  var audioEl = document.createElement('audio');
  audioEl.setAttribute('playsinline', 'true');
  audioEl.setAttribute('webkit-playsinline', 'true');
  document.body.appendChild(audioEl);

  var S = {
    my: 'tr',
    other: 'en',
    msgs: [],
    autoSpeak: true,
    audioReady: false,
    usedTouch: false,
    session: null
  };

  function $(id) { return document.getElementById(id); }

  function langOf(code) {
    for (var i = 0; i < LANGS.length; i++) if (LANGS[i].code === code) return LANGS[i];
    return LANGS[0];
  }

  function speakLabel(code) {
    return code === 'en' ? 'HOLD TO SPEAK' : 'BASILI TUT';
  }

  function setStatus(text, live) {
    $('ltStatusText').textContent = text;
    $('ltStatusDot').classList.toggle('active', !!live);
  }

  function showError(msg) {
    var box = $('ltErrorBox');
    box.textContent = msg;
    box.className = 'error-box';
    box.classList.remove('hidden');
  }

  function hideError() {
    $('ltErrorBox').classList.add('hidden');
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function pickMime() {
    if (typeof MediaRecorder === 'undefined') return '';
    var cands = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/aac'];
    for (var i = 0; i < cands.length; i++) {
      if (MediaRecorder.isTypeSupported(cands[i])) return cands[i];
    }
    return '';
  }

  function needsRolling(mime) {
    var m = String(mime || '').toLowerCase();
    return !m || m.indexOf('webm') === -1;
  }

  function isMeaningfulPhrase(text) {
    var t = String(text || '').trim();
    if (!t) return false;
    var words = t.split(/\s+/).filter(Boolean);
    // Canlı çeviri için daha erken başla (kelime kelime değil, kısa ifade yeter)
    if (words.length >= 3) return true;
    if (words.length >= 2 && t.length >= 10) return true;
    if (words.length >= 2 && /[.!?…,;:؟。！？]$/.test(t)) return true;
    return t.length >= 14;
  }

  function shouldRetranslate(prev, next) {
    var a = String(prev || '').trim();
    var b = String(next || '').trim();
    if (!b || b === a) return false;
    if (!a) return isMeaningfulPhrase(b);
    if (b.length - a.length >= 6) return true;
    var aw = a.split(/\s+/).filter(Boolean).length;
    var bw = b.split(/\s+/).filter(Boolean).length;
    if (bw - aw >= 1 && b.length - a.length >= 4) return true;
    if (bw - aw >= 2) return true;
    return /[.!?…]$/.test(b) && b !== a;
  }

  window.LiveTalkHeuristics = {
    isMeaningfulPhrase: isMeaningfulPhrase,
    shouldRetranslate: shouldRetranslate
  };

  function mergeTranscript(prev, next) {
    var a = String(prev || '').trim();
    var b = String(next || '').trim();
    if (!b) return a;
    if (!a) return b;
    if (b.indexOf(a) === 0) return b;
    if (a.indexOf(b) === 0) return a;
    var aWords = a.split(/\s+/);
    var bWords = b.split(/\s+/);
    var max = Math.min(aWords.length, bWords.length);
    var overlap = 0;
    for (var k = max; k >= 1; k--) {
      if (aWords.slice(-k).join(' ').toLowerCase() === bWords.slice(0, k).join(' ').toLowerCase()) {
        overlap = k;
        break;
      }
    }
    return (a + ' ' + bWords.slice(overlap).join(' ')).replace(/\s+/g, ' ').trim();
  }

  function makeRecorder(stream, mime) {
    try {
      return mime
        ? new MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 128000 })
        : new MediaRecorder(stream);
    } catch (e) {
      return new MediaRecorder(stream);
    }
  }

  function stopRecorderBlob(recorder) {
    return new Promise(function (resolve) {
      if (!recorder || recorder.state === 'inactive') {
        resolve(null);
        return;
      }
      var chunks = [];
      var finished = false;
      function done() {
        if (finished) return;
        finished = true;
        resolve(chunks.length ? new Blob(chunks, { type: recorder.mimeType || 'audio/mp4' }) : null);
      }
      recorder.ondataavailable = function (e) {
        if (e.data && e.data.size) chunks.push(e.data);
      };
      recorder.onstop = done;
      try { recorder.requestData(); } catch (e) {}
      try { recorder.stop(); } catch (e) { done(); }
      setTimeout(done, 1200);
    });
  }

  function unlockAudio() {
    if (S.audioReady) return;
    try {
      audioEl.volume = 1;
      audioEl.src = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAZGF0YQQAAAA=';
      var p = audioEl.play();
      if (p && p.then) {
        p.then(function () {
          audioEl.pause();
          audioEl.currentTime = 0;
          S.audioReady = true;
        }).catch(function () {});
      }
    } catch (e) {}
  }

  function stopTts() {
    try { audioEl.pause(); audioEl.currentTime = 0; } catch (e) {}
  }

  async function playB64(b64) {
    if (!b64) return;
    stopTts();
    var bin = atob(b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    var url = URL.createObjectURL(new Blob([bytes], { type: 'audio/mpeg' }));
    audioEl.volume = 1;
    audioEl.src = url;
    var done = function () { URL.revokeObjectURL(url); };
    audioEl.onended = done;
    audioEl.onerror = done;
    try { await audioEl.play(); } catch (e) {}
  }

  function showLivePanel(fromCode, toCode) {
    $('ltLiveFromFlag').textContent = langOf(fromCode).flag;
    $('ltLiveToFlag').textContent = langOf(toCode).flag;
    $('ltLiveOrig').textContent = 'Dinleniyor…';
    $('ltLiveTrans').textContent = 'Çeviri konuşurken oluşacak…';
    $('ltLiveBox').classList.remove('hidden');
  }

  function updateLivePanel(orig, trans) {
    if (orig) $('ltLiveOrig').textContent = orig;
    if (trans) $('ltLiveTrans').textContent = trans;
    $('ltLiveBox').classList.remove('hidden');
  }

  function hideLivePanel() {
    $('ltLiveBox').classList.add('hidden');
  }

  function clearMicUi() {
    ['ltMicMe', 'ltMicOther'].forEach(function (id) {
      var b = $(id);
      if (!b) return;
      b.classList.remove('recording');
      b.classList.remove('processing');
    });
  }

  function markMic(side, mode) {
    clearMicUi();
    var btn = side === 'other' ? $('ltMicOther') : $('ltMicMe');
    if (btn && mode) btn.classList.add(mode);
  }

  async function fetchStt(blob, lang, signal) {
    var r = await fetch('/api/stt?' + new URLSearchParams({ lang: lang }), {
      method: 'POST',
      body: blob,
      headers: { 'Content-Type': blob.type || 'audio/mp4' },
      signal: signal
    });
    var raw = await r.text();
    var d = {};
    try { d = raw ? JSON.parse(raw) : {}; } catch (e) {
      throw new Error(r.ok ? 'STT yanıtı okunamadı' : 'STT hatası (' + r.status + ')');
    }
    if (!r.ok) throw new Error(d.error || 'Konuşma anlaşılamadı');
    return String(d.text || '').trim();
  }

  async function fetchTranslate(text, from, to, signal) {
    var r = await fetch('/api/translate?' + new URLSearchParams({
      q: text, from: from, to: to, my: S.my, other: S.other
    }), { signal: signal });
    var d = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(d.error || 'Çeviri başarısız');
    return String(d.text || '').trim();
  }

  async function fetchTts(text, lang) {
    var phrase = String(text || '').trim().slice(0, 2500);
    if (!phrase) return null;
    var r = await fetch('/api/tts?' + new URLSearchParams({ q: phrase, tl: lang }));
    if (!r.ok) return null;
    var bytes = new Uint8Array(await (await r.blob()).arrayBuffer());
    var bin = '';
    for (var i = 0; i < bytes.length; i += 8192) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
    }
    return btoa(bin);
  }

  function render() {
    var el = $('ltMessages');
    if (!S.msgs.length) {
      el.innerHTML = '<div class="empty-state">' +
        '<div class="empty-icon">🗣️</div>' +
        '<h2>Konuşurken çeviri başlar</h2>' +
        '<p>Butona basılı tutup konuş. Anlamlı bölüm oluşunca hedef dilde çeviri canlı güncellenir.</p>' +
        '</div>';
      $('ltClearBtn').classList.add('hidden');
      return;
    }
    $('ltClearBtn').classList.remove('hidden');
    el.innerHTML = S.msgs.map(function (m, i) {
      var from = langOf(m.from);
      var to = langOf(m.to);
      var side = m.from === S.my ? 'me' : 'other';
      var who = side === 'me' ? 'BEN' : 'KARŞI TARAF';
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
        var m = S.msgs[parseInt(btn.dataset.idx, 10)];
        if (m && m.audio) playB64(m.audio);
      };
    });
    el.scrollTop = 0;
  }

  function syncUi() {
    var my = langOf(S.my);
    var other = langOf(S.other);
    $('ltMyLang').value = S.my;
    $('ltOtherLang').value = S.other;
    $('ltMeBadge').textContent = my.flag + ' BEN';
    $('ltOtherBadge').textContent = other.flag + ' KARŞI TARAF';
    $('ltMeLangName').textContent = my.name;
    $('ltOtherLangName').textContent = other.name;
    $('ltMicTitleMe').textContent = speakLabel(S.my);
    $('ltMicTitleOther').textContent = speakLabel(S.other);
    $('ltMicHintMe').textContent = my.name + ' → canlı çeviri';
    $('ltMicHintOther').textContent = other.name + ' → canlı çeviri';
  }

  function abortFetches(sess) {
    if (!sess) return;
    if (sess.sttAbort) { try { sess.sttAbort.abort(); } catch (e) {} sess.sttAbort = null; }
    if (sess.trAbort) { try { sess.trAbort.abort(); } catch (e) {} sess.trAbort = null; }
    if (sess.translateTimer) { clearTimeout(sess.translateTimer); sess.translateTimer = null; }
    sess.translateInflight = false;
    sess.translatePending = false;
  }

  function applyLiveOrig(sess, text) {
    if (!sess || !text) return false;
    var next = String(text).trim();
    if (!next || next === sess.liveOrig) return false;
    if (sess.liveOrig && next.length < sess.liveOrig.length && sess.liveOrig.indexOf(next) === 0) {
      return false;
    }
    sess.liveOrig = next;
    updateLivePanel(sess.liveOrig, sess.liveTrans || '');
    setStatus('🎙️ Algılanıyor… çeviri canlı', true);
    if (isMeaningfulPhrase(sess.liveOrig) || shouldRetranslate(sess.lastTranslatedOrig, sess.liveOrig)) {
      scheduleTranslate(sess);
    }
    return true;
  }

  function scheduleTranslate(sess) {
    if (!sess || sess.finalizing) return;
    var text = String(sess.liveOrig || '').trim();
    if (!text) return;

    // İlk anlamlı metinde çeviriyi hemen başlat (debounce yüzünden hiç çalışmasın)
    if (!sess.liveTrans && isMeaningfulPhrase(text) && !sess.translateInflight) {
      if (sess.translateTimer) { clearTimeout(sess.translateTimer); sess.translateTimer = null; }
      runTranslate(sess, true);
      return;
    }

    // Uçuştayken iptal etme — bitince güncel metni çevir
    if (sess.translateInflight) {
      sess.translatePending = true;
      return;
    }

    var now = Date.now();
    if (!sess.translateFirstAt) sess.translateFirstAt = now;
    if (sess.translateTimer) clearTimeout(sess.translateTimer);

    // Sürekli interim güncellemesi debounce'u sonsuza ertelemesin
    var waited = now - (sess.translateFirstAt || now);
    var delay = waited >= TR_MAX_WAIT_MS ? 0 : TR_DEBOUNCE_MS;
    sess.translateTimer = setTimeout(function () {
      sess.translateTimer = null;
      sess.translateFirstAt = 0;
      runTranslate(sess, false);
    }, delay);
  }

  async function runTranslate(sess, force) {
    if (!sess || sess.finalizing) return;
    var text = String(sess.liveOrig || '').trim();
    if (!text) return;
    if (!force) {
      if (!isMeaningfulPhrase(text) && !shouldRetranslate(sess.lastTranslatedOrig, text)) return;
      if (!shouldRetranslate(sess.lastTranslatedOrig, text) && sess.liveTrans) return;
    } else if (sess.liveTrans && text === sess.lastTranslatedOrig) {
      return;
    }

    // Öncekini iptal etme — paralel çakışmayı reqId ile çöz
    var ctrl = new AbortController();
    sess.trAbort = ctrl;
    var reqId = ++sess.trReqId;
    sess.translateInflight = true;
    sess.translatePending = false;
    try {
      if (!sess.liveTrans) {
        updateLivePanel(sess.liveOrig, 'Çevriliyor…');
      }
      setStatus('✍️ Canlı çevriliyor…', true);
      var translated = await fetchTranslate(text, sess.from, sess.to, ctrl.signal);
      if (!S.session || S.session.id !== sess.id || reqId !== sess.trReqId) return;
      if (!translated) return;
      sess.liveTrans = translated;
      sess.lastTranslatedOrig = text;
      updateLivePanel(sess.liveOrig, sess.liveTrans);
      setStatus('🔴 Canlı çeviri — konuşmaya devam', true);
    } catch (e) {
      if (e && e.name === 'AbortError') return;
    } finally {
      if (S.session && S.session.id === sess.id && reqId === sess.trReqId) {
        sess.translateInflight = false;
        // Konuşma sürerken metin değiştiyse hemen yeniden çevir
        if (sess.translatePending && sess.active && !sess.finalizing) {
          sess.translatePending = false;
          scheduleTranslate(sess);
        }
      }
    }
  }

  async function runLiveStt(sess) {
    if (!sess || !sess.active || sess.finalizing) return;
    if (sess.sttInflight) { sess.sttQueued = true; return; }
    var now = Date.now();
    if (now - sess.lastSttAt < STT_GAP_MS && sess.liveOrig) {
      sess.sttQueued = true;
      return;
    }
    if (!sess.chunks.length) return;
    var blob = new Blob(sess.chunks, { type: sess.mime || 'audio/webm' });
    if (blob.size < MIN_BLOB_BYTES) return;

    sess.sttInflight = true;
    sess.lastSttAt = now;
    if (sess.sttAbort) { try { sess.sttAbort.abort(); } catch (e) {} }
    var ctrl = new AbortController();
    sess.sttAbort = ctrl;
    var reqId = ++sess.sttReqId;
    try {
      var text = await fetchStt(blob, sess.from, ctrl.signal);
      if (!S.session || S.session.id !== sess.id || reqId !== sess.sttReqId) return;
      applyLiveOrig(sess, text);
    } catch (e) {
      if (e && e.name === 'AbortError') return;
    } finally {
      sess.sttInflight = false;
      if (sess.sttQueued && sess.active && !sess.finalizing) {
        sess.sttQueued = false;
        runLiveStt(sess);
      }
    }
  }

  async function sttCompletePart(sess, blob) {
    if (!sess || !blob || blob.size < MIN_BLOB_BYTES) return;
    if (sess.sttAbort) { try { sess.sttAbort.abort(); } catch (e) {} }
    var ctrl = new AbortController();
    sess.sttAbort = ctrl;
    var reqId = ++sess.sttReqId;
    try {
      var text = await fetchStt(blob, sess.from, ctrl.signal);
      if (!S.session || S.session.id !== sess.id || reqId !== sess.sttReqId) return;
      if (!text) return;
      var cur = String(sess.liveOrig || '');
      if (cur && cur.toLowerCase().indexOf(text.toLowerCase()) !== -1) return;
      sess.liveOrig = mergeTranscript(cur, text);
      updateLivePanel(sess.liveOrig, sess.liveTrans || '');
      setStatus('🎙️ Algılanıyor… çeviri canlı', true);
      if (isMeaningfulPhrase(sess.liveOrig) || shouldRetranslate(sess.lastTranslatedOrig, sess.liveOrig)) {
        scheduleTranslate(sess);
      }
    } catch (e) {
      if (e && e.name === 'AbortError') return;
    }
  }

  function clearRollTimer(sess) {
    if (sess && sess.rollTimer) {
      clearTimeout(sess.rollTimer);
      sess.rollTimer = null;
    }
  }

  function scheduleRoll(sess) {
    clearRollTimer(sess);
    if (!sess || !sess.active || sess.finalizing || !sess.useRoll) return;
    sess.rollTimer = setTimeout(function () { rollSegment(sess); }, ROLL_MS);
  }

  async function rollSegment(sess) {
    if (!sess || !sess.active || sess.finalizing || !sess.useRoll || sess.rolling) {
      scheduleRoll(sess);
      return;
    }
    sess.rolling = true;
    clearRollTimer(sess);
    try {
      var blob = await stopRecorderBlob(sess.recorder);
      if (blob && blob.size) {
        sess.chunks.push(blob);
        sttCompletePart(sess, blob);
      }
      if (!sess.active || sess.finalizing) return;
      var recorder = makeRecorder(sess.stream, sess.mimePreferred);
      sess.recorder = recorder;
      sess.mime = recorder.mimeType || sess.mimePreferred || 'audio/mp4';
      recorder.onerror = function () {
        showError('Kayıt hatası — tekrar dene');
        endSession(true);
      };
      try { recorder.start(SLICE_MS); } catch (e) {
        try { recorder.start(); } catch (e2) {}
      }
    } catch (e) {
    } finally {
      sess.rolling = false;
      if (sess.active && !sess.finalizing) scheduleRoll(sess);
    }
  }

  function startWebSpeechAssist(sess) {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;
    try {
      var rec = new SR();
      rec.lang = langOf(sess.from).speech;
      rec.continuous = true;
      rec.interimResults = true;
      rec.maxAlternatives = 1;
      rec.onresult = function (ev) {
        if (!S.session || S.session.id !== sess.id || sess.finalizing) return;
        var interim = '';
        var finalText = '';
        for (var i = 0; i < ev.results.length; i++) {
          var r = ev.results[i];
          var t = (r[0] && r[0].transcript) || '';
          if (r.isFinal) finalText += t + ' ';
          else interim += t + ' ';
        }
        var combined = String(finalText + ' ' + interim).replace(/\s+/g, ' ').trim();
        if (combined) applyLiveOrig(sess, combined);
      };
      rec.onerror = function () {};
      rec.start();
      sess.webSpeech = rec;
    } catch (e) {}
  }

  function stopWebSpeech(sess) {
    if (!sess || !sess.webSpeech) return;
    try { sess.webSpeech.onresult = null; sess.webSpeech.stop(); } catch (e) {}
    sess.webSpeech = null;
  }

  async function startSession(side) {
    // Önceki oturum bitene kadar yeni konuşma başlatma (yarış / ikinci basış bug'ı)
    if (S.session && (S.session.active || S.session.finalizing)) return;
    hideError();
    unlockAudio();
    stopTts();

    var from = side === 'other' ? S.other : S.my;
    var to = side === 'other' ? S.my : S.other;

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showError('Mikrofon için Safari gerekli');
      return;
    }
    if (typeof MediaRecorder === 'undefined') {
      showError('Bu tarayıcıda canlı kayıt desteklenmiyor');
      return;
    }

    var stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia(MIC_OPTS);
    } catch (e) {
      showError('Mikrofon izni gerekli. Ayarlar → Safari → Mikrofon');
      return;
    }

    var mime = pickMime();
    var recorder;
    try {
      recorder = makeRecorder(stream, mime);
    } catch (e) {
      stream.getTracks().forEach(function (t) { t.stop(); });
      showError('Kayıt başlatılamadı — tekrar dene');
      return;
    }

    var actualMime = recorder.mimeType || mime || 'audio/webm';
    var useRoll = needsRolling(actualMime);

    var sess = {
      id: Date.now() + Math.random(),
      side: side,
      from: from,
      to: to,
      active: true,
      finalizing: false,
      startedAt: Date.now(),
      stream: stream,
      recorder: recorder,
      mimePreferred: mime,
      mime: actualMime,
      useRoll: useRoll,
      rolling: false,
      rollTimer: null,
      chunks: [],
      liveOrig: '',
      liveTrans: '',
      lastTranslatedOrig: '',
      lastSttAt: 0,
      sttInflight: false,
      sttQueued: false,
      sttAbort: null,
      trAbort: null,
      sttReqId: 0,
      trReqId: 0,
      translateTimer: null,
      translateInflight: false,
      translatePending: false,
      translateFirstAt: 0,
      webSpeech: null
    };
    S.session = sess;

    markMic(side, 'recording');
    showLivePanel(from, to);
    setStatus('🎙️ ' + langOf(from).flag + ' dinleniyor → ' + langOf(to).flag + ' canlı çeviri', true);

    if (!useRoll) {
      recorder.ondataavailable = function (e) {
        if (!e.data || !e.data.size) return;
        if (!S.session || S.session.id !== sess.id) return;
        sess.chunks.push(e.data);
        if (sess.active && !sess.finalizing) runLiveStt(sess);
      };
    }
    recorder.onerror = function () {
      showError('Kayıt hatası — tekrar dene');
      endSession(true);
    };

    try {
      recorder.start(SLICE_MS);
    } catch (e) {
      try { recorder.start(); } catch (e2) {
        showError('Kayıt başlatılamadı');
        endSession(true);
        return;
      }
    }

    if (useRoll) scheduleRoll(sess);
    startWebSpeechAssist(sess);
  }

  async function endSession(cancelled) {
    var sess = S.session;
    if (!sess || sess.finalizing) return;
    sess.finalizing = true;
    sess.active = false;
    clearRollTimer(sess);
    stopWebSpeech(sess);
    abortFetches(sess);
    markMic(sess.side, 'processing');
    setStatus('✍️ Son bölüm tamamlanıyor…', true);

    var holdMs = Date.now() - sess.startedAt;
    await new Promise(function (r) { setTimeout(r, RELEASE_TAIL_MS); });

    function clearThisSession() {
      if (S.session && S.session.id === sess.id) S.session = null;
    }

    try {
      if (sess.recorder && sess.recorder.state !== 'inactive') {
        var lastBlob = await stopRecorderBlob(sess.recorder);
        if (lastBlob && lastBlob.size) sess.chunks.push(lastBlob);
      }
    } catch (e) {}

    if (sess.stream) {
      try { sess.stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
      sess.stream = null;
    }

    if (cancelled) {
      clearThisSession();
      hideLivePanel();
      clearMicUi();
      setStatus('Hangi taraf konuşacaksa o butona basılı tut', false);
      return;
    }

    if (holdMs < MIN_HOLD_MS) {
      clearThisSession();
      hideLivePanel();
      clearMicUi();
      showError('Biraz daha uzun basılı tutun');
      setStatus('Hangi taraf konuşacaksa o butona basılı tut', false);
      return;
    }

    var blob = new Blob(sess.chunks, { type: sess.mime || 'audio/webm' });
    if ((!blob.size || blob.size < MIN_BLOB_BYTES) && !sess.liveOrig) {
      clearThisSession();
      hideLivePanel();
      clearMicUi();
      showError('Ses duyulamadı — tekrar dene');
      setStatus('Hangi taraf konuşacaksa o butona basılı tut', false);
      return;
    }

    try {
      var finalOrig = sess.liveOrig;
      if (!sess.useRoll && blob.size >= MIN_BLOB_BYTES) {
        try {
          var text = await fetchStt(blob, sess.from);
          if (text) finalOrig = text;
        } catch (e) {
          if (!finalOrig) throw e;
        }
      } else if (sess.useRoll && sess.chunks.length) {
        var last = sess.chunks[sess.chunks.length - 1];
        if (last && last.size >= MIN_BLOB_BYTES) {
          try {
            var lastText = await fetchStt(last, sess.from);
            if (lastText) finalOrig = mergeTranscript(finalOrig, lastText);
          } catch (e) {}
        }
      }
      finalOrig = String(finalOrig || '').trim();
      if (!finalOrig) throw new Error('Konuşma anlaşılamadı. Lütfen tekrar konuşun.');

      // Varsa canlı çeviriyi koru; yoksa / değiştiyse son çeviriyi yap
      var finalTrans = sess.liveTrans;
      if (!finalTrans || sess.lastTranslatedOrig !== finalOrig) {
        updateLivePanel(finalOrig, finalTrans || 'Son çeviri…');
        finalTrans = await fetchTranslate(finalOrig, sess.from, sess.to);
      }
      if (!finalTrans) throw new Error('Çeviri başarısız');

      var msg = {
        orig: finalOrig,
        trans: finalTrans,
        from: sess.from,
        to: sess.to,
        audio: null,
        speaker: sess.side
      };
      S.msgs.unshift(msg);
      render();
      hideLivePanel();
      clearMicUi();
      setStatus('Çeviri hazır', false);

      // TTS'ten önce oturumu kapat — ikinci basış çalışsın
      clearThisSession();

      if (S.autoSpeak) {
        try {
          var b64 = await fetchTts(finalTrans, sess.to);
          if (b64) {
            msg.audio = b64;
            render();
            playB64(b64);
          }
        } catch (e) {}
      }
    } catch (e) {
      showError((e && e.message) || 'Konuşma anlaşılamadı. Lütfen tekrar konuşun.');
      hideLivePanel();
      clearMicUi();
      setStatus('Hangi taraf konuşacaksa o butona basılı tut', false);
    } finally {
      clearThisSession();
    }
  }

  function bindHold(btn, side) {
    if (!btn) return;
    function down(e) {
      e.preventDefault();
      if (S.session && (S.session.active || S.session.finalizing)) return;
      startSession(side);
    }
    function up(e) {
      e.preventDefault();
      if (!S.session || S.session.finalizing) return;
      endSession(false);
    }
    btn.addEventListener('contextmenu', function (e) { e.preventDefault(); });
    btn.addEventListener('touchstart', function (e) { S.usedTouch = true; down(e); }, { passive: false });
    btn.addEventListener('touchend', up, { passive: false });
    btn.addEventListener('touchcancel', up, { passive: false });
    btn.addEventListener('mousedown', function (e) { if (!S.usedTouch) down(e); });
    btn.addEventListener('mouseup', function (e) { if (!S.usedTouch) up(e); });
    btn.addEventListener('mouseleave', function (e) {
      if (S.usedTouch) return;
      if (S.session && S.session.active) up(e);
    });
  }

  LANGS.forEach(function (l) {
    [$('ltMyLang'), $('ltOtherLang')].forEach(function (sel) {
      var o = document.createElement('option');
      o.value = l.code;
      o.textContent = l.flag + ' ' + l.name;
      sel.appendChild(o);
    });
  });

  bindHold($('ltMicMe'), 'me');
  bindHold($('ltMicOther'), 'other');

  $('ltMyLang').onchange = function () {
    var v = $('ltMyLang').value;
    if (v === S.other) S.other = S.my;
    S.my = v;
    syncUi();
  };
  $('ltOtherLang').onchange = function () {
    var v = $('ltOtherLang').value;
    if (v === S.my) S.my = S.other;
    S.other = v;
    syncUi();
  };
  $('ltSwapBtn').onclick = function () {
    var tmp = S.my; S.my = S.other; S.other = tmp; syncUi();
  };
  $('ltClearBtn').onclick = function () {
    S.msgs = [];
    render();
    hideError();
    setStatus('Hangi taraf konuşacaksa o butona basılı tut', false);
  };
  $('ltAutoSpeak').onchange = function () {
    S.autoSpeak = !!$('ltAutoSpeak').checked;
  };

  syncUi();
  render();
  setStatus('Hangi taraf konuşacaksa o butona basılı tut', false);
})();

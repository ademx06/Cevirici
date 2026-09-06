/**
 * Eşzamanlı Konuşma — konuşurken canlı STT + artımlı çeviri + hedef dil TTS.
 * Klasik çeviri (translate.html / mic-hold.js / /api/process) dokunulmaz.
 *
 * hold → MediaRecorder timeslice (webm) veya ~2sn rolling segment (mp4/iOS)
 *      → /api/stt?lang=SOURCE (+ Web Speech interim)
 *      → anlamlı bölümde /api/translate?force=1 → canlı UI
 *      → anlamlı/stabil hedef dil segmentleri → /api/tts?tl=TARGET (konuşurken)
 * release → recorder durur; mikrofon track STOP EDİLMEZ (izin tekrarlanmaz)
 *      → aynı kalıcı stream ile 2./3. konuşma hemen başlar + konuşurken TTS
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
  var RELEASE_TAIL_MS = 180;
  var MIN_HOLD_MS = 220;
  var MIN_BLOB_BYTES = 900;
  var TTS_STABLE_MS = 380;
  var TTS_MIN_WORDS = 3;

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
    session: null,
    pendingSide: null,
    micStream: null,
    ttsQueue: [],
    ttsPlaying: false,
    ttsPausedMic: false
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

  function wordCount(text) {
    return String(text || '').trim().split(/\s+/).filter(Boolean).length;
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

  function commonPrefixLen(a, b) {
    var aa = String(a || '');
    var bb = String(b || '');
    var n = Math.min(aa.length, bb.length);
    var i = 0;
    while (i < n && aa.charAt(i).toLowerCase() === bb.charAt(i).toLowerCase()) i++;
    // kelime ortasında kesme
    while (i > 0 && /[^\s]/.test(aa.charAt(i - 1)) && i < aa.length && /[^\s]/.test(aa.charAt(i))) i--;
    return i;
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

  function stopTtsPlayback() {
    try { audioEl.pause(); audioEl.currentTime = 0; } catch (e) {}
    S.ttsQueue = [];
    S.ttsPlaying = false;
    resumeMicAfterTts();
  }

  function micTracksLive(stream) {
    if (!stream) return false;
    try {
      return stream.getAudioTracks().some(function (t) { return t.readyState === 'live'; });
    } catch (e) {
      return false;
    }
  }

  function setSharedMicEnabled(enabled) {
    if (!S.micStream) return;
    try {
      S.micStream.getAudioTracks().forEach(function (t) { t.enabled = !!enabled; });
    } catch (e) {}
  }

  function setMicCaptureEnabled(sess, enabled) {
    setSharedMicEnabled(enabled);
  }

  async function ensureMicStream() {
    if (micTracksLive(S.micStream)) {
      setSharedMicEnabled(true);
      return S.micStream;
    }
    if (S.micStream) {
      try { S.micStream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
      S.micStream = null;
    }
    var stream = await navigator.mediaDevices.getUserMedia(MIC_OPTS);
    S.micStream = stream;
    setSharedMicEnabled(true);
    return stream;
  }

  function pauseMicForTts(sess) {
    if (!sess || !sess.active) return;
    if (S.ttsPausedMic) return;
    S.ttsPausedMic = true;
    setSharedMicEnabled(false);
    if (sess.webSpeech) {
      try {
        sess.webSpeechPaused = true;
        if (sess.webSpeech.abort) sess.webSpeech.abort();
        else sess.webSpeech.stop();
      } catch (e) {}
    }
  }

  function resumeMicAfterTts() {
    if (!S.ttsPausedMic) return;
    S.ttsPausedMic = false;
    var sess = S.session;
    if (!sess || !sess.active || sess.finalizing) return;
    setSharedMicEnabled(true);
    if (sess.webSpeechPaused) {
      sess.webSpeechPaused = false;
      sess.webSpeech = null;
      startWebSpeechAssist(sess);
    }
  }

  async function playB64(b64) {
    if (!b64) return;
    try { audioEl.pause(); audioEl.currentTime = 0; } catch (e) {}
    var bin = atob(b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    var url = URL.createObjectURL(new Blob([bytes], { type: 'audio/mpeg' }));
    audioEl.volume = 1;
    audioEl.src = url;
    return new Promise(function (resolve) {
      var done = function () {
        URL.revokeObjectURL(url);
        resolve();
      };
      audioEl.onended = done;
      audioEl.onerror = done;
      try {
        var p = audioEl.play();
        if (p && p.then) p.catch(done);
      } catch (e) { done(); }
    });
  }

  function enqueueTts(text, lang, sess) {
    if (!S.autoSpeak) return;
    var phrase = String(text || '').trim();
    if (!phrase || !lang) return;
    var key = lang + '|' + phrase.toLowerCase();
    if (sess && sess.lastSpeakKey === key) return;
    if (sess) sess.lastSpeakKey = key;
    S.ttsQueue.push({ text: phrase, lang: lang, sessId: sess ? sess.id : 0 });
    pumpTtsQueue();
  }

  async function pumpTtsQueue() {
    if (S.ttsPlaying) return;
    if (!S.ttsQueue.length) {
      resumeMicAfterTts();
      return;
    }
    S.ttsPlaying = true;
    var item = S.ttsQueue.shift();
    var active = S.session;
    if (active && active.active && !active.finalizing) {
      pauseMicForTts(active);
    }
    try {
      setStatus('🔊 ' + langOf(item.lang).flag + ' sesli çeviri…', !!(active && active.active));
      var b64 = await fetchTts(item.text, item.lang);
      if (b64) {
        if (active && active.id === item.sessId && active.lastAudioMsg) {
          active.lastAudioMsg.audio = b64;
        }
        await playB64(b64);
      }
    } catch (e) {
    } finally {
      S.ttsPlaying = false;
      if (S.ttsQueue.length) pumpTtsQueue();
      else resumeMicAfterTts();
    }
  }

  /**
   * Partial çeviriyi baştan tekrar okumadan, yalnızca yeni tamamlanmış bölümü seslendir.
   */
  function maybeSpeakTranslation(sess, fullTrans, forceAll, allowStable) {
    if (!sess || !S.autoSpeak) return;
    var text = String(fullTrans || '').trim();
    if (!text) return;

    var spoken = String(sess.spokenTrans || '').trim();
    var unsaid = text;
    if (spoken) {
      var idx = text.toLowerCase().indexOf(spoken.toLowerCase());
      if (idx === 0) {
        unsaid = text.slice(spoken.length).replace(/^\s+/, '');
      } else {
        var pref = commonPrefixLen(spoken, text);
        if (pref >= Math.min(12, spoken.length)) {
          unsaid = text.slice(pref).replace(/^\s+/, '');
          sess.spokenTrans = text.slice(0, pref).trim();
          spoken = sess.spokenTrans;
        } else {
          // Anlamlı yeniden yazım: henüz okunmamışsa forceAll dışında bekle
          if (!forceAll) return;
          unsaid = text;
          sess.spokenTrans = '';
          spoken = '';
        }
      }
    }

    if (!unsaid) return;

    var commit = '';
    if (forceAll) {
      commit = unsaid;
    } else {
      var sent = unsaid.match(/^([\s\S]+?[.!?…؟。！？]+)(?:\s+|$)/);
      if (sent) {
        commit = sent[1].trim();
      } else if (allowStable && wordCount(unsaid) >= TTS_MIN_WORDS && isMeaningfulPhrase(sess.liveOrig)) {
        commit = unsaid;
      } else if (allowStable && !spoken && wordCount(unsaid) >= 2 && unsaid.length >= 8) {
        // İlk anlamlı çeviriyi konuşma bitmeden seslendir
        commit = unsaid;
      } else {
        return;
      }
    }

    if (!commit) return;
    var nextSpoken = (spoken ? spoken + ' ' : '') + commit;
    nextSpoken = nextSpoken.replace(/\s+/g, ' ').trim();
    if (nextSpoken === spoken) return;
    sess.spokenTrans = nextSpoken;
    enqueueTts(commit, sess.to, sess);
  }

  function scheduleStableSpeak(sess) {
    if (!sess || !S.autoSpeak) return;
    if (sess.speakTimer) clearTimeout(sess.speakTimer);
    var snap = String(sess.liveTrans || '');
    sess.speakTimer = setTimeout(function () {
      sess.speakTimer = null;
      if (String(sess.liveTrans || '') !== snap) return;
      maybeSpeakTranslation(sess, sess.liveTrans, false, true);
    }, TTS_STABLE_MS);
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
    // force=1: klasik pair_safe yön sapmasını engelle; aynı kaliteli translate_text motoru
    var r = await fetch('/api/translate?' + new URLSearchParams({
      q: text, from: from, to: to, my: S.my, other: S.other, force: '1'
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
        '<p>Butona basılı tutup konuş. Anlamlı bölüm oluşunca hedef dilde yazılı ve sesli çeviri canlı güncellenir.</p>' +
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
    $('ltMicHintMe').textContent = my.name + ' → canlı çeviri + ses';
    $('ltMicHintOther').textContent = other.name + ' → canlı çeviri + ses';
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
      // Aktif oturum veya serbest bırakılmış aynı sess (finalize öncesi) kabul
      if (reqId !== sess.trReqId) return;
      if (S.session && S.session.id !== sess.id && !sess.detached) return;
      if (!translated) return;
      var prev = sess.liveTrans;
      sess.liveTrans = translated;
      sess.lastTranslatedOrig = text;
      sess.transStableAt = Date.now();
      updateLivePanel(sess.liveOrig, sess.liveTrans);
      setStatus('🔴 Canlı çeviri — konuşmaya devam', true);
      if (translated !== prev) {
        maybeSpeakTranslation(sess, translated, false, false);
        scheduleStableSpeak(sess);
      }
    } catch (e) {
      if (e && e.name === 'AbortError') return;
    } finally {
      if (reqId === sess.trReqId) {
        sess.translateInflight = false;
        if (sess.translatePending && sess.active && !sess.finalizing) {
          sess.translatePending = false;
          scheduleTranslate(sess);
        }
      }
    }
  }

  async function runLiveStt(sess) {
    if (!sess || !sess.active || sess.finalizing) return;
    if (S.ttsPlaying || S.ttsPausedMic) { sess.sttQueued = true; return; }
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
      if (sess.sttQueued && sess.active && !sess.finalizing && !S.ttsPlaying) {
        sess.sttQueued = false;
        runLiveStt(sess);
      }
    }
  }

  async function sttCompletePart(sess, blob) {
    if (!sess || !blob || blob.size < MIN_BLOB_BYTES) return;
    if (S.ttsPlaying || S.ttsPausedMic) return;
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
      stopWebSpeech(sess);
      var rec = new SR();
      rec.lang = langOf(sess.from).speech;
      rec.continuous = true;
      rec.interimResults = true;
      rec.maxAlternatives = 1;
      rec.onresult = function (ev) {
        if (!S.session || S.session.id !== sess.id || sess.finalizing) return;
        if (S.ttsPlaying || S.ttsPausedMic) return;
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
      rec.onend = function () {
        if (!S.session || S.session.id !== sess.id || !sess.active || sess.finalizing) return;
        if (S.ttsPlaying || S.ttsPausedMic || sess.webSpeechPaused) return;
        try { rec.start(); } catch (e) {
          sess.webSpeech = null;
          setTimeout(function () {
            if (S.session && S.session.id === sess.id && sess.active && !sess.finalizing) {
              startWebSpeechAssist(sess);
            }
          }, 120);
        }
      };
      rec.start();
      sess.webSpeech = rec;
    } catch (e) {}
  }

  function stopWebSpeech(sess) {
    if (!sess || !sess.webSpeech) return;
    try {
      sess.webSpeech.onresult = null;
      sess.webSpeech.onend = null;
      sess.webSpeech.onerror = null;
      if (sess.webSpeech.abort) sess.webSpeech.abort();
      else sess.webSpeech.stop();
    } catch (e) {}
    sess.webSpeech = null;
  }

  function releaseHardware(sess) {
    clearRollTimer(sess);
    stopWebSpeech(sess);
    abortFetches(sess);
    if (sess.speakTimer) { clearTimeout(sess.speakTimer); sess.speakTimer = null; }
    return Promise.resolve().then(function () {
      if (!sess.recorder || sess.recorder.state === 'inactive') return null;
      return stopRecorderBlob(sess.recorder);
    }).then(function (lastBlob) {
      if (lastBlob && lastBlob.size) sess.chunks.push(lastBlob);
      // Track'leri STOP ETME — aksi halde her basışta yeniden izin istenir ve 2. konuşma bozulur
      sess.stream = null;
      sess.recorder = null;
      setSharedMicEnabled(false);
      S.ttsPausedMic = false;
    });
  }

  function tryStartPending() {
    if (!S.pendingSide) return;
    if (S.session && S.session.active) return;
    var side = S.pendingSide;
    S.pendingSide = null;
    startSession(side);
  }

  async function startSession(side) {
    // Yalnızca aktif kayıt varken engelle. Finalize arka planda — ikinci basış çalışır.
    if (S.session && S.session.active) {
      S.pendingSide = side;
      return;
    }
    if (S.session && S.session.finalizing && !S.session.detached) {
      S.pendingSide = side;
      return;
    }

    hideError();
    unlockAudio();
    // Önceki TTS kuyruğunu temizleme: önceki cümlenin sonunu okumaya izin ver.
    // Yeni basışta echo olmaması için mikrofon açılınca pauseMicForTts zaten yok.

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

    // Yeni konuşmada önceki TTS'i kes — mikrofon echo'ya düşmesin
    stopTtsPlayback();

    var stream;
    try {
      stream = await ensureMicStream();
    } catch (e) {
      showError('Mikrofon izni gerekli. Ayarlar → Safari → Mikrofon');
      return;
    }

    // ensureMicStream sırasında başka oturum açıldıysa yeni kayıt başlatma
    if (S.session && S.session.active) {
      return;
    }

    setSharedMicEnabled(true);

    var mime = pickMime();
    var recorder;
    try {
      recorder = makeRecorder(stream, mime);
    } catch (e) {
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
      detached: false,
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
      spokenTrans: '',
      lastSpeakKey: '',
      speakTimer: null,
      transStableAt: 0,
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
      webSpeech: null,
      webSpeechPaused: false,
      lastAudioMsg: null
    };
    S.session = sess;
    S.ttsPausedMic = false;

    markMic(side, 'recording');
    showLivePanel(from, to);
    setStatus('🎙️ ' + langOf(from).flag + ' dinleniyor → ' + langOf(to).flag + ' canlı çeviri + ses', true);

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
    markMic(sess.side, 'processing');
    setStatus('✍️ Son bölüm tamamlanıyor…', true);

    var holdMs = Date.now() - sess.startedAt;

    // Mikrofon / recorder / webspeech'i hemen kapat — ikinci basış engellenmesin
    await new Promise(function (r) { setTimeout(r, RELEASE_TAIL_MS); });
    await releaseHardware(sess);

    // Oturumu aktif kayıt slotundan ayır (finalize arka planda)
    sess.detached = true;
    if (S.session && S.session.id === sess.id) S.session = null;
    clearMicUi();

    if (cancelled) {
      hideLivePanel();
      setStatus('Hangi taraf konuşacaksa o butona basılı tut', false);
      tryStartPending();
      return;
    }

    if (holdMs < MIN_HOLD_MS) {
      hideLivePanel();
      showError('Biraz daha uzun basılı tutun');
      setStatus('Hangi taraf konuşacaksa o butona basılı tut', false);
      tryStartPending();
      return;
    }

    // Mikrofon serbest — bekleyen ikinci basışı hemen başlat; finalize arka planda
    tryStartPending();
    finalizeUtterance(sess).finally(function () {
      tryStartPending();
    });
  }

  async function finalizeUtterance(sess) {
    var blob = new Blob(sess.chunks, { type: sess.mime || 'audio/webm' });
    if ((!blob.size || blob.size < MIN_BLOB_BYTES) && !sess.liveOrig) {
      hideLivePanel();
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

      var finalTrans = sess.liveTrans;
      if (!finalTrans || sess.lastTranslatedOrig !== finalOrig) {
        updateLivePanel(finalOrig, finalTrans || 'Son çeviri…');
        finalTrans = await fetchTranslate(finalOrig, sess.from, sess.to);
      }
      if (!finalTrans) throw new Error('Çeviri başarısız');

      sess.liveOrig = finalOrig;
      sess.liveTrans = finalTrans;

      var msg = {
        orig: finalOrig,
        trans: finalTrans,
        from: sess.from,
        to: sess.to,
        audio: null,
        speaker: sess.side
      };
      sess.lastAudioMsg = msg;
      S.msgs.unshift(msg);
      render();
      hideLivePanel();
      setStatus('Çeviri hazır', false);

      // Son eksik hedef dil bölümünü seslendir (tekrar okumadan)
      maybeSpeakTranslation(sess, finalTrans, true);

      // Tekrar dinle için tam cümle TTS'i arka planda al (kuyruk boşsa / ek olarak)
      if (S.autoSpeak && !msg.audio) {
        try {
          var b64 = await fetchTts(finalTrans, sess.to);
          if (b64) {
            msg.audio = b64;
            render();
          }
        } catch (e) {}
      }
    } catch (e) {
      showError((e && e.message) || 'Konuşma anlaşılamadı. Lütfen tekrar konuşun.');
      hideLivePanel();
      setStatus('Hangi taraf konuşacaksa o butona basılı tut', false);
    }
  }

  function bindHold(btn, side) {
    if (!btn) return;
    function down(e) {
      e.preventDefault();
      if (S.session && S.session.active) return;
      startSession(side);
    }
    function up(e) {
      e.preventDefault();
      if (!S.session || !S.session.active || S.session.finalizing) return;
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
    if (!S.autoSpeak) stopTtsPlayback();
  };

  syncUi();
  render();
  setStatus('Hangi taraf konuşacaksa o butona basılı tut', false);
})();

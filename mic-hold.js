/**
 * iOS Safari–safe hold-to-talk microphone (shared by translate + education).
 */
(function (global) {
  'use strict';

  const IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

  const DEFAULT_MIC_OPTS = {
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  };

  function delay(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  function pickMime() {
    if (typeof MediaRecorder === 'undefined') return '';
    for (const m of ['audio/mp4', 'audio/aac', 'audio/webm;codecs=opus', 'audio/webm']) {
      if (MediaRecorder.isTypeSupported(m)) return m;
    }
    return '';
  }

  function createMicHold(cfg) {
    const S = cfg.state;
    const tailMs = cfg.tailMs ?? 450;
    const minHoldMs = cfg.minHoldMs ?? 400;
    const minBlobBytes = cfg.minBlobBytes ?? 200;
    const micOpenMs = cfg.micOpenMs ?? 12000;
    const micOpts = cfg.micOpts ?? DEFAULT_MIC_OPTS;

    if (S.pendingEndHold == null) S.pendingEndHold = false;
    if (S.micOpening == null) S.micOpening = false;
    if (S.micOpenGen == null) S.micOpenGen = 0;

    function isRecording() {
      return S.recorder?.state === 'recording';
    }

    function cleanupRecorder() {
      if (!S.recorder) return;
      S.recorder.ondataavailable = null;
      S.recorder.onstop = null;
      S.recorder = null;
    }

    function releaseStream() {
      if (S.stream) {
        S.stream.getTracks().forEach((t) => {
          try { t.stop(); } catch { /* ignore */ }
        });
        S.stream = null;
      }
    }

    function teardownMicOnly() {
      clearTimeout(S.stopTimer);
      clearTimeout(S.safetyTimer);
      S.stopTimer = null;
      S.safetyTimer = null;
      if (S.recorder) {
        if (S.recorder.state === 'recording') {
          try { S.recorder.stop(); } catch { cleanupRecorder(); }
        } else {
          cleanupRecorder();
        }
      }
      releaseStream();
    }

    function releaseMic() {
      teardownMicOnly();
      S.micOpening = false;
      S.pendingEndHold = false;
    }

    async function iosSafeStop(recorder) {
      if (!recorder || recorder.state !== 'recording') return;
      try { recorder.requestData(); } catch { /* ignore */ }
      await delay(IS_IOS ? 140 : 70);
      if (recorder.state === 'recording') {
        try { recorder.requestData(); } catch { /* ignore */ }
        await delay(IS_IOS ? 140 : 70);
      }
      if (recorder.state === 'recording') {
        try { recorder.stop(); } catch { /* ignore */ }
      }
    }

    async function openFreshMic(openGen) {
      if (IS_IOS || !S.stream) {
        teardownMicOnly();
        await delay(IS_IOS ? 80 : 30);
      } else {
        const tracks = S.stream.getAudioTracks();
        const live = tracks.length > 0 && tracks.every((t) => t.readyState === 'live' && t.enabled);
        if (live) return S.stream;
        releaseStream();
      }

      if (S.micOpenGen !== openGen) throw new Error('cancelled');

      const micPromise = navigator.mediaDevices.getUserMedia(micOpts);
      const timeout = new Promise((_, reject) => {
        setTimeout(() => reject(new Error('Mikrofon açılamadı — tekrar dene')), micOpenMs);
      });
      S.stream = await Promise.race([micPromise, timeout]);
      return S.stream;
    }

    function deliverBlob(blob, pressMs) {
      if (pressMs < minHoldMs) {
        if (cfg.onShortHold) cfg.onShortHold(pressMs);
        else cfg.onError?.('Biraz daha uzun basılı tutun');
        if (!cfg.isBusy?.()) cfg.onIdle?.();
        return;
      }
      if (!blob || blob.size < minBlobBytes) {
        if (cfg.onEmptyBlob) cfg.onEmptyBlob(blob?.size ?? 0);
        else cfg.onError?.('Ses duyulamadı — tekrar dene');
        if (!cfg.isBusy?.()) cfg.onIdle?.();
        return;
      }
      cfg.onBlob(blob, pressMs);
    }

    function startRecorder(gen) {
      const mime = pickMime();
      S.chunks = [];
      S.stopHandled = false;

      const tracks = S.stream?.getAudioTracks?.() ?? [];
      if (!S.stream || !tracks.length || !tracks.every((t) => t.readyState === 'live')) {
        cfg.onError?.('Mikrofon hazır değil — tekrar dene');
        if (!cfg.isBusy?.()) cfg.onIdle?.();
        return;
      }

      try {
        S.recorder = mime
          ? new MediaRecorder(S.stream, { mimeType: mime, audioBitsPerSecond: 128000 })
          : new MediaRecorder(S.stream);
      } catch {
        cfg.onError?.('Kayıt başlatılamadı — tekrar dene');
        if (!cfg.isBusy?.()) cfg.onIdle?.();
        return;
      }

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
        S.pendingEndHold = false;
        cleanupRecorder();

        const blob = chunks.length
          ? new Blob(chunks, { type: mimeType })
          : new Blob([], { type: mimeType });
        deliverBlob(blob, pressMs);
      };

      try {
        if (IS_IOS) S.recorder.start();
        else S.recorder.start(250);
      } catch {
        cleanupRecorder();
        cfg.onError?.('Kayıt başlatılamadı');
        if (!cfg.isBusy?.()) cfg.onIdle?.();
        return;
      }

      if (S.pendingEndHold || !S.holdActive || S.holdGen !== gen) {
        finishRecording();
      }
    }

    function finishRecording() {
      if (!isRecording()) {
        if (S.pendingEndHold && (S.pressMs || 0) >= minHoldMs) {
          S.pendingEndHold = false;
          cfg.onError?.('Mikrofon geç açıldı — tekrar basılı tut');
          if (!cfg.isBusy?.()) cfg.onIdle?.();
        }
        return;
      }
      clearTimeout(S.stopTimer);
      S.stopTimer = setTimeout(() => {
        void iosSafeStop(S.recorder);
      }, tailMs);
    }

    async function beginHold() {
      const gen = ++S.holdGen;

      if (cfg.canBegin && cfg.canBegin() === false) return;

      if (cfg.beforeBegin) {
        try { await cfg.beforeBegin(); } catch { /* ignore */ }
      }

      S.holdActive = true;
      S.pendingEndHold = false;
      S.fingerDownAt = Date.now();
      cfg.onHideError?.();
      cfg.onSpeaking?.();
      cfg.unlockAudio?.();
      cfg.stopTts?.();

      if (!navigator.mediaDevices?.getUserMedia) {
        cfg.onError?.('Mikrofon için Safari gerekli');
        cfg.onIdle?.();
        return;
      }

      if (isRecording()) return;

      const openGen = ++S.micOpenGen;
      S.micOpening = true;
      cfg.onMicOpening?.();

      try {
        await openFreshMic(openGen);
        S.micOpening = false;

        if (S.holdGen !== gen) {
          releaseStream();
          cfg.onIdle?.();
          return;
        }

        if (!S.holdActive && !S.pendingEndHold) {
          releaseStream();
          cfg.onIdle?.();
          return;
        }

        startRecorder(gen);
      } catch (e) {
        S.micOpening = false;
        if (e?.message === 'cancelled') {
          cfg.onIdle?.();
          return;
        }
        teardownMicOnly();
        cfg.onError?.(e?.message || 'Mikrofon izni gerekli. Ayarlar → Safari → Mikrofon');
        cfg.onIdle?.();
      }
    }

    function endHold() {
      if (S.fingerDownAt) S.pressMs = Date.now() - S.fingerDownAt;
      S.holdActive = false;

      if (!isRecording()) {
        if (S.micOpening) {
          S.pendingEndHold = true;
          if ((S.pressMs || 0) >= minHoldMs) cfg.onProcessing?.();
          return;
        }
        S.pendingEndHold = false;
        if ((S.pressMs || 0) >= minHoldMs && !cfg.isBusy?.()) {
          cfg.onError?.('Kayıt başlamadı — tekrar dene');
        }
        cfg.onIdle?.();
        return;
      }

      cfg.onProcessing?.();

      clearTimeout(S.safetyTimer);
      S.safetyTimer = setTimeout(() => {
        if (isRecording()) void iosSafeStop(S.recorder);
        else if (!cfg.isBusy?.()) cfg.onIdle?.();
      }, 8000);

      finishRecording();
    }

    function bindHold(el) {
      if (!el) return;
      const down = (e) => { e.preventDefault(); void beginHold(); };
      const up = (e) => { e.preventDefault(); endHold(); };

      el.addEventListener('contextmenu', (e) => e.preventDefault());
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

    return {
      beginHold,
      endHold,
      bindHold,
      releaseMic,
      isRecording,
    };
  }

  global.MicHold = { create: createMicHold, IS_IOS };
})(typeof window !== 'undefined' ? window : globalThis);

/* Gemini Live — iki yönlü anlık ses (tarayıcı tarafı)
 *
 * LiveAudio.unlock()                 → iOS: ses/mikrofon bağlamını kullanıcı dokunuşunda aç
 * LiveAudio.Mic                      → mikrofon → 16 kHz PCM16 parçaları (100 ms)
 * LiveAudio.Player                   → 24 kHz PCM16 parçalarını gecikmesiz sırayla çal
 * LiveAudio.Session                  → /api/live/session jetonuyla Google'a doğrudan WebSocket
 */
(function (global) {
  'use strict';

  let ctx = null;
  function audioCtx() {
    if (!ctx) {
      const AC = global.AudioContext || global.webkitAudioContext;
      ctx = new AC({ latencyHint: 'interactive' });
    }
    return ctx;
  }
  function unlock() {
    const c = audioCtx();
    if (c.state !== 'running') c.resume().catch(() => {});
    try {
      // iOS: sessiz bir tampon çal → hoparlör yolu açılır
      const b = c.createBuffer(1, 1, 22050);
      const s = c.createBufferSource();
      s.buffer = b; s.connect(c.destination); s.start(0);
    } catch { /* ignore */ }
    return c;
  }
  function setSession(type) {
    try { if (navigator.audioSession) navigator.audioSession.type = type; } catch { /* ignore */ }
  }

  function b64FromBytes(u8) {
    let s = '';
    for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    return btoa(s);
  }
  function bytesFromB64(b64) {
    const bin = atob(b64);
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return u8;
  }

  // ------------------------------------------------------------- Mic (16 kHz PCM16)
  const WORKLET = `
  class Pcm16Down extends AudioWorkletProcessor {
    constructor(o) { super(); this.ratio = sampleRate / 16000; this.pos = 0; this.buf = new Int16Array(1600); this.n = 0; this.on = true;
      this.port.onmessage = (e) => { if (e.data === 'flush') this.flush(); }; }
    flush() { if (this.n > 0) { this.port.postMessage(this.buf.slice(0, this.n).buffer, []); this.n = 0; } }
    process(inputs) {
      const ch = inputs[0] && inputs[0][0];
      if (!ch) return true;
      let level = 0;
      for (let i = 0; i < ch.length; i++) { const a = Math.abs(ch[i]); if (a > level) level = a; }
      while (this.pos < ch.length) {
        const i = Math.floor(this.pos), f = this.pos - i;
        const v = i + 1 < ch.length ? ch[i] * (1 - f) + ch[i + 1] * f : ch[i];
        const s = Math.max(-1, Math.min(1, v));
        this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0).buffer, []); this.n = 0; }
        this.pos += this.ratio;
      }
      this.pos -= ch.length;
      this.port.postMessage({ level });
      return true;
    }
  }
  registerProcessor('pcm16-down', Pcm16Down);`;
  let workletReady = null;

  class Mic {
    constructor({ onChunk, onLevel } = {}) {
      this.onChunk = onChunk; this.onLevel = onLevel;
      this.stream = null; this.node = null; this.src = null; this.active = false;
    }
    async start() {
      if (this.active) return;
      this.active = true;
      const c = audioCtx();
      if (c.state !== 'running') await c.resume().catch(() => {});
      setSession('play-and-record');
      if (!workletReady) {
        const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
        workletReady = c.audioWorklet.addModule(url);
      }
      const [stream] = await Promise.all([
        navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } }),
        workletReady,
      ]);
      if (!this.active) { stream.getTracks().forEach((t) => t.stop()); return; }
      this.stream = stream;
      this.src = c.createMediaStreamSource(stream);
      this.node = new AudioWorkletNode(c, 'pcm16-down');
      this.node.port.onmessage = (e) => {
        if (e.data instanceof ArrayBuffer) { if (this.onChunk) this.onChunk(new Uint8Array(e.data)); }
        else if (e.data && this.onLevel) this.onLevel(e.data.level || 0);
      };
      // Çıkışa bağlamak (sessiz kazançla) Safari'de işlemenin durmamasını sağlar
      const mute = c.createGain(); mute.gain.value = 0;
      this.src.connect(this.node); this.node.connect(mute); mute.connect(c.destination);
    }
    stop() {
      this.active = false;
      try { if (this.node) this.node.port.postMessage('flush'); } catch { /* ignore */ }
      const node = this.node, src = this.src, stream = this.stream;
      this.node = this.src = this.stream = null;
      setTimeout(() => {
        try { if (src) src.disconnect(); } catch { /* ignore */ }
        try { if (node) node.disconnect(); } catch { /* ignore */ }
        if (stream) stream.getTracks().forEach((t) => t.stop());
        setSession('playback');
      }, 60);
    }
  }

  // ------------------------------------------------------------- Player (24 kHz PCM16)
  class Player {
    constructor({ onStart, onIdle } = {}) {
      this.onStart = onStart; this.onIdle = onIdle;
      this.next = 0; this.sources = new Set(); this.playing = false; this.idleTimer = null;
    }
    enqueue(u8, rate = 24000) {
      const c = audioCtx();
      if (c.state !== 'running') c.resume().catch(() => {});
      const n = Math.floor(u8.byteLength / 2);
      if (!n) return;
      const i16 = new Int16Array(u8.buffer, u8.byteOffset, n);
      const buf = c.createBuffer(1, n, rate);
      const ch = buf.getChannelData(0);
      for (let i = 0; i < n; i++) ch[i] = i16[i] / 32768;
      const s = c.createBufferSource();
      s.buffer = buf; s.connect(c.destination);
      const now = c.currentTime;
      if (this.next < now + 0.02) this.next = now + 0.04;
      s.start(this.next);
      this.next += buf.duration;
      this.sources.add(s);
      s.onended = () => { this.sources.delete(s); this._checkIdle(); };
      if (!this.playing) { this.playing = true; if (this.onStart) this.onStart(); }
      clearTimeout(this.idleTimer);
    }
    _checkIdle() {
      clearTimeout(this.idleTimer);
      this.idleTimer = setTimeout(() => {
        if (!this.sources.size && this.playing) { this.playing = false; if (this.onIdle) this.onIdle(); }
      }, 120);
    }
    stop() {
      this.sources.forEach((s) => { try { s.stop(); } catch { /* ignore */ } });
      this.sources.clear();
      this.next = 0;
      if (this.playing) { this.playing = false; if (this.onIdle) this.onIdle(); }
    }
    /** Kaydedilmiş parçaları baştan çal (tekrar dinle) */
    replay(chunks, rate = 24000) { this.stop(); (chunks || []).forEach((u8) => this.enqueue(u8, rate)); }
  }

  // ------------------------------------------------------------- Session
  class Session {
    /**
     * opts: { body: {...} (sent to /api/live/session), manualActivity: bool,
     *         onAudio(u8), onInput(text), onOutput(text), onTurnComplete(), onInterrupted(), onState(state, info) }
     */
    constructor(opts) {
      this.o = opts; this.ws = null; this.state = 'idle'; this.ready = null; this.handle = null;
      this.variant = 0; this.lastUse = 0;
    }
    get isOpen() { return this.ws && this.ws.readyState === 1 && this.state === 'ready'; }
    _set(state, info) { this.state = state; if (this.o.onState) this.o.onState(state, info); }
    connect() {
      if (this.isOpen) return Promise.resolve();
      if (this.ready) return this.ready;
      this._set('connecting');
      this.ready = this._open().finally(() => { this.ready = null; });
      return this.ready;
    }
    async _open(attempt = 0) {
      const body = Object.assign({}, this.o.body || {}, { variant: this.variant });
      let d;
      try {
        const r = await fetch('/api/live/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        d = await r.json();
        if (!r.ok || !d.ok) throw new Error(d.error || 'Canlı ses bağlantısı kurulamadı');
      } catch (e) {
        this._set('error', e.message);
        throw e;
      }
      const setup = d.setup;
      if (this.handle && setup.sessionResumption) setup.sessionResumption = { handle: this.handle };
      await new Promise((resolve, reject) => {
        const ws = new WebSocket(d.ws);
        this.ws = ws;
        let done = false;
        const timer = setTimeout(() => { if (!done) { done = true; try { ws.close(); } catch { /* ignore */ } reject(new Error('Bağlantı zaman aşımı')); } }, 12000);
        ws.onopen = () => ws.send(JSON.stringify({ setup }));
        ws.onmessage = async (ev) => {
          let m;
          try { m = JSON.parse(typeof ev.data === 'string' ? ev.data : await ev.data.text()); } catch { return; }
          if (m.setupComplete !== undefined) {
            if (!done) { done = true; clearTimeout(timer); this._set('ready'); resolve(); if (this.o.onReady) this.o.onReady(); }
            return;
          }
          this._onMessage(m);
        };
        ws.onclose = (e) => {
          clearTimeout(timer);
          if (this.ws === ws) this.ws = null;
          if (!done) {
            done = true;
            // Kurulum reddedildi → diğer biçimi dene (yalnızca bir kez)
            if (e.code === 1007 && attempt === 0) { this.variant = this.variant ? 0 : 1; this.handle = null; this._open(1).then(resolve, reject); return; }
            reject(new Error(e.reason ? `Bağlantı kapandı: ${String(e.reason).slice(0, 80)}` : 'Bağlantı kapandı'));
            return;
          }
          this._set('closed', e.code);
        };
        ws.onerror = () => {};
      });
    }
    _onMessage(m) {
      if (m.sessionResumptionUpdate && m.sessionResumptionUpdate.resumable && m.sessionResumptionUpdate.newHandle) {
        this.handle = m.sessionResumptionUpdate.newHandle;
      }
      if (m.goAway) { this._set('goaway'); }
      const sc = m.serverContent;
      if (!sc) return;
      if (sc.interrupted && this.o.onInterrupted) this.o.onInterrupted();
      if (sc.inputTranscription && sc.inputTranscription.text && this.o.onInput) this.o.onInput(sc.inputTranscription.text);
      if (sc.modelTurn && sc.modelTurn.parts) {
        for (const p of sc.modelTurn.parts) {
          if (p.inlineData && p.inlineData.data && this.o.onAudio) {
            const rate = Number((String(p.inlineData.mimeType || '').match(/rate=(\d+)/) || [])[1]) || 24000;
            this.o.onAudio(bytesFromB64(p.inlineData.data), rate);
          }
        }
      }
      if (sc.outputTranscription && sc.outputTranscription.text && this.o.onOutput) this.o.onOutput(sc.outputTranscription.text);
      if (sc.turnComplete && this.o.onTurnComplete) this.o.onTurnComplete();
    }
    send(obj) {
      if (!this.ws || this.ws.readyState !== 1) return false;
      this.ws.send(JSON.stringify(obj));
      this.lastUse = Date.now();
      return true;
    }
    sendAudio(u8) { return this.send({ realtimeInput: { audio: { data: b64FromBytes(u8), mimeType: 'audio/pcm;rate=16000' } } }); }
    activityStart() { return this.send({ realtimeInput: { activityStart: {} } }); }
    activityEnd() { return this.send({ realtimeInput: { activityEnd: {} } }); }
    sendText(text) { return this.send({ realtimeInput: { text } }); }
    seed(turns) {
      if (!turns || !turns.length) return false;
      return this.send({ clientContent: { turns, turnComplete: false } });
    }
    close() {
      const ws = this.ws; this.ws = null; this.handle = null;
      if (ws) { try { ws.close(); } catch { /* ignore */ } }
      this._set('idle');
    }
  }

  global.LiveAudio = { unlock, audioCtx, Mic, Player, Session, b64FromBytes, bytesFromB64 };
})(typeof window !== 'undefined' ? window : globalThis);

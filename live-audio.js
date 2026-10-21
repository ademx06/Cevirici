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
    try { const cc = captureCtx(); if (cc.state !== 'running') cc.resume().catch(() => {}); } catch { /* ignore */ }
    try {
      // iOS: sessiz bir tampon çal → hoparlör yolu açılır
      const b = c.createBuffer(1, 1, 22050);
      const s = c.createBufferSource();
      s.buffer = b; s.connect(c.destination); s.start(0);
    } catch { /* ignore */ }
    return c;
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
  // Kayıt için AYRI bir ses bağlamı: iPhone'da mikrofon açılıp kapanırken çalma bağlamı etkilenmesin (kesik ses olmasın)
  const WORKLET = `
  class Pcm16Down extends AudioWorkletProcessor {
    constructor() { super(); this.ratio = sampleRate / 16000; this.pos = 0; this.buf = new Int16Array(1600); this.n = 0; this.peak = 0; this.frames = 0;
      this.port.onmessage = (e) => { if (e.data === 'flush') this.flush(); }; }
    flush() { if (this.n > 0) { this.port.postMessage(this.buf.slice(0, this.n).buffer); this.n = 0; } }
    process(inputs) {
      const ch = inputs[0] && inputs[0][0];
      if (!ch) return true;
      for (let i = 0; i < ch.length; i++) { const a = ch[i] < 0 ? -ch[i] : ch[i]; if (a > this.peak) this.peak = a; }
      while (this.pos < ch.length) {
        const i = this.pos | 0, f = this.pos - i;
        const v = i + 1 < ch.length ? ch[i] * (1 - f) + ch[i + 1] * f : ch[i];
        const s = v > 1 ? 1 : v < -1 ? -1 : v;
        this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0).buffer); this.n = 0; }
        this.pos += this.ratio;
      }
      this.pos -= ch.length;
      if (++this.frames >= 12) { this.port.postMessage({ level: this.peak }); this.frames = 0; this.peak = 0; } // ~30/sn
      return true;
    }
  }
  registerProcessor('pcm16-down', Pcm16Down);`;
  let capCtx = null;
  let capReady = null;
  function captureCtx() {
    if (!capCtx) {
      const AC = global.AudioContext || global.webkitAudioContext;
      capCtx = new AC({ latencyHint: 'interactive' });
      const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
      capReady = capCtx.audioWorklet.addModule(url);
    }
    return capCtx;
  }

  class Mic {
    constructor({ onChunk, onLevel, onLive } = {}) {
      this.onChunk = onChunk; this.onLevel = onLevel; this.onLive = onLive;
      this.stream = null; this.node = null; this.src = null; this.active = false;
    }
    async start() {
      if (this.active) return;
      this.active = true;
      const c = captureCtx();
      const streamP = navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
      if (c.state !== 'running') c.resume().catch(() => {});
      const [stream] = await Promise.all([streamP, capReady]);
      if (!this.active) { stream.getTracks().forEach((t) => t.stop()); return; }
      if (c.state !== 'running') await c.resume().catch(() => {});
      this.stream = stream;
      this.src = c.createMediaStreamSource(stream);
      this.node = new AudioWorkletNode(c, 'pcm16-down');
      this.node.port.onmessage = (e) => {
        if (e.data instanceof ArrayBuffer) { if (this.onChunk) this.onChunk(new Uint8Array(e.data)); }
        else if (e.data && this.onLevel) this.onLevel(e.data.level || 0);
      };
      const mute = c.createGain(); mute.gain.value = 0;
      this.src.connect(this.node); this.node.connect(mute); mute.connect(c.destination);
      this._mute = mute;
      if (this.onLive) this.onLive(); // mikrofon gerçekten açıldı → kullanıcı konuşabilir
    }
    stop() {
      this.active = false;
      try { if (this.node) this.node.port.postMessage('flush'); } catch { /* ignore */ }
      const node = this.node, src = this.src, stream = this.stream, mute = this._mute;
      this.node = this.src = this.stream = this._mute = null;
      setTimeout(() => {
        try { if (src) src.disconnect(); } catch { /* ignore */ }
        try { if (node) node.disconnect(); } catch { /* ignore */ }
        try { if (mute) mute.disconnect(); } catch { /* ignore */ }
        if (stream) stream.getTracks().forEach((t) => t.stop());
        // kayıt bağlamını beklet; çalma bağlamını ayağa kaldır (iOS ses yolu değişiminden sonra)
        if (capCtx && capCtx.state === 'running') capCtx.suspend().catch(() => {});
        const p = audioCtx();
        if (p.state !== 'running') p.resume().catch(() => {});
      }, 80);
    }
  }

  // ------------------------------------------------------------- Player (24 kHz PCM16)
  class Player {
    constructor({ onStart, onIdle } = {}) {
      this.onStart = onStart; this.onIdle = onIdle;
      this.next = 0; this.sources = new Set(); this.playing = false; this.idleTimer = null;
      this.pend = []; this.pendLen = 0; this.flushTimer = null;
    }
    /** Küçük parçaları birleştirip (~120 ms) planla → daha az düğüm, daha akıcı ses */
    enqueue(u8, rate = 24000) {
      this.rate = rate;
      this.pend.push(u8); this.pendLen += u8.byteLength;
      const minBytes = Math.round(rate * 2 * (this.playing ? 0.08 : 0.12));
      clearTimeout(this.flushTimer);
      if (this.pendLen >= minBytes) this._flush();
      else this.flushTimer = setTimeout(() => this._flush(), 60);
    }
    _flush() {
      clearTimeout(this.flushTimer);
      if (!this.pendLen) return;
      const all = new Uint8Array(this.pendLen);
      let o = 0; for (const p of this.pend) { all.set(p, o); o += p.byteLength; }
      this.pend = []; this.pendLen = 0;
      this._schedule(all, this.rate || 24000);
    }
    _schedule(u8, rate) {
      const c = audioCtx();
      if (c.state !== 'running') c.resume().catch(() => {});
      const n = Math.floor(u8.byteLength / 2);
      if (!n) return;
      const dv = new DataView(u8.buffer, u8.byteOffset, n * 2);
      const buf = c.createBuffer(1, n, rate);
      const ch = buf.getChannelData(0);
      for (let i = 0; i < n; i++) ch[i] = dv.getInt16(i * 2, true) / 32768;
      const s = c.createBufferSource();
      s.buffer = buf; s.connect(c.destination);
      const now = c.currentTime;
      // Tampon: yeni akışta 200 ms önde başla; ağ boşluğu olursa 150 ms yeniden tamponla → kesik ses yok
      if (this.next < now + 0.03) this.next = now + (this.playing ? 0.15 : 0.2);
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
        if (!this.sources.size && !this.pendLen && this.playing) { this.playing = false; if (this.onIdle) this.onIdle(); }
      }, 150);
    }
    stop() {
      clearTimeout(this.flushTimer);
      this.pend = []; this.pendLen = 0;
      this.sources.forEach((s) => { try { s.stop(); } catch { /* ignore */ } });
      this.sources.clear();
      this.next = 0;
      if (this.playing) { this.playing = false; if (this.onIdle) this.onIdle(); }
    }
    /** Kaydedilmiş parçaları baştan çal (tekrar dinle) */
    replay(chunks, rate = 24000) { this.stop(); (chunks || []).forEach((u8) => this.enqueue(u8, rate)); this._flush(); }
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
      if (sc.interimInputTranscription && sc.interimInputTranscription.text && this.o.onInterim) this.o.onInterim(sc.interimInputTranscription.text);
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

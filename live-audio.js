/* Gemini Live — iki yönlü anlık ses (tarayıcı tarafı)
 *
 * Mimari (v5):
 *  • Mikrofon bir kez açılır ve sayfa açıkken AÇIK kalır ("sıcak mikrofon"). Basınca yalnızca kapı açılır →
 *    gecikme yok; iPhone'da ses donanımı yeniden ayarlanmaz → cevap sesi titremez / tonu kaymaz.
 *  • Ses bağlamı mikrofon açıldıktan SONRA kurulur → örnekleme hızı donanımla birebir (bozuk/yanlış perdeli ses yok).
 *  • Son ~250 ms her zaman tamponda tutulur → bastığın an konuşmaya başlasan da ilk hece kaybolmaz.
 *
 * LiveAudio.unlock()            → kullanıcı dokunuşunda ses bağlamını uyandır
 * LiveAudio.micReady()          → mikrofon şu an açık mı (basınca anında kayıt)
 * LiveAudio.micPermission()     → 'granted' | 'prompt' | 'denied' | 'unknown'
 * LiveAudio.openMic()           → mikrofonu aç (gerekirse izin ister)
 * LiveAudio.Mic                 → kayıt "musluğu": start() kapıyı açar, stop() kapatır (16 kHz PCM16, 100 ms)
 * LiveAudio.Player              → 24 kHz PCM16 parçalarını boşluksuz çal
 * LiveAudio.Session             → /api/live/session jetonuyla Google'a doğrudan WebSocket
 */
(function (global) {
  'use strict';

  const AC = global.AudioContext || global.webkitAudioContext;
  let ctx = null; // tek ses bağlamı (çalma + kayıt)
  let ctxGen = 0;
  function newCtx() { ctxGen += 1; return new AC({ latencyHint: 'interactive' }); }
  function audioCtx() { if (!ctx) ctx = newCtx(); return ctx; }
  function setSession(type) { try { if (navigator.audioSession) navigator.audioSession.type = type; } catch { /* ignore */ } }

  function unlock() {
    if (!(eng.node && eng.stream && eng.stream.active)) setSession('playback'); // sessiz tuşu açıkken de çalsın (yazıyla sorulunca)
    const c = audioCtx();
    if (c.state !== 'running') c.resume().catch(() => {});
    try {
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

  // ------------------------------------------------------------- worklet: 16 kHz'e indir (ortalamalı), kapı + ön tampon
  const WORKLET = `
  class Pcm16Gate extends AudioWorkletProcessor {
    constructor() {
      super();
      this.ratio = sampleRate / 16000;
      this.acc = 0; this.cnt = 0; this.pos = 0; this.prev = 0;
      this.ring = new Int16Array(4000); this.rn = 0; this.rfull = false;   // ~250 ms ön tampon
      this.buf = new Int16Array(1600); this.n = 0;                          // 100 ms parça
      this.id = 0; this.peak = 0; this.frames = 0;
      this.port.onmessage = (e) => {
        const d = e.data || {};
        if (d.cmd === 'on') {
          this.id = d.id; this.n = 0;
          if (d.preroll) {
            let r;
            if (this.rfull) { r = new Int16Array(this.ring.length); r.set(this.ring.subarray(this.rn)); r.set(this.ring.subarray(0, this.rn), this.ring.length - this.rn); }
            else r = this.ring.slice(0, this.rn);
            if (r.length) this.port.postMessage({ id: this.id, pcm: r.buffer }, [r.buffer]);
          }
        } else if (d.cmd === 'off') {
          if (this.id && this.n) { const b = this.buf.slice(0, this.n); this.port.postMessage({ id: this.id, pcm: b.buffer }, [b.buffer]); }
          this.port.postMessage({ id: this.id || d.id, done: true });
          this.id = 0; this.n = 0;
        }
      };
    }
    out(v) {
      const s = v > 1 ? 1 : v < -1 ? -1 : v;
      const q = s < 0 ? s * 0x8000 : s * 0x7fff;
      this.ring[this.rn++] = q; if (this.rn === this.ring.length) { this.rn = 0; this.rfull = true; }
      if (!this.id) return;
      this.buf[this.n++] = q;
      if (this.n === this.buf.length) { const b = this.buf.slice(0); this.port.postMessage({ id: this.id, pcm: b.buffer }, [b.buffer]); this.n = 0; }
    }
    process(inputs) {
      const ch = inputs[0] && inputs[0][0];
      if (!ch) return true;
      if (this.ratio >= 1) {
        // kutu filtresi: her çıkış örneği = karşılık gelen giriş örneklerinin ortalaması (net, cızırtısız)
        for (let i = 0; i < ch.length; i++) {
          const x = ch[i];
          if (this.id) { const a = x < 0 ? -x : x; if (a > this.peak) this.peak = a; }
          this.acc += x; this.cnt++; this.pos += 1;
          if (this.pos >= this.ratio) { this.out(this.acc / this.cnt); this.acc = 0; this.cnt = 0; this.pos -= this.ratio; }
        }
      } else {
        for (let i = 0; i < ch.length; i++) {
          const x = ch[i];
          if (this.id) { const a = x < 0 ? -x : x; if (a > this.peak) this.peak = a; }
          while (this.pos < 1) { this.out(this.prev + (x - this.prev) * this.pos); this.pos += this.ratio; }
          this.pos -= 1; this.prev = x;
        }
      }
      if (this.id && ++this.frames >= 10) { this.port.postMessage({ id: this.id, level: this.peak }); this.frames = 0; this.peak = 0; }
      return true;
    }
  }
  registerProcessor('pcm16-gate', Pcm16Gate);`;
  let workletUrl = null;

  // ------------------------------------------------------------- sıcak mikrofon
  const eng = { stream: null, ctx: null, src: null, node: null, mute: null, opening: null, taps: new Map(), seq: 0 };
  function micReady() {
    // iOS: arama/Siri/uygulama değişimi sonrası iz 'muted' ya da bağlam kapanmış olabilir → hazır sayma, yeniden aç
    return !!(eng.node && eng.stream && eng.stream.active && eng.ctx && eng.ctx.state !== 'closed'
      && eng.stream.getAudioTracks().some((t) => t.readyState === 'live' && !t.muted));
  }

  async function micPermission() {
    if (micReady()) return 'granted';
    try {
      const p = await navigator.permissions.query({ name: 'microphone' });
      if (p && p.state) return p.state;
    } catch { /* desteklenmiyor */ }
    try { if (localStorage.getItem('mic_ok') === '1') return 'granted'; } catch { /* ignore */ }
    return 'unknown';
  }

  function openMic() {
    if (micReady()) return Promise.resolve(eng);
    if (eng.opening) return eng.opening;
    if (eng.stream || eng.node) closeMic(); // bayat/susmuş akışı temizle
    eng.opening = (async () => {
      setSession('play-and-record');
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
      try { localStorage.setItem('mic_ok', '1'); } catch { /* ignore */ }
      // Mikrofon açıldı → ses donanımı artık kayıt+çalma modunda; bağlamı ŞİMDİ kur (hız birebir)
      const old = ctx;
      const c = newCtx();
      ctx = c;
      if (old) setTimeout(() => { try { old.close(); } catch { /* ignore */ } }, 4000);
      if (!workletUrl) workletUrl = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
      await c.audioWorklet.addModule(workletUrl);
      if (c.state !== 'running') await c.resume().catch(() => {});
      const src = c.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(c, 'pcm16-gate');
      const mute = c.createGain(); mute.gain.value = 0;
      src.connect(node); node.connect(mute); mute.connect(c.destination);
      node.port.onmessage = (e) => {
        const d = e.data || {};
        const tap = eng.taps.get(d.id);
        if (!tap) return;
        if (d.pcm) { if (tap.onChunk) tap.onChunk(new Uint8Array(d.pcm)); }
        else if (d.level !== undefined) { if (tap.onLevel) tap.onLevel(d.level); }
        else if (d.done) { eng.taps.delete(d.id); if (tap._done) tap._done(); }
      };
      Object.assign(eng, { stream, ctx: c, src, node, mute });
      stream.getAudioTracks().forEach((t) => { t.onended = () => closeMic(); });
      return eng;
    })().finally(() => { eng.opening = null; });
    return eng.opening;
  }

  function closeMic() {
    const { stream, src, node, mute } = eng;
    eng.stream = eng.src = eng.node = eng.mute = eng.ctx = null;
    eng.taps.forEach((t) => { if (t._done) t._done(); });
    eng.taps.clear();
    try { if (src) src.disconnect(); } catch { /* ignore */ }
    try { if (node) node.disconnect(); } catch { /* ignore */ }
    try { if (mute) mute.disconnect(); } catch { /* ignore */ }
    if (stream) { stream.getTracks().forEach((t) => t.stop()); setSession('playback'); }
  }

  async function warmIfGranted() {
    if (micReady() || !navigator.mediaDevices) return;
    try {
      const p = await navigator.permissions.query({ name: 'microphone' });
      if (p.state === 'granted') await openMic();
    } catch { /* izin sorgulanamıyor → ilk basışta açılır */ }
  }
  // Sayfa arka plana geçince mikrofonu bırak (gizlilik + pil); öne gelince izin varsa sessizce yeniden aç
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') closeMic();
      else warmIfGranted();
    });
    global.addEventListener('pagehide', closeMic);
  }

  class Mic {
    /** opts: { onChunk(u8), onLevel(peak), onLive(), preroll: true } */
    constructor({ onChunk, onLevel, onLive, preroll = true } = {}) {
      this.onChunk = onChunk; this.onLevel = onLevel; this.onLive = onLive; this.preroll = preroll;
      this.active = false; this.id = 0;
    }
    async start() {
      if (this.active) return;
      this.active = true;
      await openMic();
      if (!this.active) return;
      if (eng.ctx && eng.ctx.state !== 'running') await Promise.race([eng.ctx.resume().catch(() => {}), new Promise((r) => setTimeout(r, 600))]);
      if (!this.active) return;
      this.id = ++eng.seq;
      eng.taps.set(this.id, this);
      eng.node.port.postMessage({ cmd: 'on', id: this.id, preroll: this.preroll });
      if (this.onLive) this.onLive();
    }
    /** Kapıyı kapat; son parça teslim edilince çözülür */
    stop() {
      this.active = false;
      if (!this.id || !eng.node || !eng.taps.has(this.id)) return Promise.resolve();
      const id = this.id; this.id = 0;
      return new Promise((resolve) => {
        this._done = resolve;
        eng.node.port.postMessage({ cmd: 'off', id });
        setTimeout(resolve, 250);
      });
    }
  }

  // ------------------------------------------------------------- Player (24 kHz PCM16)
  class Player {
    constructor({ onStart, onIdle } = {}) {
      this.onStart = onStart; this.onIdle = onIdle;
      this.next = 0; this.sources = new Set(); this.playing = false; this.idleTimer = null;
      this.pend = []; this.pendLen = 0; this.flushTimer = null; this.gen = 0; this.held = false; this.heldQ = [];
    }
    /** Çalmayı beklet (basılıyken) / bırak */
    hold(on) {
      this.held = !!on;
      if (!on && this.heldQ.length) {
        const q = this.heldQ; this.heldQ = [];
        q.forEach(([u8, r]) => this.enqueue(u8, r));
        this._flush();
      }
    }
    enqueue(u8, rate = 24000) {
      if (this.held) { this.heldQ.push([u8, rate]); return; }
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
      if (this.gen !== ctxGen) { this.gen = ctxGen; this.next = 0; }
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
      // Tampon: yeni akışta 180 ms önde başla; ağ boşluğu olursa 140 ms yeniden tamponla → kesik ses yok
      if (this.next < now + 0.03) this.next = now + (this.playing ? 0.14 : 0.18);
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
      this.pend = []; this.pendLen = 0; this.heldQ = []; this.held = false;
      this.sources.forEach((s) => { try { s.stop(); } catch { /* ignore */ } });
      this.sources.clear();
      this.next = 0;
      if (this.playing) { this.playing = false; if (this.onIdle) this.onIdle(); }
    }
    replay(chunks, rate = 24000) { this.stop(); (chunks || []).forEach((u8) => this.enqueue(u8, rate)); this._flush(); }
  }

  // ------------------------------------------------------------- Session
  class Session {
    constructor(opts) {
      this.o = opts; this.ws = null; this.state = 'idle'; this.ready = null; this.handle = null;
      this.variant = 0; this.lastUse = 0; this.vad = false;
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
      const body = Object.assign({}, (typeof this.o.body === 'function' ? this.o.body() : this.o.body) || {}, { variant: this.variant });
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
      const aad = setup.realtimeInputConfig && setup.realtimeInputConfig.automaticActivityDetection;
      this.vad = !aad || aad.disabled === false;
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
      // bazen "<speaker:Who>" gibi etiketler yazıya sızıyor → temizle
      const stripTag = (s) => String(s).replace(/<\/?[A-Za-z_]{2,20}(?::[^<>\s]{0,30})?>/g, '');
      if (sc.inputTranscription && sc.inputTranscription.text && this.o.onInput) { const tx = stripTag(sc.inputTranscription.text); if (tx.trim() || /\s/.test(tx)) this.o.onInput(tx); }
      if (sc.modelTurn && sc.modelTurn.parts) {
        for (const p of sc.modelTurn.parts) {
          if (p.inlineData && p.inlineData.data && this.o.onAudio) {
            const rate = Number((String(p.inlineData.mimeType || '').match(/rate=(\d+)/) || [])[1]) || 24000;
            this.o.onAudio(bytesFromB64(p.inlineData.data), rate);
          }
        }
      }
      if (sc.outputTranscription && sc.outputTranscription.text && this.o.onOutput) { const tx = stripTag(sc.outputTranscription.text); if (tx.trim() || /\s/.test(tx)) this.o.onOutput(tx); }
      if (sc.generationComplete && this.o.onGenerationComplete) this.o.onGenerationComplete();
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
    streamEnd() { return this.send({ realtimeInput: { audioStreamEnd: true } }); }
    sendText(text) { return this.send({ realtimeInput: { text } }); }
    sendVideo(b64) { return this.send({ realtimeInput: { video: { data: b64, mimeType: 'image/jpeg' } } }); }
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

  // ------------------------------------------------------------- Turn: bas-konuş turu (tüm sayfalarda ortak)
  // Gerçek ses (ardışık birkaç seviye ölçümü) algılanmadan Google'a HİÇBİR ŞEY gönderilmez → boş/kısa basışta
  // model "¿Qué?" / "Evet?" gibi uydurma cevap üretmez. Ses gelince ön tamponla birlikte akıtılır.
  const VOICE_LEVEL = 0.05; // tepe genliği eşiği
  const VOICE_HITS = 7;     // ~190 ms gerçek ses (dokunma tıkırtısı / kısa gürültü konuşma sayılmasın)
  class Turn {
    /** getSession: () => Session (hazır olunca), ready: bağlantı Promise'i */
    constructor(session, ready) {
      this.s = session; this.pending = []; this.hits = 0; this.voiced = false; this.started = false; this.sentAny = false;
      this.ready = Promise.resolve(ready).then(() => { this._try(); });
      this.ready.catch(() => {});
    }
    chunk(u8) {
      if (this.started && this.s.isOpen) { this.s.sendAudio(u8); return; }
      this.pending.push(u8);
      if (!this.voiced && this.pending.length > 14) this.pending.shift(); // sessizken yalnızca son ~1,4 sn
    }
    level(lv) {
      if (this.voiced) return;
      if (lv > VOICE_LEVEL) { if (++this.hits >= VOICE_HITS) { this.voiced = true; this._try(); } } else if (this.hits > 0) this.hits -= 1;
    }
    _try() {
      if (!this.voiced || this.started || !this.s.isOpen) return;
      this.started = true;
      if (!this.s.vad) this.s.activityStart();
      this.s._activity = true;
      const q = this.pending; this.pending = [];
      q.forEach((c) => this.s.sendAudio(c));
    }
    /** Bırakıldı. Ses yoksa false (hiçbir şey gönderilmedi); varsa konuşmayı bitirir ve true döner */
    async end() {
      await this.ready;
      this._try();
      if (!this.voiced || !this.started || !this.s.isOpen) { this.pending = []; this.s._activity = false; return false; }
      const q = this.pending; this.pending = []; q.forEach((c) => this.s.sendAudio(c));
      if (this.s.vad) { for (let i = 0; i < 3; i++) this.s.sendAudio(new Uint8Array(3200)); this.s.streamEnd(); } else this.s.activityEnd();
      this.s._activity = false;
      return true;
    }
  }

  global.LiveAudio = { unlock, audioCtx, micReady, micPermission, openMic, closeMic, warmIfGranted, Mic, Player, Session, Turn, b64FromBytes, bytesFromB64 };
  if (typeof document !== 'undefined' && navigator.mediaDevices) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', warmIfGranted);
    else warmIfGranted();
  }
})(typeof window !== 'undefined' ? window : globalThis);

/* Canlı tercüman — Gemini Live Translate (konuşurken çevirir, klasik STT/TTS yok)
 *
 * Çeviri sayfası (translate.html): iki bas-konuş düğmesi; bastığın dilden diğerine anında sesli çeviri.
 * Karşılıklı (live-talk.html): eller serbest — mikrofon açık, kim hangi dilde konuşursa diğer dile çevrilir.
 */
(function () {
  'use strict';

  const LANGS = [
    { code: 'tr', name: 'Türkçe', flag: '🇹🇷' }, { code: 'en', name: 'English', flag: '🇬🇧' },
    { code: 'de', name: 'Deutsch', flag: '🇩🇪' }, { code: 'fr', name: 'Français', flag: '🇫🇷' },
    { code: 'es', name: 'Español', flag: '🇪🇸' }, { code: 'it', name: 'Italiano', flag: '🇮🇹' },
    { code: 'ru', name: 'Русский', flag: '🇷🇺' }, { code: 'ar', name: 'العربية', flag: '🇸🇦' },
    { code: 'zh', name: '中文', flag: '🇨🇳' }, { code: 'ka', name: 'ქართული', flag: '🇬🇪' },
  ];
  const HOLD = { tr: 'Basılı tut, konuş', en: 'Hold to speak', de: 'Gedrückt halten', fr: 'Maintenir pour parler',
    es: 'Mantén para hablar', it: 'Tieni premuto', ru: 'Удерживай', ar: 'اضغط مطولاً', zh: '按住说话', ka: 'დააჭირე და ილაპარაკე' };
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const lang = (c) => LANGS.find((l) => l.code === c) || LANGS[0];
  const PAGE = $('ltToggle') ? 'talk' : 'translate';
  const KEY = PAGE === 'talk' ? 'lt_langs_v2' : 'tr_langs_v2';
  const SILENCE = new Uint8Array(3200); // 100 ms @16 kHz

  let prefs = { my: 'tr', other: 'en' };
  try { prefs = Object.assign(prefs, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch { /* ignore */ }
  const savePrefs = () => { try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* ignore */ } };

  const ids = PAGE === 'talk'
    ? { my: 'ltMyLang', other: 'ltOtherLang', swap: 'ltSwapBtn', status: 'ltStatusText', dot: 'ltStatusDot', err: 'ltErrorBox', msgs: 'ltMessages', clear: 'ltClearBtn' }
    : { my: 'myLang', other: 'otherLang', swap: 'swapBtn', status: 'statusText', dot: 'statusDot', err: 'errorBox', msgs: 'messages', clear: 'clearBtn' };

  // ---------------------------------------------------------------- state
  const player = new LiveAudio.Player({ onStart: () => setStatus('Çeviri seslendiriliyor…', true), onIdle: () => idle() });
  const sessions = {}; // dir → Session   (toOther: konuşan = ben, toMine: konuşan = karşı taraf)
  const bubbles = []; // {dir, from, to, orig, trans, visible, done, okunus, audio:[]}
  const cur = {}; // dir → active bubble
  let mic = null;
  let holdDir = null;
  let handsFree = false;
  let pending = []; // audio buffered while connecting (hold mode)

  function setStatus(t, live = false) { $(ids.status).textContent = t; $(ids.dot).classList.toggle('active', !!live); }
  function idle() {
    if (holdDir || handsFree) return;
    setStatus(PAGE === 'talk' ? 'Başlat\'a bas, sırayla konuşun' : 'Hangi dilde konuşacaksan o düğmeye basılı tut', false);
  }
  function showErr(t) { const b = $(ids.err); if (!b) return; b.textContent = t; b.classList.toggle('hidden', !t); }

  function targetOf(dir) { return dir === 'toOther' ? prefs.other : prefs.my; }
  function sourceOf(dir) { return dir === 'toOther' ? prefs.my : prefs.other; }

  function session(dir) {
    if (sessions[dir]) return sessions[dir];
    const s = new LiveAudio.Session({
      body: { kind: 'translate', target: targetOf(dir) },
      onInput: (t) => { const b = bubbleFor(dir); b.orig = (b.orig + t).replace(/\s+/g, ' '); touch(dir); },
      onOutput: (t) => { const b = bubbleFor(dir); b.trans = (b.trans + t).replace(/\s+/g, ' '); b.visible = true; touch(dir); },
      onAudio: (u8, rate) => { const b = bubbleFor(dir); b.visible = true; b.audio.push(u8); b.rate = rate; player.enqueue(u8, rate); touch(dir); },
      onTurnComplete: () => finalize(dir),
      onState: (st, info) => {
        if (st === 'error') showErr(String(info || 'Canlı bağlantı kurulamadı'));
        if ((st === 'closed' || st === 'goaway') && document.visibilityState === 'visible') setTimeout(() => s.connect().catch(() => {}), 1500);
      },
    });
    sessions[dir] = s;
    return s;
  }
  function closeAll() {
    Object.keys(sessions).forEach((k) => { try { sessions[k].close(); } catch { /* ignore */ } delete sessions[k]; });
  }

  function bubbleFor(dir) {
    if (!cur[dir]) {
      cur[dir] = { dir, from: sourceOf(dir), to: targetOf(dir), orig: '', trans: '', visible: false, done: false, okunus: '', audio: [], rate: 24000, t: Date.now() };
      bubbles.push(cur[dir]);
    }
    return cur[dir];
  }
  const finTimers = {};
  function touch(dir) {
    clearTimeout(finTimers[dir]);
    finTimers[dir] = setTimeout(() => finalize(dir), 1800);
    renderSoon();
  }
  async function finalize(dir) {
    clearTimeout(finTimers[dir]);
    const b = cur[dir];
    if (!b) return;
    cur[dir] = null;
    if (!b.visible || !b.trans.trim()) { const i = bubbles.indexOf(b); if (i >= 0) bubbles.splice(i, 1); renderSoon(); return; }
    b.done = true;
    renderSoon();
    if (b.to !== 'tr') {
      try {
        const r = await fetch('/api/pronounce?' + new URLSearchParams({ q: b.trans.trim().slice(0, 400), lang: b.to }));
        const d = await r.json();
        b.okunus = d.phonetic || '';
        renderSoon();
      } catch { /* ignore */ }
    }
  }

  let rp = false;
  let lastSig = '';
  function sig() { return bubbles.filter((b) => b.visible).map((b) => `${bubbles.indexOf(b)}:${b.done ? 1 : 0}:${b.okunus ? 1 : 0}`).join('|'); }
  function renderSoon() {
    if (rp) return; rp = true;
    requestAnimationFrame(() => {
      rp = false;
      if (sig() !== lastSig) { render(); return; }
      // yapı aynı → yalnızca akan metni yerinde güncelle (titreme yok)
      const el = $(ids.msgs);
      bubbles.forEach((b, i) => {
        if (!b.visible) return;
        const a = el.querySelector(`[data-b="${i}"]`);
        if (!a) return;
        const o = a.querySelector('.bubble-original'); const t = a.querySelector('.bubble-translated');
        if (o && o.textContent !== (b.orig || '…')) o.textContent = b.orig || '…';
        if (t && t.textContent !== b.trans) t.textContent = b.trans;
      });
    });
  }
  function render() {
    lastSig = sig();
    const el = $(ids.msgs);
    const list = bubbles.filter((b) => b.visible);
    if ($(ids.clear)) $(ids.clear).classList.toggle('hidden', !list.length);
    if (!list.length) {
      el.innerHTML = `<div class="empty-state"><div class="empty-icon"></div>
        <h2>${PAGE === 'talk' ? 'Konuşun, anında çevireyim' : 'Basılı tut ve konuş'}</h2>
        <p>${PAGE === 'talk' ? 'Başlat\'a bas, telefonu ortaya koy. Kim hangi dilde konuşursa diğer dile sesli çevrilir — cümle bitmeden başlar.' : 'Konuşmaya başladığın an çeviri sesli akmaya başlar — cümlenin bitmesini beklemez.'}</p></div>`;
      return;
    }
    el.innerHTML = list.slice().reverse().map((b) => {
      const f = lang(b.from), t = lang(b.to);
      const i = bubbles.indexOf(b);
      return `<article class="bubble ${b.dir === 'toOther' ? 'me' : 'other'} ${b.done ? '' : 'is-live'}" data-b="${i}">
        <div class="bubble-label">${f.flag} ${esc(f.name)}</div>
        <div class="bubble-original">${esc(b.orig || '…')}</div>
        <div class="bubble-divider"></div>
        <div class="bubble-label">${t.flag} ${esc(t.name)}</div>
        <div class="bubble-translated"${b.to === 'ar' ? ' dir="rtl"' : ''}>${esc(b.trans)}</div>
        ${b.okunus ? `<div class="bubble-phonetic"><b>Okunuş</b> · ${esc(b.okunus)}</div>` : ''}
        ${b.done && b.audio.length ? `<button type="button" class="replay-btn" data-replay="${i}">▶ Tekrar dinle</button>` : ''}
      </article>`;
    }).join('');
  }
  $(ids.msgs).addEventListener('click', (e) => {
    const r = e.target.closest('[data-replay]');
    if (!r) return;
    LiveAudio.unlock();
    const b = bubbles[Number(r.dataset.replay)];
    if (b) player.replay(b.audio, b.rate);
  });

  // ---------------------------------------------------------------- languages
  function fillSelects() {
    [$(ids.my), $(ids.other)].forEach((sel) => {
      sel.innerHTML = LANGS.map((l) => `<option value="${l.code}">${l.flag} ${esc(l.name)}</option>`).join('');
    });
    $(ids.my).value = prefs.my; $(ids.other).value = prefs.other;
    syncLabels();
  }
  function syncLabels() {
    const m = lang(prefs.my), o = lang(prefs.other);
    if (PAGE === 'translate') {
      $('micTitleMy').textContent = `${m.flag} ${m.name}`; $('micActionMy').textContent = HOLD[m.code] || 'Basılı tut';
      $('micTitleOther').textContent = `${o.flag} ${o.name}`; $('micActionOther').textContent = HOLD[o.code] || 'Basılı tut';
    } else {
      $('ltPair').textContent = `${m.flag} ${m.name}  ⇄  ${o.flag} ${o.name}`;
    }
  }
  function onLangChange() {
    if (prefs.my === prefs.other) prefs.other = prefs.my === 'en' ? 'tr' : 'en';
    savePrefs(); stopAll(); closeAll(); fillSelects(); preconnect();
  }
  $(ids.my).addEventListener('change', (e) => { prefs.my = e.target.value; onLangChange(); });
  $(ids.other).addEventListener('change', (e) => { prefs.other = e.target.value; onLangChange(); });
  $(ids.swap).addEventListener('click', () => { [prefs.my, prefs.other] = [prefs.other, prefs.my]; onLangChange(); });
  if ($(ids.clear)) $(ids.clear).addEventListener('click', () => { bubbles.length = 0; render(); });

  function preconnect() {
    // Bağlantıyı önceden kur → ilk konuşmada bekleme olmasın
    ['toOther', 'toMine'].forEach((d) => { session(d).connect().catch(() => {}); });
  }

  // ---------------------------------------------------------------- hold-to-talk (Çeviri)
  async function holdStart(btn, dir) {
    if (holdDir) return;
    LiveAudio.unlock();
    showErr('');
    holdDir = dir; pending = [];
    btn.classList.add('arming');
    setStatus('Mikrofon açılıyor…', true);
    const s = session(dir);
    const ready = s.connect().then(() => { const q = pending; pending = []; q.forEach((c) => s.sendAudio(c)); });
    mic = new LiveAudio.Mic({
      onChunk: (u8) => { if (s.isOpen && !pending.length) s.sendAudio(u8); else pending.push(u8); },
      onLive: () => { btn.classList.remove('arming'); btn.classList.add('recording'); setStatus(`Konuş — ${lang(sourceOf(dir)).name}`, true); },
      onLevel: (lv) => { btn.style.setProperty('--lv', Math.min(1, lv * 3).toFixed(2)); },
    });
    try { await mic.start(); } catch (e) { holdAbort(btn, e && e.name === 'NotAllowedError' ? 'Mikrofon izni gerekli' : 'Mikrofon açılamadı'); return; }
    ready.catch((e) => holdAbort(btn, e.message || 'Canlı bağlantı kurulamadı'));
  }
  function holdAbort(btn, msg) {
    holdDir = null; if (mic) { mic.stop(); mic = null; } btn.classList.remove('recording', 'arming'); showErr(msg); idle();
  }
  function holdEnd(btn) {
    if (!holdDir) return;
    const dir = holdDir; holdDir = null;
    btn.classList.remove('recording', 'arming');
    btn.style.removeProperty('--lv');
    if (mic) { mic.stop(); mic = null; }
    const s = sessions[dir];
    // kısa sessizlik + akış sonu → son kelimeler de hemen çevrilsin
    setTimeout(() => {
      if (!s || !s.isOpen) return;
      for (let i = 0; i < 8; i++) s.sendAudio(SILENCE);
      s.send({ realtimeInput: { audioStreamEnd: true } });
    }, 120);
    if (!player.playing) setStatus('Çeviriliyor…', true);
  }
  function bindHold(btn, dirFn) {
    if (!btn) return;
    let touchUsed = false;
    const down = (e) => { e.preventDefault(); void holdStart(btn, dirFn()); };
    const up = (e) => { e.preventDefault(); holdEnd(btn); };
    btn.addEventListener('contextmenu', (e) => e.preventDefault());
    btn.addEventListener('touchstart', (e) => { touchUsed = true; down(e); }, { passive: false });
    btn.addEventListener('touchend', up, { passive: false });
    btn.addEventListener('touchcancel', up, { passive: false });
    btn.addEventListener('mousedown', (e) => { if (!touchUsed) down(e); });
    btn.addEventListener('mouseup', (e) => { if (!touchUsed) up(e); });
    btn.addEventListener('mouseleave', (e) => { if (!touchUsed && holdDir) up(e); });
  }

  // ---------------------------------------------------------------- hands-free (Karşılıklı)
  async function startHandsFree() {
    LiveAudio.unlock();
    showErr('');
    handsFree = true;
    $('ltToggle').classList.add('recording');
    $('ltToggleText').textContent = 'Durdur';
    setStatus('Bağlanıyor…', true);
    const a = session('toOther'), b = session('toMine');
    mic = new LiveAudio.Mic({
      onChunk: (u8) => {
        // Çeviri çalarken mikrofonu sustur → kendi sesini tekrar çevirmesin
        const chunk = player.playing ? SILENCE : u8;
        if (a.isOpen) a.sendAudio(chunk);
        if (b.isOpen) b.sendAudio(chunk);
      },
      onLevel: (lv) => { const m = $('ltMeter'); if (m) m.style.transform = `scale(${1 + Math.min(0.6, lv * 2.5)})`; },
    });
    try {
      await Promise.all([mic.start(), a.connect(), b.connect()]);
      setStatus('Dinliyorum — konuşabilirsiniz', true);
    } catch (e) {
      stopHandsFree();
      showErr(e && e.name === 'NotAllowedError' ? 'Mikrofon izni gerekli' : (e.message || 'Canlı bağlantı kurulamadı'));
    }
  }
  function stopHandsFree() {
    handsFree = false;
    if (mic) { mic.stop(); mic = null; }
    const t = $('ltToggle'); if (t) t.classList.remove('recording');
    const tt = $('ltToggleText'); if (tt) tt.textContent = 'Başlat';
    Object.values(sessions).forEach((s) => { if (s.isOpen) s.send({ realtimeInput: { audioStreamEnd: true } }); });
    idle();
  }
  function stopAll() { if (handsFree) stopHandsFree(); if (mic) { mic.stop(); mic = null; } holdDir = null; player.stop(); }

  // ---------------------------------------------------------------- typed text (Çeviri) — metin için klasik çeviri
  async function translateTyped() {
    const inp = $('translateTextInput');
    const text = (inp.value || '').trim();
    if (!text) return;
    inp.value = '';
    LiveAudio.unlock();
    setStatus('Çeviriliyor…', true);
    try {
      const r = await fetch('/api/translate?' + new URLSearchParams({ q: text, from: prefs.my, to: prefs.other, my: prefs.my, other: prefs.other }));
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Çeviri başarısız');
      const b = { dir: d.from === prefs.my ? 'toOther' : 'toMine', from: d.from, to: d.to, orig: text, trans: d.text, visible: true, done: true, okunus: '', audio: [], rate: 24000 };
      bubbles.push(b); render();
      const au = new Audio('/api/tts?' + new URLSearchParams({ q: d.text.slice(0, 400), tl: d.to }));
      au.play().catch(() => {});
      if (d.to !== 'tr') {
        const p = await (await fetch('/api/pronounce?' + new URLSearchParams({ q: d.text.slice(0, 400), lang: d.to }))).json();
        b.okunus = p.phonetic || ''; render();
      }
      idle();
    } catch (e) { showErr(e.message || 'Çeviri başarısız'); idle(); }
  }

  // ---------------------------------------------------------------- boot
  fillSelects();
  render();
  idle();
  if (!(window.WebSocket && window.AudioWorkletNode && navigator.mediaDevices)) {
    showErr('Bu tarayıcı canlı sesi desteklemiyor — Safari/Chrome güncel sürüm gerekir.');
  }
  if (PAGE === 'translate') {
    bindHold($('micBtnMy'), () => 'toOther');
    bindHold($('micBtnOther'), () => 'toMine');
    $('translateSendBtn').addEventListener('click', () => void translateTyped());
    $('translateTextInput').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); void translateTyped(); } });
  } else {
    $('ltToggle').addEventListener('click', () => { if (handsFree) stopHandsFree(); else void startHandsFree(); });
  }
  preconnect();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') stopAll();
    else preconnect();
  });
})();

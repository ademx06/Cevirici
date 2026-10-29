/* Eğitim — yapay zekâ öğretmen istemcisi (v3)
 * Tek istek/tur · seviye takibi · kelime & düzeltme kaydı · anında seslendirme
 */
(function () {
  'use strict';

  // ------------------------------------------------------------------ data
  const LANGS = [
    { code: 'en', flag: '🇬🇧', name: 'English', tr: 'İngilizce' },
    { code: 'de', flag: '🇩🇪', name: 'Deutsch', tr: 'Almanca' },
    { code: 'fr', flag: '🇫🇷', name: 'Français', tr: 'Fransızca' },
    { code: 'es', flag: '🇪🇸', name: 'Español', tr: 'İspanyolca' },
    { code: 'it', flag: '🇮🇹', name: 'Italiano', tr: 'İtalyanca' },
    { code: 'ru', flag: '🇷🇺', name: 'Русский', tr: 'Rusça' },
    { code: 'ar', flag: '🇸🇦', name: 'العربية', tr: 'Arapça', rtl: true },
    { code: 'zh', flag: '🇨🇳', name: '中文', tr: 'Çince' },
    { code: 'ka', flag: '🇬🇪', name: 'ქართული', tr: 'Gürcüce' },
    { code: 'id', flag: '🇮🇩', name: 'Bahasa Indonesia', tr: 'Endonezce' },
  ];
  const LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2'];
  const LEVEL_TR = { A1: 'Başlangıç', A2: 'Temel', B1: 'Orta', B2: 'Orta üstü', C1: 'İleri', C2: 'Ustalık' };
  const ACCENTS = {
    en: [['en-US', 'Amerikan'], ['en-GB', 'İngiliz'], ['en-AU', 'Avustralya'], ['en-IE', 'İrlanda']],
    es: [['es-ES', 'İspanya'], ['es-MX', 'Meksika']],
    fr: [['fr-FR', 'Fransa'], ['fr-CA', 'Kanada']],
    de: [['de-DE', 'Almanya'], ['de-AT', 'Avusturya'], ['de-CH', 'İsviçre']],
    ar: [['ar-SA', 'Suudi Arabistan'], ['ar-EG', 'Mısır']],
    zh: [['zh-CN', 'Mandarin (Çin)'], ['zh-TW', 'Tayvan']],
  };
  const SCENARIOS = [
    ['Günlük hayat', [['friend', 'Arkadaşla sohbet'], ['daily_chat', 'Günlük sohbet'], ['meet_new', 'Yeni biriyle tanışma'], ['neighbor', 'Komşuyla konuşma'], ['phone_call', 'Telefonda konuşma'], ['weekend_plans', 'Hafta sonu planı'], ['hobbies', 'Hobiler'], ['sports', 'Spor'], ['movies', 'Film ve dizi'], ['music', 'Müzik'], ['food_talk', 'Yemek sohbeti'], ['shopping_chat', 'Alışveriş sohbeti'], ['teacher', 'Sınıf öğretmeni']]],
    ['Seyahat', [['airport', 'Havalimanı'], ['flight', 'Uçakta'], ['passport_control', 'Pasaport kontrolü'], ['taxi', 'Taksi'], ['hotel', 'Otel check-in'], ['hotel_checkout', 'Otel check-out'], ['hotel_problem', 'Otel problemi'], ['restaurant', 'Restoran'], ['cafe', 'Kafe'], ['market', 'Market'], ['directions', 'Yol tarifi'], ['car_rental', 'Araba kiralama'], ['tour', 'Tur rezervasyonu'], ['shop', 'Mağaza']]],
    ['İş', [['interview', 'İş görüşmesi'], ['colleagues', 'İş arkadaşlarıyla sohbet'], ['meeting', 'Toplantı'], ['work_phone', 'İş telefonu'], ['customer', 'Müşteri görüşmesi'], ['boss', 'Patronla görüşme'], ['salary', 'Maaş görüşmesi']]],
    ['Sosyal', [['make_friends', 'Yeni arkadaş edinme'], ['invite', 'Birini davet etme'], ['ask_advice', 'Tavsiye isteme'], ['apology', 'Özür dileme'], ['thanks', 'Teşekkür etme']]],
    ['Gerçek hayat', [['doctor', 'Doktor'], ['pharmacy', 'Eczane'], ['bank', 'Banka'], ['post_office', 'Postane'], ['rent_apartment', 'Ev kiralama'], ['tech_support', 'Teknik destek']]],
  ];
  const SCENARIO_NAME = Object.fromEntries(SCENARIOS.flatMap(([, items]) => items));

  const PROFILE_KEY = 'edu_v3_profile';
  const chatKey = (lang) => `edu_v3_chat_${lang}`;
  const TURN_TIMEOUT = 40000;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  const langOf = (c) => LANGS.find((l) => l.code === c) || LANGS[0];
  const ICON = {
    play: '<svg viewBox="0 0 24 24"><path d="M11 5L6 9H3v6h3l5 4zM15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>',
    slow: '<svg viewBox="0 0 24 24"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2M9 2h6"/></svg>',
    fill: '<svg viewBox="0 0 24 24"><path d="M7 4.5v15l13-7.5z"/></svg>',
  };

  // ------------------------------------------------------------------ storage
  function safeGet(key, fallback) {
    try { const v = JSON.parse(localStorage.getItem(key)); return v ?? fallback; } catch { return fallback; }
  }
  function safeSet(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch { /* storage full / private mode */ }
  }

  function defaultProfile() {
    const p = {
      lang: 'en', levels: {}, autoLevel: true, scenario: '', slow: false,
      showOkunus: true, showTr: true, autoSpeak: true, accents: {}, goalMin: 10,
      days: {}, streak: 0, lastDay: '', ema: {}, sinceChange: {}, recent: {},
      words: {}, mistakes: {}, turns: 0, correct: 0,
    };
    // eski sürümden seviye/dil taşı
    const old = safeGet('edu_profile_v2', null);
    if (old && typeof old === 'object') {
      const lg = String(old.targetLang || 'en');
      if (LANGS.some((l) => l.code === lg)) p.lang = lg;
      if (LEVELS.includes(old.currentLevel)) p.levels[p.lang] = old.currentLevel;
    }
    return p;
  }
  const P = Object.assign(defaultProfile(), safeGet(PROFILE_KEY, {}));
  ['levels', 'accents', 'days', 'ema', 'sinceChange', 'recent', 'words', 'mistakes'].forEach((k) => {
    if (!P[k] || typeof P[k] !== 'object' || Array.isArray(P[k])) P[k] = {};
  });
  if (!LANGS.some((l) => l.code === P.lang)) P.lang = 'en';
  const saveProfile = () => safeSet(PROFILE_KEY, P);

  const S = {
    msgs: [],
    busy: false,
    mode: 'speak',
    lastActive: Date.now(),
    holdActive: false, holdGen: 0, recorder: null, stream: null, chunks: [],
  };

  const level = () => (LEVELS.includes(P.levels[P.lang]) ? P.levels[P.lang] : 'A1');
  const str = (v, n = 600) => (typeof v === 'string' ? v : v == null ? '' : String(v)).slice(0, n);
  function cleanMsg(m) {
    if (!m || typeof m !== 'object') return null;
    if (m.role === 'user') return m.text ? { role: 'user', text: str(m.text, 500), okunus: str(m.okunus, 600), mode: m.mode === 'help' ? 'help' : 'speak', t: Number(m.t) || 0 } : null;
    if (m.role !== 'tutor') return null;
    const fix = m.fix && typeof m.fix === 'object' && m.fix.fixed
      ? { status: m.fix.status === 'better' ? 'better' : 'fix', fixed: str(m.fix.fixed), okunus: str(m.fix.okunus), explain_tr: str(m.fix.explain_tr), how_tr: str(m.fix.how_tr) } : null;
    const arr = (v) => (Array.isArray(v) ? v.filter((x) => x && typeof x === 'object') : []);
    const out = {
      role: 'tutor', lang: str(m.lang, 5) || P.lang, mode: str(m.mode, 10), you: str(m.you, 500),
      reply: str(m.reply), reply_tr: str(m.reply_tr), okunus: str(m.okunus, 900), fix,
      examples: arr(m.examples).filter((e) => e.text).map((e) => ({ text: str(e.text), tr: str(e.tr), okunus: str(e.okunus) })),
      explain_tr: str(m.explain_tr), words: arr(m.words).filter((w) => w.word).map((w) => ({ word: str(w.word, 60), tr: str(w.tr, 80) })),
      speak: arr(m.speak).filter((i) => i.text).map((i) => ({ text: str(i.text, 480), lang: str(i.lang, 5) })),
      provider: str(m.provider, 10), t: Number(m.t) || 0,
      reply_target: str(m.reply_target), checked: !!m.checked, unclear: !!m.unclear,
      segments: arr(m.segments).filter((g) => g.text).map((g) => ({ text: str(g.text, 400), lang: str(g.lang, 5) })),
    };
    return out.reply || out.examples.length ? out : null;
  }
  const loadChat = () => { const c = safeGet(chatKey(P.lang), []); return Array.isArray(c) ? c.map(cleanMsg).filter(Boolean).slice(-60) : []; };
  try { ['edu_chat_v3', 'edu_history_v2'].forEach((k) => localStorage.removeItem(k)); } catch { /* ignore */ }
  // sohbetin seviyesi/senaryosu: arşivde sohbetin kendi seviyesi görünsün (sonradan seçilen seviye değil)
  const saveChat = () => {
    try { if (S.msgs.some((m) => m.role === 'user' && m.text)) safeSet(`edu_v3_meta_${P.lang}`, { level: level(), scenario: P.scenario || '' }); } catch { /* ignore */ }
    saveChat0();
  };
  // canlı öğretmen sesi kalıcı (IndexedDB): sohbet değişince/yenilenince "Dinle" aynı sesle çalar
  const audDb = () => new Promise((res, rej) => { const q = indexedDB.open('edu_v3_audio', 1); q.onupgradeneeded = () => q.result.createObjectStore('a'); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
  async function audPut(key, val) { try { const db = await audDb(); db.transaction('a', 'readwrite').objectStore('a').put(val, key); } catch { /* ignore */ } }
  async function audGet(key) { try { const db = await audDb(); return await new Promise((r) => { const q = db.transaction('a').objectStore('a').get(key); q.onsuccess = () => r(q.result || null); q.onerror = () => r(null); }); } catch { return null; } }
  function saveLiveAudio(m) { try { if (m && m.t && m._audio && m._audio.length) void audPut(m.t, { rate: m._rate || 24000, blob: new Blob(m._audio) }); } catch { /* ignore */ } }
  async function audGc() {
    try {
      const keep = new Set();
      for (let i = 0; i < localStorage.length; i += 1) {
        const k = localStorage.key(i); if (!/^edu_v3_(chat|archive)_/.test(k)) continue;
        const v = JSON.parse(localStorage.getItem(k) || '[]');
        (Array.isArray(v) ? v : []).forEach((x) => { if (x && x.msgs) x.msgs.forEach((mm) => keep.add(mm.t)); else if (x) keep.add(x.t); });
      }
      const db = await audDb(); const os = db.transaction('a', 'readwrite').objectStore('a');
      os.openCursor().onsuccess = (e) => { const c = e.target.result; if (!c) return; if (!keep.has(c.key)) c.delete(); c.continue(); };
    } catch { /* ignore */ }
  }
  setTimeout(audGc, 8000);
  const saveChat0 = () => safeSet(chatKey(P.lang), S.msgs.slice(-60).map((m) => {
    const { _audio, _rate, _final, pending, live, ...rest } = m; // eslint-disable-line no-unused-vars
    return rest;
  }));

  // ---- sohbet arşivi: yeni sohbet / senaryo değişiminde eski sohbet kaybolmaz, listeden açılır/silinir
  const archKey = (lang) => `edu_v3_archive_${lang}`;
  const loadArch = () => { const a = safeGet(archKey(P.lang), []); return Array.isArray(a) ? a : []; };
  function archiveCurrent(scn) {
    try {
      if (!S.msgs.some((m) => m.role === 'user' && m.text && m.text.trim())) return;
      const msgs = S.msgs.slice(-60).filter((m) => !m.pending).map((m) => { const { _audio, _rate, _final, pending, live, ...rest } = m; return rest; }); // eslint-disable-line no-unused-vars
      const a = loadArch();
      const mt = safeGet(`edu_v3_meta_${P.lang}`, null) || {};
      a.unshift({ id: Date.now(), ts: Date.now(), scenario: mt.scenario !== undefined ? mt.scenario : (scn === undefined ? (P.scenario || '') : (scn || '')), level: LEVELS.includes(mt.level) ? mt.level : level(), msgs });
      safeSet(archKey(P.lang), a.slice(0, 20));
    } catch { /* ignore */ }
  }
  function renderChatList() {
    const box = $('chatList'); if (!box) return;
    const a = loadArch();
    box.textContent = '';
    if (!a.length) { box.hidden = true; return; }
    box.hidden = false;
    const h = document.createElement('div'); h.className = 'chat-list-h'; h.textContent = 'Önceki sohbetler'; box.appendChild(h);
    a.forEach((c) => {
      const row = document.createElement('div'); row.className = 'chat-item';
      const info = document.createElement('div'); info.className = 'chat-info';
      const first = (c.msgs.find((m) => m.role === 'user' && m.text) || {}).text || '';
      const when = new Date(c.ts).toLocaleString('tr-TR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
      const t1 = document.createElement('b'); t1.textContent = `${SCENARIO_NAME[c.scenario] || 'Serbest sohbet'} · ${c.level || ''}`;
      const t2 = document.createElement('small'); t2.textContent = `${when} · ${first.slice(0, 40)}`;
      info.append(t1, t2);
      const open = document.createElement('button'); open.type = 'button'; open.className = 'btn'; open.textContent = 'Aç';
      open.addEventListener('click', () => openArchived(c.id));
      const del = document.createElement('button'); del.type = 'button'; del.className = 'btn btn-danger'; del.textContent = 'Sil';
      del.addEventListener('click', () => { if (!window.confirm('Bu sohbet silinsin mi?')) return; safeSet(archKey(P.lang), loadArch().filter((x) => x.id !== c.id)); renderChatList(); });
      row.append(info, open, del); box.appendChild(row);
    });
  }
  function openArchived(id) {
    const a = loadArch(); const c = a.find((x) => x.id === id); if (!c) return;
    archiveCurrent();
    safeSet(archKey(P.lang), loadArch().filter((x) => x.id !== id));
    P.scenario = c.scenario || '';
    if (LEVELS.includes(c.level)) { P.levels[P.lang] = c.level; P.sinceChange[P.lang] = 0; P.ema[P.lang] = LEVELS.indexOf(c.level) + 1; }
    saveProfile();
    S.msgs = (c.msgs || []).map(cleanMsg).filter(Boolean);
    saveChat();
    closeSheet('settingsSheet');
    switchConversation();
  }

  // ------------------------------------------------------------------ status
  let statusTimer = null;
  function setStatus(text, live = false, sticky = false) {
    $('statusText').textContent = text;
    $('statusDot').classList.toggle('active', !!live);
    clearTimeout(statusTimer);
    if (!sticky && !live) statusTimer = setTimeout(() => idleStatus(), 5000);
  }
  function idleStatus() {
    if (S.busy) return;
    $('statusText').textContent = `${langOf(P.lang).name} konuş · takılırsan Yardım`;
    $('statusDot').classList.remove('active');
  }

  // ------------------------------------------------------------------ audio (instant)
  const audio = new Audio();
  audio.setAttribute('playsinline', '');
  audio.preload = 'auto';
  let audioUnlocked = false;
  function unlockAudio() {
    if (audioUnlocked) return;
    audioUnlocked = true;
    try {
      audio.src = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAZGF0YQQAAAA=';
      const p = audio.play();
      if (p && p.catch) p.catch(() => { audioUnlocked = false; });
    } catch { audioUnlocked = false; }
  }
  document.addEventListener('touchstart', unlockAudio, { passive: true, capture: true });
  document.addEventListener('mousedown', unlockAudio, { capture: true });

  const ttsCache = new Map(); // key -> Promise<objectURL>
  function ttsUrl(text, lang, slow) {
    const q = new URLSearchParams({ q: text.slice(0, 2500), tl: lang });
    if (slow) q.set('slow', '1');
    const acc = P.accents[lang];
    if (acc) q.set('voice', acc);
    return `/api/tts?${q}`;
  }
  function fetchTts(text, lang, slow) {
    const key = `${lang}|${slow ? 1 : 0}|${P.accents[lang] || ''}|${text}`;
    if (ttsCache.has(key)) return ttsCache.get(key);
    const pr = fetch(ttsUrl(text, lang, slow))
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => (b && b.size > 100 ? URL.createObjectURL(b) : null))
      .catch(() => null);
    ttsCache.set(key, pr);
    pr.then((u) => { if (!u) ttsCache.delete(key); });
    if (ttsCache.size > 80) ttsCache.delete(ttsCache.keys().next().value);
    return pr;
  }
  let playToken = 0;
  let playingBtn = null;
  function stopAudio() {
    playToken += 1;
    try { audio.pause(); } catch { /* ignore */ }
    if (playingBtn) playingBtn.classList.remove('playing');
    playingBtn = null;
  }
  function playUrl(url, token) {
    return new Promise((resolve) => {
      if (!url || token !== playToken) return resolve();
      const done = () => { audio.onended = null; audio.onerror = null; resolve(); };
      audio.onended = done;
      audio.onerror = done;
      audio.src = url;
      const p = audio.play();
      if (p && p.catch) p.catch(done);
    });
  }
  /** items: [{text, lang}] — all fetched in parallel right away, played in order. */
  async function speak(items, { slow = P.slow, btn = null } = {}) {
    const list = (items || []).filter((i) => i && i.text);
    if (!list.length) return;
    stopAudio();
    const token = playToken;
    const urls = list.map((i) => fetchTts(i.text, i.lang || P.lang, slow));
    if (btn) { playingBtn = btn; btn.classList.add('playing'); }
    for (const u of urls) {
      if (token !== playToken) break;
      await playUrl(await u, token);
    }
    if (token === playToken && btn) btn.classList.remove('playing');
  }

  // ------------------------------------------------------------------ rendering
  function okunusLine(text) {
    return P.showOkunus && text ? `<p class="t-okunus">${esc(text)}</p>` : '';
  }
  function trLine(text) {
    return P.showTr && text ? `<p class="t-tr">${esc(text)}</p>` : '';
  }
  function playBtns(idx, part, label = 'Dinle') {
    return `<button type="button" class="t-btn" data-play="${idx}" data-part="${part}">${ICON.play}${label}</button>`
      + `<button type="button" class="t-btn" data-play="${idx}" data-part="${part}" data-slow="1">${ICON.slow}Yavaş</button>`;
  }

  function renderTutor(m, idx) {
    const lg = langOf(m.lang || P.lang);
    const dir = lg.rtl ? ' dir="rtl"' : '';
    let html = '';
    if (m.fix && m.fix.fixed) {
      const better = m.fix.status === 'better';
      html += `<div class="fix ${better ? 'is-better' : ''}">
        <div class="fix-head">${better ? 'Daha doğal söyleyiş' : 'Doğrusu'}</div>
        ${m.you ? `<p class="fix-you"${dir}>${esc(m.you)}</p>` : ''}
        <p class="fix-right"${dir}>${esc(m.fix.fixed)}</p>
        ${okunusLine(m.fix.okunus)}
        ${m.fix.explain_tr ? `<p class="fix-why">${esc(m.fix.explain_tr)}</p>` : ''}
        ${m.fix.how_tr ? `<p class="fix-how">🧩 Nasıl kurulur: ${esc(m.fix.how_tr)}</p>` : ''}
        <div class="t-actions">${playBtns(idx, 'fix')}</div>
      </div>`;
    } else if (m.mode === 'speak' && m.unclear) {
      html += '<span class="ok-badge is-unclear">🎤 Seni net duyamadım — yavaşça tekrar söyle</span>';
    } else if (m.mode === 'speak' && m.you && !m.pending && m.provider && m.provider !== 'rules' && (m.provider !== 'live' || m.checked)) {
      html += '<span class="ok-badge">✓ Doğru söyledin</span>';
    }
    if (m.examples && m.examples.length) {
      if (m.explain_tr) html += `<p class="help-note">${esc(m.explain_tr)}</p>`;
      html += `<div class="examples">${m.examples.map((ex, j) => `
        <div class="ex">
          <span class="ex-target"${dir}>${esc(ex.text)}</span>
          ${okunusLine(ex.okunus)}
          ${P.showTr && ex.tr ? `<span class="ex-tr">${esc(ex.tr)}</span>` : ''}
          <button type="button" class="play" data-play="${idx}" data-part="ex${j}" aria-label="Dinle">${ICON.fill}</button>
        </div>`).join('')}</div>`;
    } else if (m.explain_tr) {
      html += `<p class="help-note">${esc(m.explain_tr)}</p>`;
    }
    if (m.reply) {
      html += `<p class="t-target"${dir} lang="${esc(m.lang || P.lang)}">${esc(m.reply_target || m.reply)}</p>${okunusLine(m.okunus)}${trLine(m.reply_tr)}`;
      if (m.pending && !m.okunus && P.showOkunus) html += '<p class="t-pending">okunuş hazırlanıyor…</p>';
      html += `<div class="t-actions">${playBtns(idx, 'reply')}</div>`;
    }
    if (m.words && m.words.length) {
      html += `<div class="words">${m.words.map((w) => `<button type="button" class="word-chip" data-word="${esc(w.word)}"><b>${esc(w.word)}</b>${w.tr ? ` ${esc(w.tr)}` : ''}</button>`).join('')}</div>`;
    }
    return `<div class="msg msg-tutor" data-i="${idx}"><div class="msg-body">${html}</div></div>`;
  }

  function renderUser(m, i) {
    const help = m.mode === 'help';
    const txt = m.text || (m.pending ? '🎙️ Dinliyorum…' : '');
    return `<div class="msg msg-user ${help ? 'help' : ''} ${m.pending ? 'is-live' : ''}" data-i="${i}">${help ? '<span class="msg-tag">Yardım · Türkçe</span>' : ''}<div class="msg-body">${esc(txt)}${!help && m.okunus && P.showOkunus ? `<p class="t-okunus">${esc(m.okunus)}</p>` : ''}</div></div>`;
  }

  function render() {
    const feed = $('feed');
    if (!S.msgs.length) {
      const lg = langOf(P.lang);
      feed.innerHTML = `<div class="edu-start">
        <div class="edu-start-flag">${lg.flag}</div>
        <h2>${lg.tr} dersi · ${level()}</h2>
        <p>Öğretmen seninle <b>sesli</b> konuşur. <b>Konuş</b>'a basılı tut, ${lg.tr} söyle — bıraktığın an cevap verir.
        Takılırsan <b>Yardım</b>'a basıp <b>Türkçe</b> sor.</p>
        <button type="button" id="startLesson" class="btn btn-accent btn-block">Derse başla</button>
      </div>`;
      return;
    }
    const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 160;
    feed.innerHTML = S.msgs.map((m, i) => (m.role === 'user' ? renderUser(m, i) : renderTutor(m, i))).join('')
      + (S.busy && !L.tutorMsg ? '<div class="msg msg-tutor"><div class="typing"><i></i><i></i><i></i></div></div>' : '');
    if (nearBottom || S.busy || L.talking) feed.scrollTop = feed.scrollHeight;
  }

  function partItems(m, part) {
    if (!m) return [];
    const lang = m.lang || P.lang;
    // Türkçe ipucu Türkçe aksanla, hedef dil kendi aksanıyla (sırası korunur)
    if (part === 'reply') return (m.segments && m.segments.length) ? m.segments.map((g) => ({ text: g.text, lang: g.lang === 'tr' ? 'tr' : lang })) : [{ text: m.reply, lang }];
    if (part === 'fix' && m.fix) return [{ text: m.fix.fixed, lang }];
    if (part.startsWith('ex')) { const ex = (m.examples || [])[Number(part.slice(2))]; return ex ? [{ text: ex.text, lang }] : []; }
    return [];
  }

  $('feed').addEventListener('click', (e) => {
    const b = e.target.closest('[data-play]');
    if (b) {
      unlockAudio();
      const m = S.msgs[Number(b.dataset.play)];
      const slow = b.dataset.slow === '1';
      if (m && m._audio && m._audio.length && b.dataset.part === 'reply' && !slow && L.player) {
        stopAudio(); LiveAudio.unlock(); L.player.replay(m._audio, m._rate || 24000);
        return;
      }
      if (m && m.provider === 'live' && m.t && !slow && b.dataset.part === 'reply' && L.player) {
        stopAudio(); LiveAudio.unlock();
        void audGet(m.t).then((rec) => {
          if (rec && rec.blob) rec.blob.arrayBuffer().then((ab) => L.player.replay([new Uint8Array(ab)], rec.rate || 24000));
          else void speak(partItems(m, b.dataset.part), { slow: P.slow, btn: b });
        });
        return;
      }
      void speak(partItems(m, b.dataset.part), { slow: slow || P.slow, btn: b });
      return;
    }
    const st = e.target.closest('#startLesson');
    if (st) { void liveGreet(); return; }
    const w = e.target.closest('[data-word]');
    if (w) { unlockAudio(); void speak([{ text: w.dataset.word, lang: P.lang }], { btn: w }); }
  });

  // ------------------------------------------------------------------ header/meta
  function syncHeader() {
    const lg = langOf(P.lang);
    $('langLabel').textContent = `${lg.flag} ${lg.tr}`;
    $('levelBtn').textContent = level();
    $('levelBtn').title = `${level()} · ${LEVEL_TR[level()]}`;
    $('micSub').textContent = `${lg.flag} ${lg.name}`;
    $('scenarioBtn').textContent = P.scenario ? `Senaryo: ${SCENARIO_NAME[P.scenario] || P.scenario}` : 'Serbest sohbet · senaryo seç';
    const d = P.days[today()] || { min: 0 };
    $('todayMin').textContent = String(Math.round(d.min || 0));
    $('goalMin').textContent = String(P.goalMin || 10);
    $('goalBar').style.width = `${Math.min(100, Math.round(((d.min || 0) / (P.goalMin || 10)) * 100))}%`;
    $('streak').textContent = String(P.streak || 0);
    document.documentElement.lang = 'tr';
  }

  // ------------------------------------------------------------------ progress bookkeeping
  function bumpDay(isCorrect) {
    const t = today();
    const now = Date.now();
    const gap = Math.min(2, Math.max(0.15, (now - S.lastActive) / 60000));
    S.lastActive = now;
    const d = P.days[t] || (P.days[t] = { min: 0, turns: 0, correct: 0 });
    d.min = Math.round(((d.min || 0) + gap) * 10) / 10;
    d.turns = (d.turns || 0) + 1;
    if (isCorrect) d.correct = (d.correct || 0) + 1;
    if (P.lastDay !== t) {
      const y = new Date(Date.now() - 86400000);
      const yk = `${y.getFullYear()}-${String(y.getMonth() + 1).padStart(2, '0')}-${String(y.getDate()).padStart(2, '0')}`;
      P.streak = P.lastDay === yk ? (P.streak || 0) + 1 : 1;
      P.lastDay = t;
    }
    const keys = Object.keys(P.days).sort();
    while (keys.length > 60) delete P.days[keys.shift()];
  }

  function adaptLevel(res) {
    const lang = P.lang;
    const cur = LEVELS.indexOf(level()) + 1;
    const isFix = !!(res.fix && res.fix.status === 'fix');
    const rec = Array.isArray(P.recent[lang]) ? P.recent[lang] : [];
    rec.push(isFix ? 0 : 1);
    P.recent[lang] = rec.slice(-8);
    const guess = LEVELS.indexOf(res.user_level) + 1;
    if (guess > 0) {
      const prev = Number(P.ema[lang]) || cur;
      // ilk turlarda (yerleştirme) tahmine daha çok güven: C2 konuşan biri A1'de takılı kalmasın
      const w = (Number(P.sinceChange[lang]) || 0) < 4 ? 0.5 : 0.25;
      P.ema[lang] = Math.round((prev * (1 - w) + guess * w) * 100) / 100;
    }
    P.sinceChange[lang] = (Number(P.sinceChange[lang]) || 0) + 1;
    if (!P.autoLevel || P.sinceChange[lang] < 3 || P.recent[lang].length < 3) return;
    const acc = P.recent[lang].reduce((a, b) => a + b, 0) / P.recent[lang].length;
    const ema = Number(P.ema[lang]) || cur;
    let next = cur;
    if (ema >= cur + 0.6 && acc >= 0.65 && cur < 6) next = Math.min(6, cur + Math.max(1, Math.min(3, Math.round(ema) - cur)));
    else if ((ema <= cur - 0.75 || acc <= 0.25) && cur > 1) next = cur - 1;
    if (next !== cur) {
      P.levels[lang] = LEVELS[next - 1];
      P.sinceChange[lang] = 0;
      P.ema[lang] = next;
      setStatus(next > cur ? `Tebrikler! Seviyen ${LEVELS[next - 1]} oldu` : `Seviye ${LEVELS[next - 1]}'e ayarlandı — daha rahat ilerleyelim`, false);
    }
  }

  function recordLearning(res, userText) {
    const lang = P.lang;
    const words = Array.isArray(P.words[lang]) ? P.words[lang] : [];
    (res.words || []).forEach((w) => {
      if (!w.word || words.some((x) => x.w.toLowerCase() === w.word.toLowerCase())) return;
      words.unshift({ w: w.word, tr: w.tr || '', ts: Date.now() });
    });
    P.words[lang] = words.slice(0, 300);
    if (res.fix && res.fix.status === 'fix') {
      const ms = Array.isArray(P.mistakes[lang]) ? P.mistakes[lang] : [];
      ms.unshift({ you: userText, fixed: res.fix.fixed, ok: res.fix.okunus || '', why: res.fix.explain_tr || '', ts: Date.now() });
      P.mistakes[lang] = ms.slice(0, 100);
    }
  }

  // ------------------------------------------------------------------ turns
  function historyForApi() {
    return S.msgs.slice(-12).map((m) => (m.role === 'user'
      ? { role: 'user', text: (m.mode === 'help' ? '(Türkçe yardım istedi) ' : '') + m.text }
      : { role: 'tutor', text: m.reply || (m.examples && m.examples[0] && m.examples[0].text) || '' }))
      .filter((h) => h.text);
  }
  function weakForApi() {
    const ms = Array.isArray(P.mistakes[P.lang]) ? P.mistakes[P.lang] : [];
    return ms.slice(0, 4).map((m) => `${m.you} → ${m.fixed}`.slice(0, 120));
  }

  async function postTurn(body) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TURN_TIMEOUT);
    try {
      let r;
      try {
        r = await fetch('/api/edu/turn', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: ctrl.signal });
      } catch (e) {
        if (e && e.name === 'AbortError') throw new Error('Yanıt gecikti — tekrar dene');
        // sunucu uykudaysa uyandırıp bir kez daha dene
        setStatus('Sunucu uyanıyor…', true, true);
        if (window.ApiClient) await ApiClient.wakeServer(30000);
        r = await fetch('/api/edu/turn', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: ctrl.signal });
      }
      if (r.status === 502 || r.status === 503) {
        setStatus('Sunucu uyanıyor…', true, true);
        if (window.ApiClient) await ApiClient.wakeServer(30000);
        r = await fetch('/api/edu/turn', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: ctrl.signal });
      }
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || 'Bağlantı sorunu — tekrar dene');
      return d;
    } finally {
      clearTimeout(timer);
    }
  }

  async function runTurn({ text = '', audioB64 = '', mode = 'speak' }) {
    if (S.busy) return;
    S.busy = true;
    stopAudio();
    if (text) S.msgs.push({ role: 'user', text, mode, t: Date.now() });
    render();
    setStatus(audioB64 ? 'Anlıyorum…' : 'Düşünüyorum…', true, true);
    const body = {
      lang: P.lang, mode, level: level(), scenario: P.scenario || null,
      slow: P.slow, voice: P.accents[P.lang] || null,
      history: historyForApi().slice(0, text ? -1 : undefined), weak: weakForApi(),
    };
    if (text) body.text = text; else body.audio = audioB64;
    try {
      const res = await postTurn(body);
      // istemci tarafında hemen sesi istemeye başla (sunucu zaten hazırlıyor)
      const speakItems = Array.isArray(res.speak) ? res.speak : [];
      if (P.autoSpeak) speakItems.forEach((i) => fetchTts(i.text, i.lang || P.lang, P.slow));
      if (!text && res.user_text) S.msgs.push({ role: 'user', text: res.user_text, mode, t: Date.now() });
      const userText = res.user_text || text;
      const msg = {
        role: 'tutor', lang: res.lang || P.lang, mode, you: mode === 'speak' ? userText : '',
        reply: res.reply || '', reply_tr: res.reply_tr || '', okunus: res.okunus || '',
        fix: res.fix || null, examples: res.examples || [], explain_tr: res.explain_tr || '',
        words: res.words || [], speak: speakItems, provider: res.provider || '', t: Date.now(),
      };
      S.msgs.push(msg);
      if (mode === 'speak') {
        P.turns = (P.turns || 0) + 1;
        if (!msg.fix || msg.fix.status !== 'fix') P.correct = (P.correct || 0) + 1;
        adaptLevel(res);
      }
      bumpDay(mode === 'speak' && !(msg.fix && msg.fix.status === 'fix'));
      recordLearning(res, userText);
      saveProfile();
      S.busy = false;
      saveChat();
      render();
      syncHeader();
      if (res.provider === 'rules') showAiNotice();
      if (!$('statusText').textContent.startsWith('Tebrikler') && !$('statusText').textContent.startsWith('Seviye')) idleStatus();
      if (P.autoSpeak && speakItems.length) {
        const btn = document.querySelector('#feed .msg:last-child [data-play]');
        void speak(speakItems, { btn });
      }
    } catch (e) {
      S.busy = false;
      render();
      setStatus((e && e.message) || 'Bir sorun oldu — tekrar dene');
    }
  }

  async function greet() {
    S.busy = true;
    render();
    try {
      const q = new URLSearchParams({ lang: P.lang, level: level(), slow: P.slow ? '1' : '0' });
      if (P.scenario) q.set('scenario', P.scenario);
      if (P.accents[P.lang]) q.set('voice', P.accents[P.lang]);
      let r;
      try { r = await fetch(`/api/edu/greeting?${q}`); } catch { if (window.ApiClient) await ApiClient.wakeServer(30000); r = await fetch(`/api/edu/greeting?${q}`); }
      const res = await r.json();
      if (!r.ok) throw new Error(res.error || 'Bağlantı sorunu');
      S.msgs.push({ role: 'tutor', lang: res.lang, mode: 'greeting', reply: res.reply, reply_tr: res.reply_tr, okunus: res.okunus, speak: res.speak || [], examples: [], words: [], t: Date.now() });
      saveChat();
      if (P.autoSpeak && audioUnlocked) void speak(res.speak || []);
      else (res.speak || []).forEach((i) => fetchTts(i.text, i.lang, P.slow));
    } catch (e) {
      setStatus('Sunucuya ulaşılamadı — internetini kontrol et');
    } finally {
      S.busy = false;
      render();
    }
  }

  async function sendText() {
    const input = $('textInput');
    const text = input.value.trim();
    if (!text || S.busy) return;
    input.value = '';
    unlockAudio();
    const mode = /^\s*(yardım|yardim)\b/i.test(text) ? 'help' : 'speak';
    const clean = mode === 'help' ? text.replace(/^\s*(yardım|yardim)[\s,:-]*/i, '') || text : text;
    if (LIVE_OK && L.failed < 2) { await liveSendText(clean, mode); return; }
    await runTurn({ text: clean, mode });
  }

  function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => resolve(String(fr.result || ''));
      fr.onerror = () => reject(new Error('Ses okunamadı'));
      fr.readAsDataURL(blob);
    });
  }

  // ------------------------------------------------------------------ microphone
  let activeMicBtn = null;
  const mic = window.MicHold && MicHold.create({
    state: S,
    tailMs: 260,
    minHoldMs: 320,
    minBlobBytes: 400,
    micOpenMs: 12000,
    canBegin: () => {
      if (S.busy) { setStatus('Önceki cevap bekleniyor…'); return false; }
      return true;
    },
    onHideError: () => {},
    onMicOpening: () => setStatus('Mikrofon açılıyor…', true, true),
    onSpeaking: () => {
      stopAudio();
      if (activeMicBtn) activeMicBtn.classList.add('recording');
      setStatus(S.mode === 'help' ? 'Dinliyorum — Türkçe söyle…' : `Dinliyorum — ${langOf(P.lang).tr} konuş…`, true, true);
    },
    unlockAudio,
    onProcessing: () => {
      document.querySelectorAll('.mic-btn.recording').forEach((b) => b.classList.remove('recording'));
      setStatus('Anlıyorum…', true, true);
    },
    onIdle: () => {
      document.querySelectorAll('.mic-btn.recording').forEach((b) => b.classList.remove('recording'));
      if (!S.busy) idleStatus();
    },
    onShortHold: () => setStatus('Biraz daha uzun basılı tut'),
    onEmptyBlob: () => setStatus('Ses duyulamadı — tekrar dene'),
    onError: (msg) => setStatus(msg || 'Mikrofon hatası'),
    isBusy: () => S.busy,
    onBlob: async (blob) => {
      document.querySelectorAll('.mic-btn.recording').forEach((b) => b.classList.remove('recording'));
      try {
        const b64 = await blobToBase64(blob);
        await runTurn({ audioB64: b64, mode: S.mode });
      } catch (e) {
        setStatus((e && e.message) || 'Ses gönderilemedi');
      }
    },
  });

  // ------------------------------------------------------------------ CANLI SES (Gemini Live)
  // Bas-konuş: konuşurken ses parça parça Google'a akar; bıraktığın anda cevap sesli akmaya başlar.
  const TUTOR_VAD = false; // ölçüldü: elle başlat/bitir modu daha hızlı (bırakınca ~1 sn'de cevap)
  const LIVE_OK = !!(window.LiveAudio && window.WebSocket && window.AudioWorkletNode && navigator.mediaDevices);
  const L = { session: null, player: null, mic: null, pendingChunks: [], talking: false, userMsg: null, tutorMsg: null,
    started: false, failed: 0, turnTimer: null, mode: 'speak', sessionKey: '' };

  function liveBody() {
    return { kind: 'tutor', vad: TUTOR_VAD, lang: P.lang, level: level(), scenario: P.scenario || null, weak: weakForApi(),
      history: S.msgs.filter((m) => !m.pending).slice(-12).map((m) => (m.role === 'user'
        ? { role: 'user', text: m.text || '' }
        : { role: 'model', text: m.reply || (m.examples && m.examples[0] && m.examples[0].text) || '' })).filter((h) => h.text) };
  }
  function liveKey() { return `${P.lang}|${level()}|${P.scenario || ''}`; }

  function seedTurns() {
    return S.msgs.slice(-8).map((m) => (m.role === 'user'
      ? { role: 'user', parts: [{ text: m.text }] }
      : { role: 'model', parts: [{ text: m.reply || (m.examples && m.examples[0] && m.examples[0].text) || '' }] }))
      .filter((t) => t.parts[0].text);
  }

  function ensureLive() {
    if (!LIVE_OK) return Promise.reject(new Error('Bu tarayıcı canlı sesi desteklemiyor'));
    if (L.session && L.sessionKey !== liveKey()) { L.session.close(); L.session = null; }
    if (!L.player) {
      L.player = new LiveAudio.Player({
        onStart: () => { setStatus('Öğretmen konuşuyor…', true, true); },
        onIdle: () => { if (!L.talking && !S.busy) idleStatus(); },
      });
    }
    if (!L.session) {
      L.sessionKey = liveKey();
      L.session = new LiveAudio.Session({
        body: liveBody,
        onReady: () => {
          // Yeni oturum (devam tutamacı yoksa): önceki sohbeti bağlam olarak ver
          // geçmiş sohbet artık oturum talimatında (sunucu) — burada ayrıca göndermeye gerek yok
        },
        onAudio: (u8, rate) => {
          if (!L.tutorMsg) startTutorMsg();
          L.tutorMsg._audio.push(u8);
          L.tutorMsg._rate = rate;
          if (P.autoSpeak) L.player.enqueue(u8, rate);
        },
        onInput: (t) => {
          if (!L.userMsg && L.talking) { L.userMsg = { role: 'user', text: '', mode: L.mode, t: Date.now(), pending: true }; S.msgs.push(L.userMsg); renderSoon(); }
          if (L.userMsg) { L.userMsg.text = (L.userMsg._final = (L.userMsg._final || '') + t).replace(/\s+/g, ' '); patchSoon(); }
        },
        onInterim: (t) => {
          if (L.userMsg && !L.userMsg._final) { L.userMsg.text = String(t).replace(/\s+/g, ' '); patchSoon(); }
        },
        onOutput: (t) => {
          if (!L.tutorMsg) startTutorMsg();
          L.tutorMsg.reply = (L.tutorMsg.reply + t).replace(/\s+/g, ' ');
          if (L.genTimer) { clearTimeout(L.genTimer); L.genTimer = setTimeout(() => { if (L.tutorMsg) finishLiveTurn(); }, 1800); }
          patchSoon();
        },
        onInterrupted: () => { if (L.talking) L.player.stop(); },
        // metin bitince (ses hâlâ çalarken) okunuş/çeviri istenir → ekranda bekleme olmaz
        // yazıya dökme sesten/metinden sonra gelebilir → hemen bitirme, son parçadan sonra kısa süre bekle (cümle ikiye bölünmesin)
        onGenerationComplete: () => { if (L.tutorMsg) { clearTimeout(L.genTimer); L.genTimer = setTimeout(() => { if (L.tutorMsg) finishLiveTurn(); }, 1800); } },
        onTurnComplete: () => { if (L.tutorMsg || L.userMsg) finishLiveTurn(); },
        onState: (st) => {
          if (st === 'closed' || st === 'goaway') {
            if (L.session) L.session.ws = null;
            setTimeout(warmLive, 1500); // bağlantıyı hazır tut → basınca bekleme olmasın
          }
        },
      });
    }
    return L.session.connect();
  }

  let warmFails = 0;
  function warmLive() {
    if (!LIVE_OK || document.visibilityState !== 'visible' || L.talking || warmFails > 3) return;
    ensureLive().then(() => { warmFails = 0; }).catch(() => { warmFails += 1; });
  }

  function startTutorMsg() {
    S.busy = false;
    // bitmiş öğretmen mesajının geç gelen son parçası: yeni balon açma, aynı mesaja ekle
    const lastMsg = S.msgs[S.msgs.length - 1];
    if (L.lastTutor && lastMsg === L.lastTutor && Date.now() - (L.lastDone || 0) < 6000 && !L.userMsg && !L.talking) {
      L.tutorMsg = L.lastTutor; L.tutorMsg.pending = true; L.tutorMsg._reopen = true;
      renderSoon();
      return;
    }
    L.tutorMsg = { role: 'tutor', lang: P.lang, mode: L.mode, you: L.mode === 'speak' && L.userMsg ? L.userMsg.text : '',
      reply: '', reply_tr: '', okunus: '', fix: null, examples: [], explain_tr: '', words: [], provider: 'live', live: true,
      pending: true, t: Date.now(), _audio: [], _rate: 24000 };
    S.msgs.push(L.tutorMsg);
    renderSoon();
  }

  /** Akan metni yerinde güncelle (tüm sohbeti yeniden çizmeden) → titreme yok */
  let patchPending = false;
  function patchSoon() {
    if (patchPending) return;
    patchPending = true;
    requestAnimationFrame(() => {
      patchPending = false;
      const feed = $('feed');
      let structural = false;
      [L.userMsg, L.tutorMsg].forEach((m) => {
        if (!m) return;
        const i = S.msgs.indexOf(m);
        const el = feed.querySelector(`[data-i="${i}"]`);
        if (!el) { structural = true; return; }
        if (m.role === 'user') {
          const b = el.querySelector('.msg-body');
          const t = m.text || (L.talking ? (L.heard ? '🎙️ Seni duyuyorum…' : '🎙️ Dinliyorum…') : '…');
          if (b && b.textContent !== t) b.textContent = t;
        } else {
          const tgt = el.querySelector('.t-target');
          if (!tgt) { structural = true; return; }
          if (tgt.textContent !== m.reply) tgt.textContent = m.reply;
        }
      });
      if (structural) { render(); return; }
      const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 200;
      if (nearBottom) feed.scrollTop = feed.scrollHeight;
    });
  }

  let renderPending = false;
  function renderSoon() {
    if (renderPending) return;
    renderPending = true;
    requestAnimationFrame(() => { renderPending = false; render(); });
  }

  async function finishLiveTurn() {
    clearTimeout(L.turnTimer); clearTimeout(L.genTimer); L.genTimer = null;
    const user = L.userMsg; const tutor = L.tutorMsg;
    L.userMsg = null; L.tutorMsg = null; S.busy = false;
    if (user && !user.text.trim()) {
      const i = S.msgs.indexOf(user);
      if (i >= 0) S.msgs.splice(i, 1);
    }
    if (user) user.pending = false;
    if (!tutor) { render(); idleStatus(); return; }
    tutor.reply = tutor.reply.trim();
    tutor.you = tutor.mode === 'speak' ? (user ? user.text.trim() : (tutor._reopen ? tutor.you : '')) : '';
    L.lastTutor = tutor; L.lastDone = Date.now();
    const seq = (tutor._seq = (tutor._seq || 0) + 1);
    const ut = user ? (user.mode !== 'help' ? user.text : '') : (tutor._reopen && tutor.mode !== 'help' ? tutor.you : '');
    // Cevap + ses hemen bitsin; okunuş/TR arka planda gelsin (takılma azalır)
    tutor.pending = false;
    const prevT = [...S.msgs].reverse().find((m) => m !== tutor && m.role === 'tutor' && m.reply && !m.pending);
    const prevTutor = prevT ? String(prevT.reply).slice(0, 500) : '';
    render(); saveChat();
    saveLiveAudio(tutor); setTimeout(() => saveLiveAudio(tutor), 1500);
    if (!L.player.playing) idleStatus();
    void (async () => {
      // okunuş+Türkçe hızlı (kural/çeviri) ve düzeltme+seviye ayrı istek → okunuş düzeltmeyi beklemeden hemen gelir
      const post = (part) => fetch('/api/edu/annotate', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lang: tutor.lang, tutor_text: tutor.reply, user_text: ut, mode: tutor.mode, level: level(), prev_tutor: prevTutor, part }) })
        .then((r) => (r.ok ? r.json() : null)).catch(() => null);
      const pFast = post('fast');
      const pCheck = ut ? post('check') : Promise.resolve(null);
      try {
        const f = await pFast;
        if (f && tutor._seq === seq) {
          tutor.okunus = f.okunus || '';
          tutor.segments = Array.isArray(f.segments) ? f.segments : [];
          if (user && f.user_okunus) user.okunus = f.user_okunus;
          tutor.reply_tr = f.tr || '';
          if (f.hint_tr) { tutor.explain_tr = f.hint_tr; tutor.reply_target = f.target || ''; }
          saveChat(); render();
          // canlı ses gelmediyse (ör. yazıyla sorulunca) sessiz kalma: yedek seslendirme
          if (P.autoSpeak && tutor.reply && !(tutor._audio && tutor._audio.length)) void speak(partItems(tutor, 'reply'));
        }
        const a = await pCheck;
        if (a && tutor._seq === seq) { tutor.fix = a.fix || null; tutor.words = a.words || []; tutor.checked = !!a.checked; tutor.unclear = !!a.unclear; }
        if (a && tutor.mode === 'speak' && user && user.text.trim() && !tutor.unclear) {
          P.turns = (P.turns || 0) + 1;
          if (!tutor.fix) P.correct = (P.correct || 0) + 1;
          adaptLevel({ fix: tutor.fix, user_level: a.user_level });
          bumpDay(!tutor.fix);
        } else {
          bumpDay(false);
        }
        recordLearning({ words: tutor.words, fix: tutor.fix }, tutor.you);
        saveProfile();
        saveChat(); render(); syncHeader();
      } catch { /* ses zaten çaldı */ }
    })();
  }

  const SILENCE = new Uint8Array(3200); // 100 ms sessizlik @16 kHz
  let micBusy = false; let micBusyAt = 0;

  /** Bas: mikrofon zaten açık → anında kayıt. İlk kez → yalnızca izin iste, dinlemeye geçme. */
  async function liveHoldStart(btn, mode) {
    if (micBusy && Date.now() - micBusyAt > 8000) micBusy = false; // takılı kalmış izin/açılış durumu
    if (L.talking || micBusy) return;
    LiveAudio.unlock();
    if (!LiveAudio.micReady()) {
      micBusy = true; micBusyAt = Date.now();
      btn.classList.add('arming');
      let perm = 'unknown';
      try { perm = await LiveAudio.micPermission(); } catch { /* ignore */ }
      if (perm !== 'granted') setStatus('Mikrofon izni isteniyor… “İzin ver”e dokun', true, true);
      const t0 = performance.now();
      try {
        await LiveAudio.openMic();
      } catch (e) {
        micBusy = false; btn.classList.remove('arming');
        setStatus(e && e.name === 'NotAllowedError' ? 'Mikrofon izni gerekli (Ayarlar → Safari → Mikrofon)' : 'Mikrofon açılamadı');
        return;
      }
      micBusy = false;
      btn.classList.remove('arming');
      // izin penceresi çıktıysa (ya da parmağını kaldırdıysan) bu basış yalnızca izin içindi
      if (perm !== 'granted' || performance.now() - t0 > 900 || !btn._held) {
        setStatus('Mikrofon hazır ✓ — şimdi basılı tutup konuş', true);
        setTimeout(() => { if (!L.talking && !S.busy) idleStatus(); }, 2500);
        return;
      }
    }
    if (!btn._held) return;
    beginTalk(btn, mode);
  }

  function beginTalk(btn, mode) {
    const wasPlaying = !!(L.player && L.player.playing);
    L.player && L.player.stop();
    stopAudio();
    if (L.tutorMsg) { L.tutorMsg.pending = false; L.tutorMsg = null; }
    clearTimeout(L.turnTimer);
    L.talking = true; L.talkAt = Date.now(); L.mode = mode; L.heard = false;
    btn.classList.add('recording');
    setStatus(mode === 'help' ? 'Dinliyorum — Türkçe söyle' : `Dinliyorum — ${langOf(P.lang).tr} konuş`, true, true);
    L.userMsg = { role: 'user', text: '', mode, t: Date.now(), pending: true };
    S.msgs.push(L.userMsg);
    renderSoon();
    L.turnReady = ensureLive();
    L.turn = new LiveAudio.Turn(L.session, L.turnReady);
    const t = L.turn;
    L.turnReady.catch((e) => { L.failed += 1; liveAbort(btn, e.message || 'Canlı bağlantı kurulamadı'); });
    L.mic = new LiveAudio.Mic({
      preroll: !wasPlaying, // öğretmenin sesi mikrofona karışmasın
      onChunk: (u8) => t.chunk(u8),
      onLevel: (lv) => {
        t.level(lv);
        btn.style.setProperty('--lv', Math.min(1, lv * 3).toFixed(2));
        if (t.voiced && L.userMsg && !L.userMsg.text && !L.heard) { L.heard = true; patchSoon(); }
      },
    });
    L.mic.start().catch((e) => liveAbort(btn, (e && e.name === 'NotAllowedError') ? 'Mikrofon izni gerekli' : 'Mikrofon açılamadı'));
  }

  function liveAbort(btn, msg) {
    L.talking = false;
    if (L.mic) { L.mic.stop(); L.mic = null; }
    btn.classList.remove('recording', 'arming');
    if (L.userMsg) { const i = S.msgs.indexOf(L.userMsg); if (i >= 0) S.msgs.splice(i, 1); L.userMsg = null; }
    render();
    setStatus(msg);
  }

  /** Bırak: son parça gider gitmez konuşma bitti bilgisi → cevap hemen akar */
  async function liveHoldEnd(btn) {
    if (!L.talking) return;
    L.talking = false;
    btn.classList.remove('recording', 'arming');
    btn.style.removeProperty('--lv');
    const m = L.mic; L.mic = null;
    S.busy = true;
    setStatus('Cevap geliyor…', true, true);
    patchSoon();
    if (m) await m.stop();
    let sent = false;
    try { sent = L.turn ? await L.turn.end() : false; } catch (e) { S.busy = false; setStatus((e && e.message) || 'Bağlantı sorunu'); render(); return; }
    L.turn = null;
    if (!sent) { // ses yok → modele hiçbir şey gitmedi (uydurma cevap yok)
      if (L.userMsg) { const i = S.msgs.indexOf(L.userMsg); if (i >= 0) S.msgs.splice(i, 1); L.userMsg = null; }
      S.busy = false; render(); setStatus('Seni duyamadım — basılı tutup tekrar konuş');
      return;
    }
    clearTimeout(L.turnTimer);
    // hiç ses algılanmadıysa kullanıcıyı bekletme
    L.turnTimer = setTimeout(() => {
      if (L.userMsg && !L.userMsg.text && !L.tutorMsg) { finishLiveTurn(); setStatus('Seni duyamadım — basılı tutup tekrar konuş'); }
    }, 6000);
    setTimeout(() => { if (S.busy || L.userMsg) { finishLiveTurn(); } }, 25000);
  }

  async function liveSendText(text, mode) {
    LiveAudio.unlock();
    stopAudio();
    L.player && L.player.stop();
    L.mode = mode;
    L.userMsg = { role: 'user', text, mode, t: Date.now() };
    S.msgs.push(L.userMsg);
    S.busy = true;
    render();
    setStatus('Cevap geliyor…', true, true);
    try {
      await ensureLive();
      L.session.sendText(mode === 'help' ? `(Türkçe yardım istiyor) ${text}` : text);
      clearTimeout(L.turnTimer);
      L.turnTimer = setTimeout(() => { if (S.busy || L.userMsg) finishLiveTurn(); }, 20000);
    } catch (e) {
      // canlı olmazsa klasik yol
      const i = S.msgs.indexOf(L.userMsg); if (i >= 0) S.msgs.splice(i, 1);
      L.userMsg = null; S.busy = false;
      await runTurn({ text, mode });
    }
  }

  async function liveGreet() {
    if (L.started) return;
    L.started = true;
    LiveAudio.unlock();
    S.busy = true; render();
    setStatus('Bağlanıyor…', true, true);
    try {
      await ensureLive();
      L.mode = 'greeting';
      L.session.sendText('[BAŞLA]');
      L.turnTimer = setTimeout(() => { if (S.busy) finishLiveTurn(); }, 15000);
    } catch (e) {
      S.busy = false; render();
      setStatus('Canlı ses açılamadı — klasik moda geçildi');
      void greet();
    }
  }

  function bindMic(btn, mode) {
    if (!btn) return;
    const useLive = () => LIVE_OK && L.failed < 2;
    const down = (e) => {
      e.preventDefault();
      btn._held = true;
      if (useLive()) {
        if (L.talking && Date.now() - (L.talkAt || 0) > 800) void liveHoldEnd(btn); // önceki basış hiç bırakılmadıysa (kayıp touchend) onu bitir
        void liveHoldStart(btn, mode); return;
      }
      S.mode = mode; activeMicBtn = btn;
      if (mic) void mic.beginHold();
    };
    const up = (e) => {
      e.preventDefault();
      btn._held = false;
      if (L.talking) { void liveHoldEnd(btn); return; }
      if (mic) mic.endHold();
    };
    let usedTouch = false;
    btn.addEventListener('contextmenu', (e) => e.preventDefault());
    btn.addEventListener('touchstart', (e) => { usedTouch = true; down(e); }, { passive: false });
    btn.addEventListener('touchend', up, { passive: false });
    btn.addEventListener('touchcancel', up, { passive: false });
    btn.addEventListener('mousedown', (e) => { if (!usedTouch) down(e); });
    btn.addEventListener('mouseup', (e) => { if (!usedTouch) up(e); });
    btn.addEventListener('mouseleave', (e) => { if (!usedTouch && L.talking) up(e); });
  }
  bindMic($('micBtn'), 'speak');
  bindMic($('helpBtn'), 'help');
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    ['micBtn', 'helpBtn'].forEach((id) => { $(id).disabled = true; });
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') { L.hiddenAt = Date.now(); if (L.session) { L.player && L.player.stop(); } }
    if (document.visibilityState === 'visible') {
      warmFails = 0;
      if (L.hiddenAt && Date.now() - L.hiddenAt > 4000) {
        // arka plandan dönüş: takılı kalan durumu temizle, bağlantıyı tazele
        if (L.tutorMsg || L.userMsg) void finishLiveTurn();
        L.talking = false; S.busy = false; micBusy = false;
        try { if (L.session) L.session.close(); } catch { /* ignore */ }
        L.session = null;
        idleStatus();
      }
      L.hiddenAt = 0;
      setTimeout(warmLive, 300);
    }
  });

  // ------------------------------------------------------------------ sheets
  function openSheet(id) { $(id).classList.remove('hidden'); }
  function closeSheet(id) { $(id).classList.add('hidden'); }
  document.querySelectorAll('.sheet').forEach((sh) => {
    sh.addEventListener('click', (e) => { if (e.target.hasAttribute('data-close')) closeSheet(sh.id); });
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') document.querySelectorAll('.sheet').forEach((s) => closeSheet(s.id)); });

  function buildSettings() {
    $('langGrid').innerHTML = LANGS.map((l) => `<button type="button" class="lang-opt ${l.code === P.lang ? 'active' : ''}" data-lang="${l.code}"><span>${l.flag}</span>${l.tr}</button>`).join('');
    $('levelGrid').innerHTML = LEVELS.map((lv) => `<button type="button" class="${lv === level() ? 'active' : ''}" data-level="${lv}" title="${LEVEL_TR[lv]}">${lv}</button>`).join('');
    $('autoLevel').checked = !!P.autoLevel;
    const sel = $('scenarioSelect');
    sel.innerHTML = '<option value="">Serbest sohbet</option>' + SCENARIOS.map(([g, items]) => `<optgroup label="${esc(g)}">${items.map(([id, name]) => `<option value="${id}">${esc(name)}</option>`).join('')}</optgroup>`).join('');
    sel.value = P.scenario || '';
    const acc = ACCENTS[P.lang] || [];
    $('accentField').classList.toggle('hidden', !acc.length);
    $('accentSelect').innerHTML = acc.map(([v, n]) => `<option value="${v}">${esc(n)}</option>`).join('');
    if (acc.length) $('accentSelect').value = P.accents[P.lang] || acc[0][0];
    $('optAutoSpeak').checked = !!P.autoSpeak;
    $('optSlow').checked = !!P.slow;
    $('optOkunus').checked = !!P.showOkunus;
    $('optTr').checked = !!P.showTr;
  }

  function switchConversation() {
    stopAudio();
    if (L.player) L.player.stop();
    if (L.session) { L.session.close(); L.session = null; }
    L.started = false; L.userMsg = null; L.tutorMsg = null; S.busy = false;
    S.msgs = loadChat();
    syncHeader();
    render();
    if (!S.msgs.length && !LIVE_OK) void greet();
    setTimeout(warmLive, 300);
  }

  $('langGrid').addEventListener('click', (e) => {
    const b = e.target.closest('[data-lang]');
    if (!b || b.dataset.lang === P.lang) return;
    P.lang = b.dataset.lang;
    saveProfile();
    buildSettings();
    switchConversation();
  });
  $('levelGrid').addEventListener('click', (e) => {
    const b = e.target.closest('[data-level]');
    if (!b) return;
    P.levels[P.lang] = b.dataset.level;
    P.sinceChange[P.lang] = 0;
    P.ema[P.lang] = LEVELS.indexOf(b.dataset.level) + 1;
    saveProfile();
    buildSettings();
    syncHeader();
  });
  $('autoLevel').addEventListener('change', (e) => { P.autoLevel = e.target.checked; saveProfile(); });
  $('scenarioSelect').addEventListener('change', (e) => {
    archiveCurrent();
    P.scenario = e.target.value || '';
    saveProfile();
    S.msgs = [];
    saveChat();
    closeSheet('settingsSheet');
    switchConversation();
  });
  $('accentSelect').addEventListener('change', (e) => {
    P.accents[P.lang] = e.target.value;
    saveProfile();
    const last = [...S.msgs].reverse().find((m) => m.role === 'tutor' && m.reply);
    if (last) { unlockAudio(); void speak([{ text: last.reply, lang: P.lang }]); }
  });
  const bindOpt = (id, key) => $(id).addEventListener('change', (e) => { P[key] = e.target.checked; saveProfile(); render(); });
  bindOpt('optAutoSpeak', 'autoSpeak');
  bindOpt('optSlow', 'slow');
  bindOpt('optOkunus', 'showOkunus');
  bindOpt('optTr', 'showTr');
  $('newChatBtn').addEventListener('click', () => {
    archiveCurrent();
    S.msgs = [];
    saveChat();
    closeSheet('settingsSheet');
    switchConversation();
  });
  $('closeSettings').addEventListener('click', () => closeSheet('settingsSheet'));
  const openSettings = () => { buildSettings(); renderChatList(); openSheet('settingsSheet'); };
  $('settingsBtn').addEventListener('click', openSettings);
  $('langBtn').addEventListener('click', openSettings);
  $('levelBtn').addEventListener('click', openSettings);
  $('scenarioBtn').addEventListener('click', () => { openSettings(); setTimeout(() => $('scenarioSelect').scrollIntoView({ block: 'center' }), 50); });

  function buildProgress() {
    const lang = P.lang;
    const lg = langOf(lang);
    const words = Array.isArray(P.words[lang]) ? P.words[lang] : [];
    const mistakes = Array.isArray(P.mistakes[lang]) ? P.mistakes[lang] : [];
    const rec = Array.isArray(P.recent[lang]) ? P.recent[lang] : [];
    const acc = rec.length ? Math.round((rec.reduce((a, b) => a + b, 0) / rec.length) * 100) : null;
    const days = [];
    for (let i = 6; i >= 0; i -= 1) {
      const d = new Date(Date.now() - i * 86400000);
      const k = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      days.push({ label: d.toLocaleDateString('tr-TR', { weekday: 'short' }), min: (P.days[k] && P.days[k].min) || 0 });
    }
    const max = Math.max(P.goalMin || 10, ...days.map((d) => d.min));
    $('progressBody').innerHTML = `
      <div class="stat-grid">
        <div class="stat"><b>${level()}</b><span>${lg.tr} · ${LEVEL_TR[level()]}</span></div>
        <div class="stat"><b>${P.streak || 0}</b><span>gün seri</span></div>
        <div class="stat"><b>${acc == null ? '—' : `${acc}%`}</b><span>son doğruluk</span></div>
      </div>
      <h3>Son 7 gün (dakika)</h3>
      <div class="week">${days.map((d) => `<div><i style="height:${Math.max(3, Math.round((d.min / max) * 60))}px"></i><span>${esc(d.label)}</span></div>`).join('')}</div>
      <h3>Kelimelerim (${words.length})</h3>
      ${words.length ? `<div class="list">${words.slice(0, 40).map((w, i) => `<div class="list-item"><div class="grow"><b>${esc(w.w)}</b><small>${esc(w.tr)}</small></div><button type="button" class="t-btn" data-pw="${i}">${ICON.play}</button></div>`).join('')}</div>` : '<p class="hint">Sohbet ettikçe yeni kelimeler burada birikir.</p>'}
      <h3>Düzeltmelerim (${mistakes.length})</h3>
      ${mistakes.length ? `<div class="list">${mistakes.slice(0, 30).map((m, i) => `<div class="list-item"><div class="grow"><b>${esc(m.fixed)}</b><small>${esc(m.you)}${m.why ? ` — ${esc(m.why)}` : ''}</small></div><button type="button" class="t-btn" data-pm="${i}">${ICON.play}</button></div>`).join('')}</div>` : '<p class="hint">Hata yaptığında doğrusu buraya kaydedilir; tekrar dinleyip çalışabilirsin.</p>'}
    `;
  }
  $('progressBody').addEventListener('click', (e) => {
    const w = e.target.closest('[data-pw]');
    const m = e.target.closest('[data-pm]');
    unlockAudio();
    if (w) { const item = (P.words[P.lang] || [])[Number(w.dataset.pw)]; if (item) void speak([{ text: item.w, lang: P.lang }], { btn: w }); }
    if (m) { const item = (P.mistakes[P.lang] || [])[Number(m.dataset.pm)]; if (item) void speak([{ text: item.fixed, lang: P.lang }], { btn: m }); }
  });
  $('progressBtn').addEventListener('click', () => { buildProgress(); openSheet('progressSheet'); });
  $('closeProgress').addEventListener('click', () => closeSheet('progressSheet'));
  $('resetBtn').addEventListener('click', () => {
    const lg = langOf(P.lang);
    if (!window.confirm(`${lg.tr} için sohbet, kelime ve düzeltme kayıtları silinsin mi?`)) return;
    delete P.words[P.lang]; delete P.mistakes[P.lang]; delete P.recent[P.lang]; delete P.ema[P.lang];
    delete P.sinceChange[P.lang];
    try { localStorage.removeItem(archKey(P.lang)); } catch { /* ignore */ }
    saveProfile();
    S.msgs = [];
    saveChat();
    closeSheet('progressSheet');
    switchConversation();
  });

  // ------------------------------------------------------------------ AI notice
  let noticeShown = false;
  function showAiNotice() {
    if (noticeShown) return;
    noticeShown = true;
    const el = $('aiNotice');
    el.innerHTML = '<details><summary>Yapay zekâ şu an yanıt vermiyor — basit modda devam ediliyor</summary><p>Render ayarlarında GROQ_API_KEY ya da GEMINI_API_KEY tanımlı ve geçerli olmalı.</p></details>';
    el.classList.remove('hidden');
  }
  fetch('/api/status').then((r) => r.json()).then((d) => { if (d && d.ai_enabled === false) showAiNotice(); }).catch(() => {});

  // ------------------------------------------------------------------ composer + boot
  $('sendBtn').addEventListener('click', () => void sendText());
  $('textInput').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); void sendText(); } });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') { stopAudio(); if (mic) mic.releaseMic(); }
    else S.lastActive = Date.now();
  });

  switchConversation();
  idleStatus();
})();

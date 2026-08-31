/**
 * Cümle Kur + Kendini Test Et — localStorage katmanı
 */
(function (global) {
  'use strict';

  const WORDS_KEY = 'edu_learned_words_v1';
  const SENTENCES_KEY = 'edu_learned_sentences_v1';
  const RESULTS_KEY = 'edu_practice_results_v1';
  const LANG_KEY = 'edu_builder_lang_v1';

  const LANGUAGES = [
    { code: 'en', name: 'English', flag: '🇬🇧' },
    { code: 'de', name: 'Deutsch', flag: '🇩🇪' },
    { code: 'fr', name: 'Français', flag: '🇫🇷' },
    { code: 'es', name: 'Español', flag: '🇪🇸' },
    { code: 'ka', name: 'ქართული', flag: '🇬🇪' },
    { code: 'ar', name: 'العربية', flag: '🇸🇦' },
    { code: 'ru', name: 'Русский', flag: '🇷🇺' },
    { code: 'it', name: 'Italiano', flag: '🇮🇹' },
    { code: 'zh', name: '中文', flag: '🇨🇳' },
  ];

  function uid() {
    return `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
  }

  function read(key) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  }

  function write(key, data) {
    localStorage.setItem(key, JSON.stringify(data));
  }

  function getLang() {
    return localStorage.getItem(LANG_KEY) || 'en';
  }

  function setLang(code) {
    localStorage.setItem(LANG_KEY, code);
  }

  function langInfo(code) {
    return LANGUAGES.find((l) => l.code === code) || LANGUAGES[0];
  }

  function defaultStats() {
    return {
      attempts: 0,
      correct: 0,
      wrong: 0,
      avgScore: 0,
      pronunciationAvg: 70,
      grammarAvg: 70,
      lastScore: 0,
      lastPracticed: null,
    };
  }

  function updateStats(stats, result) {
    const s = { ...defaultStats(), ...stats };
    s.attempts += 1;
    const score = Number(result.score) || 0;
    s.lastScore = score;
    s.lastPracticed = new Date().toISOString();
    if (score >= 70) s.correct += 1;
    else s.wrong += 1;
    s.avgScore = Math.round(
      ((s.avgScore * (s.attempts - 1)) + score) / s.attempts,
    );
    const pron = Number(result.pronunciation_score) || score;
    const gram = Number(result.grammar_score) || score;
    s.pronunciationAvg = Math.round(
      ((s.pronunciationAvg * (s.attempts - 1)) + pron) / s.attempts,
    );
    s.grammarAvg = Math.round(
      ((s.grammarAvg * (s.attempts - 1)) + gram) / s.attempts,
    );
    return s;
  }

  function srsWeight(stats) {
    const s = { ...defaultStats(), ...stats };
    if (s.attempts === 0) return 2;
    const errRate = s.wrong / Math.max(s.attempts, 1);
    let w = 1 + errRate * 2 + (100 - s.avgScore) / 50 + (100 - s.pronunciationAvg) / 80;
    if (s.avgScore >= 90 && s.attempts >= 5) w *= 0.4;
    return Math.max(0.2, w);
  }

  function learningLevel(stats) {
    const s = { ...defaultStats(), ...stats };
    if (s.attempts < 2) return '🟡 Geliştirilmeli';
    if (s.avgScore >= 85) return '🟢 İyi';
    if (s.avgScore >= 60) return '🟡 Geliştirilmeli';
    return '🔴 Tekrar edilmeli';
  }

  function saveWord(entry) {
    const items = read(WORDS_KEY);
    const lang = entry.target_lang || getLang();
    const dup = items.find(
      (w) => w.word_tr?.toLowerCase() === entry.word_tr?.toLowerCase() && w.target_lang === lang,
    );
    const record = {
      id: dup?.id || uid(),
      created_at: dup?.created_at || new Date().toISOString(),
      stats: dup?.stats || defaultStats(),
      ...entry,
      target_lang: lang,
    };
    if (dup) {
      const idx = items.indexOf(dup);
      items[idx] = { ...dup, ...record, stats: dup.stats };
    } else {
      items.unshift(record);
    }
    write(WORDS_KEY, items);
    return record;
  }

  function saveSentence(entry) {
    const items = read(SENTENCES_KEY);
    const lang = entry.target_lang || getLang();
    const dup = items.find(
      (s) => s.tr_sentence === entry.tr_sentence && s.target_lang === lang,
    );
    const record = {
      id: dup?.id || uid(),
      created_at: dup?.created_at || new Date().toISOString(),
      stats: dup?.stats || defaultStats(),
      ...entry,
      target_lang: lang,
    };
    if (dup) {
      const idx = items.indexOf(dup);
      items[idx] = { ...dup, ...record, stats: dup.stats };
    } else {
      items.unshift(record);
    }
    write(SENTENCES_KEY, items);
    return record;
  }

  function getWords(lang) {
    const code = lang || getLang();
    return read(WORDS_KEY).filter((w) => w.target_lang === code);
  }

  function getSentences(lang) {
    const code = lang || getLang();
    return read(SENTENCES_KEY).filter((s) => s.target_lang === code);
  }

  function getWordById(id) {
    return read(WORDS_KEY).find((w) => w.id === id);
  }

  function getSentenceById(id) {
    return read(SENTENCES_KEY).find((s) => s.id === id);
  }

  function recordPractice(contentType, contentId, result) {
    const results = read(RESULTS_KEY);
    results.unshift({
      id: uid(),
      content_type: contentType,
      content_id: contentId,
      score: result.score,
      grammar_score: result.grammar_score,
      pronunciation_score: result.pronunciation_score,
      vocabulary_score: result.vocabulary_score,
      naturalness_score: result.naturalness_score,
      user_answer: result.user_answer,
      correct_answer: result.correct_answer,
      created_at: new Date().toISOString(),
    });
    write(RESULTS_KEY, results.slice(0, 500));

    const key = contentType === 'word' ? WORDS_KEY : SENTENCES_KEY;
    const items = read(key);
    const idx = items.findIndex((i) => i.id === contentId);
    if (idx >= 0) {
      items[idx].stats = updateStats(items[idx].stats, result);
      write(key, items);
    }
  }

  function searchItems(query, lang) {
    const q = (query || '').trim().toLowerCase();
    if (!q) return { words: getWords(lang), sentences: getSentences(lang) };
    const words = getWords(lang).filter(
      (w) => w.word_tr?.toLowerCase().includes(q)
        || w.target_word?.toLowerCase().includes(q),
    );
    const sentences = getSentences(lang).filter(
      (s) => s.tr_sentence?.toLowerCase().includes(q)
        || s.target_sentence?.toLowerCase().includes(q),
    );
    return { words, sentences };
  }

  function pickQuizItems(type, count, lang, hardOnly) {
    const items = type === 'word' ? getWords(lang) : getSentences(lang);
    if (!items.length) return [];
    let pool = items.map((item) => ({ item, weight: srsWeight(item.stats) }));
    if (hardOnly) {
      pool = pool.filter(
        (p) => p.item.stats?.avgScore < 75 || p.item.stats?.attempts < 2,
      );
      if (!pool.length) pool = items.map((item) => ({ item, weight: srsWeight(item.stats) }));
    }
    const picked = [];
    const working = [...pool];
    const n = Math.min(count, working.length);
    for (let i = 0; i < n; i += 1) {
      const total = working.reduce((s, p) => s + p.weight, 0);
      let r = Math.random() * total;
      let chosen = 0;
      for (let j = 0; j < working.length; j += 1) {
        r -= working[j].weight;
        if (r <= 0) {
          chosen = j;
          break;
        }
      }
      picked.push(working[chosen].item);
      working.splice(chosen, 1);
    }
    return picked;
  }

  global.LearnStorage = {
    LANGUAGES,
    WORDS_KEY,
    SENTENCES_KEY,
    getLang,
    setLang,
    langInfo,
    saveWord,
    saveSentence,
    getWords,
    getSentences,
    getWordById,
    getSentenceById,
    recordPractice,
    searchItems,
    pickQuizItems,
    srsWeight,
    learningLevel,
    defaultStats,
  };
}(typeof window !== 'undefined' ? window : globalThis));

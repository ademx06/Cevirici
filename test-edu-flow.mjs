import { JSDOM } from 'jsdom';
import fs from 'fs';

const BASE = 'http://127.0.0.1:8780';

function setupDom(corrupt = false) {
  if (corrupt) {
    // Simulate iPhone localStorage corruption after several sessions
    const store = {
      edu_profile_v2: JSON.stringify({
        targetLang: 'en',
        weakAreas: 'conversation',
        strongAreas: 'speaking',
        newWords: 'hello',
        sessionLog: { bad: true },
        dailyStats: 'x',
      }),
      edu_history_v2: '{"not":"array"}',
      edu_chat_v3: JSON.stringify([
        { role: 'user', text: 'Hi', audio: 'AAAA' },
        { role: 'teacher', teacherEn: 123, teacherTr: null, audio: 'x'.repeat(5000) },
      ]),
    };
    const html = fs.readFileSync('education.html', 'utf8').replace('education.js?v=10', 'education.js');
    const dom = new JSDOM(html, {
      url: `${BASE}/education.html`,
      runScripts: 'dangerously',
      pretendToBeVisual: true,
      beforeParse(win) {
        win.localStorage.getItem = (k) => store[k] ?? null;
        win.localStorage.setItem = (k, v) => { store[k] = v; };
        win.localStorage.removeItem = (k) => { delete store[k]; };
        win.fetch = (url, opts = {}) => globalThis.fetch(url.startsWith('http') ? url : `${BASE}${url}`, opts);
        win.MediaRecorder = class {
          constructor() { this.mimeType = 'audio/mp4'; this.state = 'inactive'; }
          start() { this.state = 'recording'; }
          stop() { this.state = 'inactive'; this.onstop?.(); }
          requestData() {}
        };
        win.MediaRecorder.isTypeSupported = () => true;
        win.navigator.mediaDevices = { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) };
        win.confirm = () => true;
      },
    });
    return dom;
  }

  const html = fs.readFileSync('education.html', 'utf8').replace('education.js?v=10', 'education.js');
  return new JSDOM(html, {
    url: `${BASE}/education.html`,
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    beforeParse(win) {
      win.fetch = (url, opts = {}) => globalThis.fetch(url.startsWith('http') ? url : `${BASE}${url}`, opts);
      win.MediaRecorder = class {
        constructor() { this.mimeType = 'audio/mp4'; this.state = 'inactive'; }
        start() { this.state = 'recording'; }
        stop() { this.state = 'inactive'; this.onstop?.(); }
        requestData() {}
      };
      win.MediaRecorder.isTypeSupported = () => true;
      win.navigator.mediaDevices = { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) };
    },
  });
}

async function sendAndWait(dom, text) {
  const win = dom.window;
  const input = win.document.getElementById('textInput');
  const send = win.document.getElementById('sendBtn');
  input.value = text;
  send.click();
  await new Promise((r) => setTimeout(r, 1500));
  const errEl = win.document.getElementById('errorBox');
  const err = errEl && !errEl.classList.contains('hidden') ? errEl.textContent.trim() : '';
  return err;
}

async function run(label, corrupt) {
  const dom = setupDom(corrupt);
  await new Promise((r) => setTimeout(r, 800));
  const steps = [
    'Hello, how are you?',
    'yardım ben bugün işe gideceğim',
    'I went to work today',
    'How is the weather?',
  ];
  for (const t of steps) {
    const err = await sendAndWait(dom, t);
    if (err) {
      console.log(`FAIL [${label}] after "${t}": ${err}`);
      return false;
    }
  }
  const rows = dom.window.document.querySelectorAll('.chat-row').length;
  console.log(`OK [${label}] rows=${rows}`);
  return true;
}

const a = await run('clean', false);
const b = await run('corrupt-storage', true);
process.exit(a && b ? 0 : 1);

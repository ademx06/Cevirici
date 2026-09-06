"""Eşzamanlı Konuşma — canlı STT+çeviri duman testleri."""
from __future__ import annotations
import re, subprocess, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent

class Structure(unittest.TestCase):
    def test_files(self):
        for n in ("live-talk.html","live-talk.js","live-talk.css"):
            self.assertTrue((ROOT/n).is_file(), n)
    def test_syntax(self):
        r=subprocess.run(["node","--check",str(ROOT/"live-talk.js")],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
    def test_ids(self):
        html=(ROOT/"live-talk.html").read_text(encoding="utf-8")
        js=(ROOT/"live-talk.js").read_text(encoding="utf-8")
        missing=set(re.findall(r"\$\('([^']+)'\)", js))-set(re.findall(r'id="([^"]+)"', html))
        self.assertFalse(missing, sorted(missing))
    def test_streaming_architecture(self):
        js=(ROOT/"live-talk.js").read_text(encoding="utf-8")
        html=(ROOT/"live-talk.html").read_text(encoding="utf-8")
        self.assertIn("/api/stt", js)
        self.assertIn("/api/translate", js)
        self.assertIn("recorder.start(SLICE_MS)", js)
        self.assertIn("runLiveStt", js)
        self.assertIn("scheduleTranslate", js)
        self.assertIn("translateInflight", js)
        self.assertIn("TR_MAX_WAIT_MS", js)
        self.assertIn("isMeaningfulPhrase", js)
        self.assertIn("ltLiveBox", js)
        self.assertIn("CANLI ÇEVİRİ", html)
        self.assertIn("force: '1'", js)
        self.assertIn("maybeSpeakTranslation", js)
        self.assertIn("enqueueTts", js)
        self.assertIn("spokenTrans", js)
        self.assertIn("pendingSide", js)
        self.assertIn("releaseHardware", js)
        self.assertIn("finalizeUtterance", js)
        self.assertIn("/api/tts", js)
        self.assertNotRegex(js, r"(?<![\w/])MicHold\.create")
        # Yorum dışında gerçek çağrı olmamalı
        code_only = "\n".join(
            ln for ln in js.splitlines() if not ln.lstrip().startswith("*") and not ln.lstrip().startswith("//")
        )
        self.assertNotIn("MicHold.create", code_only)
        self.assertNotIn("/api/process", code_only)
        self.assertNotIn("mic-hold.js", html)
        self.assertIn("rollSegment", js)
        self.assertIn("scheduleRoll", js)
        self.assertIn("Sesli çeviri", html)
        self.assertIn("ensureMicStream", js)
        self.assertIn("scheduleStableSpeak", js)
        self.assertIn("micStream", js)
        # Release must not stop tracks (re-permission / 2nd utterance break)
        release = js.split("function releaseHardware", 1)[1].split("function tryStartPending", 1)[0]
        self.assertNotIn("getTracks().forEach", release)
        self.assertNotIn("t.stop()", release)

    def test_no_education_dependency(self):
        js=(ROOT/"live-talk.js").read_text(encoding="utf-8")
        self.assertNotIn("education", js.lower())
        self.assertNotIn("/api/tutor", js)

class Heuristics(unittest.TestCase):
    def test_heuristics(self):
        script=r"""
const fs=require('fs'); const vm=require('vm');
const code=fs.readFileSync('live-talk.js','utf8');
const sandbox={window:{},document:{createElement:()=>({setAttribute(){},classList:{add(){},remove(){},toggle(){}},style:{},appendChild(){}}),getElementById:()=>({classList:{add(){},remove(){},toggle(){},contains:()=>false},textContent:'',value:'',style:{},appendChild(){},addEventListener(){}}),body:{appendChild(){}},querySelectorAll:()=>[]},console,navigator:{mediaDevices:null},setTimeout,clearTimeout,fetch:async()=>({ok:true,text:async()=>'{}',json:async()=>({}),blob:async()=>new Blob()})};
vm.createContext(sandbox); vm.runInContext(code,sandbox);
const H=sandbox.window.LiveTalkHeuristics;
function assert(c,m){if(!c){console.error(m);process.exit(1)}}
assert(!H.isMeaningfulPhrase('Ben'),'short');
assert(!H.isMeaningfulPhrase('Merhaba'),'greeting-short');
assert(H.isMeaningfulPhrase('Merhaba yarın seninle bir kafede'),'phrase');
assert(H.isMeaningfulPhrase('Yarın buluşalım.'), 'punct');
assert(!H.shouldRetranslate('a b c d','a b c d'),'same');
assert(H.shouldRetranslate('Merhaba yarın','Merhaba yarın seninle bir kafede buluşmak'),'grow');
console.log('ok');
"""
        r=subprocess.run(["node","-e",script],cwd=str(ROOT),capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

class ApiSmoke(unittest.TestCase):
    def test_progressive_tr_en(self):
        import server
        parts=["Merhaba yarın seninle bir kafede","Merhaba yarın seninle bir kafede buluşmak istiyorum. Saat üç uygun mu?"]
        outs=[server.translate_text(t,"tr","en") for t in parts]
        self.assertTrue(all(outs))
        final=outs[-1].lower()
        self.assertTrue(any(k in final for k in ("meet","cafe","café","three","3","time")), final)
    def test_progressive_en_tr(self):
        import server
        parts=["Hello tomorrow I want to meet you at a cafe","Hello tomorrow I want to meet you at a cafe. Is three o'clock okay?"]
        outs=[server.translate_text(t,"en","tr") for t in parts]
        self.assertTrue(all(outs))
        final=outs[-1].lower()
        self.assertTrue(any(k in final for k in ("yarın","buluş","kafe","üç","3","uygun")), final)
    def test_force_keeps_direction_on_partial(self):
        """force=1 partial TR→EN yönünü pair_safe sapmasından korur."""
        import server
        # Doğrudan motor: force yolu translate_text kullanır
        partial = "Yarın seninle"
        forced = server.translate_text(partial, "tr", "en")
        self.assertTrue(forced)
        # İngilizce karakter / kelime beklenir; Türkçe cümle olarak kalmamalı
        low = forced.lower()
        self.assertTrue(any(k in low for k in ("tomorrow", "you", "with", "meet", "want")), forced)
    def test_audio_stt_then_translate(self):
        import server
        from pathlib import Path as P
        audio=P("/tmp/live_talk_audio/tr.mp3")
        if not audio.exists(): self.skipTest("no audio")
        text,_,_=server.transcribe_audio(audio.read_bytes(),"tr")
        self.assertTrue(text)
        tr=server.translate_text(text,"tr","en")
        self.assertTrue(tr)

if __name__=="__main__":
    unittest.main()

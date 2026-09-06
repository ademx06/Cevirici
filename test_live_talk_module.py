"""Eşzamanlı Konuşma modül dosya bütünlüğü."""
from __future__ import annotations
import re, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent

class LiveTalkModuleTests(unittest.TestCase):
    def test_files_exist(self):
        for n in ("live-talk.html","live-talk.js","live-talk.css"):
            self.assertTrue((ROOT/n).is_file(), n)
    def test_menu_link(self):
        html=(ROOT/"index.html").read_text(encoding="utf-8")
        self.assertIn('href="live-talk.html"', html)
        self.assertIn("Eşzamanlı Konuşma", html)
    def test_ids_aligned(self):
        html=(ROOT/"live-talk.html").read_text(encoding="utf-8")
        js=(ROOT/"live-talk.js").read_text(encoding="utf-8")
        missing=set(re.findall(r"\$\('([^']+)'\)", js))-set(re.findall(r'id="([^"]+)"', html))
        self.assertFalse(missing, sorted(missing))
    def test_realtime_not_classic_blob_path(self):
        js=(ROOT/"live-talk.js").read_text(encoding="utf-8")
        html=(ROOT/"live-talk.html").read_text(encoding="utf-8")
        self.assertIn("/api/stt", js)
        self.assertIn("/api/translate", js)
        self.assertIn("runLiveStt", js)
        code_only = "\n".join(
            ln for ln in js.splitlines() if not ln.lstrip().startswith("*") and not ln.lstrip().startswith("//")
        )
        self.assertNotIn("/api/process", code_only)
        self.assertNotIn("MicHold.create", code_only)
        self.assertNotIn("mic-hold.js", html)
        self.assertIn("recorder.start(SLICE_MS)", js)
    def test_langs_match_app(self):
        js=(ROOT/"live-talk.js").read_text(encoding="utf-8")
        app=(ROOT/"app.js").read_text(encoding="utf-8")
        for code in ("tr","en","ka","ru","es","de","fr","ar","it","zh"):
            self.assertIn("code: '%s'"%code if False else code, js)
            # live-talk uses code: 'xx'
            self.assertIn("code: '%s'" % code, js)
            self.assertIn("code: '%s'" % code, app)

if __name__=="__main__":
    unittest.main()

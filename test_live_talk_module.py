"""Eşzamanlı Konuşma modülü — dosya bütünlüğü + forced-source duman testleri."""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent


class LiveTalkModuleTests(unittest.TestCase):
    def test_module_files_exist(self):
        for name in ("live-talk.html", "live-talk.js", "live-talk.css"):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_menu_links_to_live_talk(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="live-talk.html"', html)
        self.assertIn("Eşzamanlı Konuşma", html)

    def test_html_js_ids_aligned(self):
        html = (ROOT / "live-talk.html").read_text(encoding="utf-8")
        js = (ROOT / "live-talk.js").read_text(encoding="utf-8")
        html_ids = set(re.findall(r'id="([^"]+)"', html))
        js_ids = set(re.findall(r"\$\('([^']+)'\)", js))
        missing = js_ids - html_ids
        self.assertFalse(missing, f"JS refers to missing HTML ids: {sorted(missing)}")

    def test_uses_forced_source_process_api(self):
        js = (ROOT / "live-talk.js").read_text(encoding="utf-8")
        self.assertIn("/api/process", js)
        self.assertIn("source:", js)
        self.assertIn("forcedSource", js)
        self.assertIn("MicHold.create", js)
        self.assertIn("AUTO_DETECT: false", js)
        self.assertIn("processAudio", js)

    def test_does_not_touch_education_assets(self):
        js = (ROOT / "live-talk.js").read_text(encoding="utf-8")
        self.assertNotIn("education", js.lower())
        self.assertNotIn("/api/tutor", js)
        self.assertNotIn("/api/education", js)

    def test_supported_langs_match_app(self):
        js = (ROOT / "live-talk.js").read_text(encoding="utf-8")
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        for code in ("tr", "en", "ka", "ru", "es", "de", "fr", "ar", "it", "zh"):
            self.assertIn(f"code: '{code}'", js)
            self.assertIn(f"code: '{code}'", app)

    def test_scripts_loaded_in_html(self):
        html = (ROOT / "live-talk.html").read_text(encoding="utf-8")
        self.assertIn("mic-hold.js", html)
        self.assertIn("live-talk.js", html)
        self.assertIn("live-talk.css", html)
        self.assertNotIn("app.js", html)


class LiveTalkForcedSourceSmoke(unittest.TestCase):
    def test_forced_pairs_keep_source_and_target(self):
        import server

        pairs = [
            ("tr", "en", "Merhaba, bugün nasılsın?"),
            ("en", "tr", "Hello, how are you today?"),
            ("tr", "ka", "Merhaba"),
            ("ka", "tr", "გამარჯობა"),
            ("tr", "ru", "Merhaba"),
            ("ru", "tr", "Здравствуйте"),
            ("tr", "es", "Merhaba"),
            ("es", "tr", "Hola"),
        ]

        for src, tgt, original in pairs:
            with self.subTest(src=src, tgt=tgt):
                def fake_forced(data, source_lang, timings=None, _src=src, _orig=original):
                    self.assertEqual(source_lang, _src)
                    return _orig, source_lang

                def fake_translate(text, fr, to, _src=src, _tgt=tgt, _orig=original):
                    self.assertEqual(fr, _src)
                    self.assertEqual(to, _tgt)
                    self.assertEqual(text, _orig)
                    return f"T[{fr}->{to}] {text}"

                with patch.object(server, "transcribe_forced", side_effect=fake_forced), \
                     patch.object(server, "translate_text", side_effect=fake_translate):
                    r = server.process_speech_segment(
                        b"fake", src, tgt, None, {}, forced_source=src,
                    )
                self.assertEqual(r["from"], src)
                self.assertEqual(r["to"], tgt)
                self.assertEqual(r["original"], original)
                self.assertEqual(r["translated"], f"T[{src}->{tgt}] {original}")
                self.assertTrue(r.get("forced_source"))
                self.assertEqual(r.get("stt_language"), src)

    def test_invalid_forced_source_errors(self):
        import server
        with self.assertRaises(ValueError):
            server.process_speech_segment(b"x", "tr", "en", None, {}, forced_source="xx")


if __name__ == "__main__":
    unittest.main()

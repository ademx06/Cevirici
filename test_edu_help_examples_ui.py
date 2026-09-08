#!/usr/bin/env python3
"""Frontend: sanitizeMsgs must keep helpExamples so render() shows cards."""
from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).resolve().parent / "education.js"
src = JS.read_text(encoding="utf-8")


def test_sanitize_preserves_help_examples():
    # Source-level contract: sanitizeChatMsg must keep helpExamples / helpTtsPairs
    assert "helpExamples" in src
    assert "sanitizeHelpExamples" in src
    assert re.search(r"helpExamples,\s*\n\s*helpTtsPairs", src) or "helpExamples," in src
    # Old bug: sanitize returned only speakTr/time without help fields
    # Ensure speakText + helpExamples both appear in sanitizeChatMsg return
    m = re.search(r"function sanitizeChatMsg\([\s\S]*?\n\}", src)
    assert m, "sanitizeChatMsg missing"
    body = m.group(0)
    assert "helpExamples" in body
    assert "helpTtsPairs" in body
    assert "helpStructure" in body
    assert "speakText" in body
    print("TEST sanitize preserves help OK")


def test_render_uses_help_blocks():
    assert "chat-help-examples" in src
    assert "chat-help-listen" in src
    assert "helpTtsPairs" in src
    # Fallback from TTS pairs when examples empty
    assert "helpTtsPairs.map" in src or "m.helpTtsPairs" in src
    print("TEST render help blocks OK")


def test_append_teacher_normalizes_examples():
    m = re.search(r"function appendTeacherMsg\([\s\S]*?\n\}", src)
    assert m
    body = m.group(0)
    assert "help_examples" in body
    assert "sanitizeHelpExamples" in body
    print("TEST appendTeacherMsg OK")


if __name__ == "__main__":
    test_sanitize_preserves_help_examples()
    test_render_uses_help_blocks()
    test_append_teacher_normalizes_examples()
    print("ALL help UI frontend tests passed")

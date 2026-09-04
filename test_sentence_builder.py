#!/usr/bin/env python3
"""Cümle kurma iskelesi — beginner sentence building."""
from __future__ import annotations

from education_engine import default_profile, process_turn


def fake(t, f, to):
    return t


def body(r):
    return ((r.get("teacher_en") or "") + "\n" + (r.get("teacher_tr") or "")).lower()


def test_i_am_read_scaffold():
    p = default_profile()
    r1 = process_turn("I am read a book.", "en", "en", [], p, translate_fn=fake)
    assert r1.get("type") == "scaffold_produce"
    b1 = body(r1)
    assert "verb-ing" in b1 or "reading" in b1
    assert "i am reading a book" in b1
    p = r1["profile"]
    assert p.get("scaffoldMode") == "produce"

    r2 = process_turn("I am reading a book.", "en", "en", [], p, translate_fn=fake)
    assert r2.get("type") == "scaffold_transfer"
    assert "watching" in body(r2) or "televizyon" in body(r2)
    p = r2["profile"]
    assert p.get("scaffoldMode") == "transfer"

    r3 = process_turn("I am watching TV.", "en", "en", [], p, translate_fn=fake)
    assert r3.get("type") == "scaffold_success"
    assert not (r3.get("profile") or {}).get("scaffoldMode")
    print("TEST I am read → produce → transfer OK")


def test_he_is_story_hint():
    p = default_profile()
    r1 = process_turn("He is a happy story.", "en", "en", [], p, translate_fn=fake)
    assert r1.get("type") == "scaffold_hint"
    b1 = body(r1)
    assert "he" in b1 and "it" in b1
    assert "it is a happy story" not in (r1.get("teacher_en") or "").lower().split("so do")[0] or "he or **it**" in b1
    # Should not dump full answer as only content without asking
    assert "?" in (r1.get("teacher_en") or "")
    p = r1["profile"]

    r2 = process_turn("it", "en", "en", [], p, translate_fn=fake)
    assert r2.get("type") == "scaffold_produce"
    assert "it is a happy story" in body(r2)
    p = r2["profile"]

    r3 = process_turn("It is a happy story.", "en", "en", [], p, translate_fn=fake)
    assert r3.get("type") == "scaffold_transfer"
    assert "book" in body(r3)
    p = r3["profile"]

    r4 = process_turn("It is a book.", "en", "en", [], p, translate_fn=fake)
    assert r4.get("type") == "scaffold_success"
    print("TEST he/it scaffold OK")


def test_correct_no_scaffold():
    r = process_turn("It is a story.", "en", "en", [], default_profile(), translate_fn=fake)
    assert r.get("type") not in ("scaffold_hint", "scaffold_produce")
    print("TEST correct sentence no scaffold OK")


if __name__ == "__main__":
    test_i_am_read_scaffold()
    test_he_is_story_hint()
    test_correct_no_scaffold()
    print("\nAll sentence-builder tests passed.")

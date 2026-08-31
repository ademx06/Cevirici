"""Telegram bot — /link ile güncel adres (iPhone'dan kendin al)."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from public_url import persist_public_url, resolve_public_url

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"

LINK_CMDS = frozenset({"/start", "/link", "/adres", "start", "link", "adres", "başlat"})


def _load_env() -> None:
    if not ENV_FILE.is_file():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _find_tunnel_url() -> str:
    return resolve_public_url()


def _link_message(url: str) -> str:
    if not url:
        return (
            "⚠️ Sunucu şu an kapalı veya adres henüz hazır değil.\n\n"
            "Birkaç dakika sonra tekrar /link yaz."
        )
    return (
        f"📱 Güncel link:\n\n{url}\n\n"
        f"🎓 Eğitim:\n{url}/education.html?v=34\n\n"
        f"🌍 Çeviri:\n{url}/translate.html\n\n"
        "💡 Link değişince buraya /link yaz — yeni adresi gönderirim."
    )


def send_telegram(chat_id: str | int, text: str, token: str | None = None) -> bool:
    tok = (token or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
    if not tok:
        return False
    body = urlencode({"chat_id": str(chat_id), "text": text}).encode()
    try:
        req = Request(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            data=body,
            headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        return bool(data.get("ok"))
    except Exception:
        return False


def _handle_message(chat_id: int, text: str) -> None:
    cmd = (text or "").strip().lower().split()[0] if text else ""
    if cmd in LINK_CMDS or (text or "").strip().lower() in LINK_CMDS:
        url = _find_tunnel_url()
        if url:
            persist_public_url(url)
        send_telegram(chat_id, _link_message(url))
    elif cmd in ("/help", "help", "yardım", "/yardım"):
        send_telegram(
            chat_id,
            "Komutlar:\n/link — güncel uygulama adresi\n/start — aynı\n\n"
            "Link değişince /link yazman yeterli.",
        )


def poll_forever(interval: float = 2.0) -> None:
    _load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return
    offset = 0
    while True:
        try:
            req = Request(
                f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=25",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode())
            for upd in data.get("result", []):
                offset = max(offset, upd.get("update_id", 0) + 1)
                msg = upd.get("message") or upd.get("edited_message") or {}
                chat = msg.get("chat") or {}
                chat_id = chat.get("id")
                text = msg.get("text") or ""
                if chat_id and text:
                    _handle_message(chat_id, text)
        except Exception:
            time.sleep(interval)
        else:
            time.sleep(0.5)


def start_telegram_bot() -> threading.Thread | None:
    _load_env()
    if not os.environ.get("TELEGRAM_BOT_TOKEN", "").strip():
        return None
    t = threading.Thread(target=poll_forever, name="telegram-bot", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    _load_env()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    url = _find_tunnel_url()
    if chat:
        send_telegram(chat, _link_message(url))
    print("Telegram bot dinliyor… /link için")
    poll_forever()

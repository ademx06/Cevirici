"""Her ortamda (Render, Railway, Cloudflare tünel) sabit uygulama adresini bul."""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
URL_FILE = ROOT / "PUBLIC_URL.txt"
TUNNEL_LOGS = (
    Path("/tmp/cloudflared-live.log"),
    Path("/tmp/sesli-cevirmen-tunnel.log"),
    Path("/tmp/cloudflared-edu.log"),
)


def _normalize(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if not u.startswith("http"):
        u = f"https://{u}"
    return u


def resolve_public_url() -> str:
    for key in ("PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL", "RAILWAY_PUBLIC_DOMAIN"):
        v = _normalize(os.environ.get(key, ""))
        if v:
            return v

    if URL_FILE.is_file():
        u = _normalize(URL_FILE.read_text(encoding="utf-8"))
        if u.startswith("https://"):
            return u

    for log in TUNNEL_LOGS:
        if not log.is_file():
            continue
        matches = re.findall(
            r"https://[a-z0-9-]+\.trycloudflare\.com",
            log.read_text(encoding="utf-8", errors="ignore"),
        )
        if matches:
            return matches[-1]
    return ""


def persist_public_url(url: str) -> None:
    u = _normalize(url)
    if u:
        URL_FILE.write_text(u + "\n", encoding="utf-8")

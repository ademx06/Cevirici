#!/usr/bin/env bash
# Sesli Çevirmen — sunucu başlatıcı
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${PORT:-8780}"

echo "▶ Sunucu başlatılıyor (port $PORT)..."
echo "   Dizin: $ROOT"
exec python3 server.py

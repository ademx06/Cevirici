#!/usr/bin/env bash
# GEÇİCİ tünel — her başlatmada YENİ trycloudflare.com adresi üretir.
# Ana ekrana eklediyseniz adres değişince kısayol çalışmaz.
# Sabit adres için: docs/SABIT-ADRES.md
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8780}"
LOG="/tmp/sesli-cevirmen-tunnel.log"
URL_FILE="$ROOT/PUBLIC_URL.txt"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "❌ cloudflared bulunamadı."
  echo "   macOS: brew install cloudflared"
  echo "   Linux: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
  exit 1
fi

echo "⚠️  UYARI: Quick tunnel kullanıyorsunuz."
echo "   Her yeniden başlatmada adres DEĞİŞİR — ana ekran kısayolu bozulabilir."
echo "   Sabit adres için docs/SABIT-ADRES.md dosyasına bakın."
echo ""

cloudflared tunnel --url "http://127.0.0.1:$PORT" 2>&1 | tee "$LOG" &
TUNNEL_PID=$!

echo "Tünel başlatıldı (pid $TUNNEL_PID). Adres bekleniyor..."
for i in $(seq 1 30); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | head -1 || true)
  if [[ -n "$URL" ]]; then
    echo "$URL" > "$URL_FILE"
    echo ""
    echo "✅ Geçici adres: $URL"
    echo "   (Kaydedildi: PUBLIC_URL.txt)"
    echo ""
    echo "iPhone: Safari → bu adres → Paylaş → Ana Ekrana Ekle"
    exit 0
  fi
  sleep 1
done

echo "❌ Adres alınamadı. Log: $LOG"
exit 1

#!/usr/bin/env bash
# Tek komutla sunucu + internet adresi (Mac/Linux)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${PORT:-8780}"
LOG="/tmp/sesli-cevirmen-tunnel.log"
URL_FILE="$ROOT/PUBLIC_URL.txt"
PID_FILE="$ROOT/.server.pid"

stop_old() {
  if [[ -f "$PID_FILE" ]]; then
    old=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
      echo "⏹ Eski sunucu durduruluyor (pid $old)..."
      kill "$old" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$PID_FILE"
  fi
  pkill -f "cloudflared tunnel --url http://127.0.0.1:$PORT" 2>/dev/null || true
}

start_server() {
  echo "▶ Sunucu başlatılıyor (port $PORT)..."
  nohup python3 server.py > /tmp/sesli-cevirmen-server.log 2>&1 &
  echo $! > "$PID_FILE"
  for i in $(seq 1 30); do
    if curl -s -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
      echo "✅ Sunucu hazır"
      return 0
    fi
    sleep 2
  done
  echo "❌ Sunucu başlamadı. Log: /tmp/sesli-cevirmen-server.log"
  exit 1
}

start_tunnel() {
  if ! command -v cloudflared >/dev/null 2>&1; then
    echo ""
    echo "❌ cloudflared yüklü değil."
    echo "   Mac:  brew install cloudflared"
    echo "   Sonra bu scripti tekrar çalıştır."
    echo ""
    echo "📱 Sadece aynı Wi-Fi'de iPhone kullanacaksan tünel şart değil:"
    IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "BILGISAYAR-IP")
    echo "   http://${IP}:$PORT"
    exit 0
  fi

  echo "▶ İnternet adresi oluşturuluyor..."
  : > "$LOG"
  nohup cloudflared tunnel --url "http://127.0.0.1:$PORT" >> "$LOG" 2>&1 &

  for i in $(seq 1 45); do
    URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | head -1 || true)
    if [[ -n "$URL" ]]; then
      echo "$URL" > "$URL_FILE"
      echo ""
      echo "════════════════════════════════════════════"
      echo "  📱 iPhone'dan bu adresi aç:"
      echo ""
      echo "  $URL"
      echo ""
      echo "  Eğitim: ${URL}/education.html"
      echo "  Çeviri: ${URL}/translate.html"
      echo "════════════════════════════════════════════"
      echo ""
      echo "💾 Adres kaydedildi: $URL_FILE"
      echo "⚠️  Bilgisayarı kapatırsan veya scripti tekrar"
      echo "   çalıştırırsan adres DEĞİŞEBİLİR."
      echo "   Sabit adres: docs/SABIT-ADRES.md"
      return 0
    fi
    sleep 1
  done
  echo "❌ Tünel adresi alınamadı. Log: $LOG"
  exit 1
}

case "${1:-start}" in
  start)
    stop_old
    start_server
    start_tunnel
    ;;
  stop)
    stop_old
    echo "✅ Durduruldu"
    ;;
  url)
    if [[ -f "$URL_FILE" ]]; then
      cat "$URL_FILE"
    else
      echo "Henüz adres yok. Önce: ./scripts/baslat.sh"
      exit 1
    fi
    ;;
  status)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "Sunucu: çalışıyor (pid $(cat "$PID_FILE"))"
    else
      echo "Sunucu: kapalı"
    fi
    if [[ -f "$URL_FILE" ]]; then
      echo "Son adres: $(cat "$URL_FILE")"
    fi
    ;;
  *)
    echo "Kullanım: $0 [start|stop|url|status]"
    ;;
esac

#!/usr/bin/env bash
# Tek komutla sunucu + internet adresi (Mac/Linux)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${PORT:-8780}"
LOG="/tmp/sesli-cevirmen-tunnel.log"
URL_FILE="$ROOT/PUBLIC_URL.txt"
PID_FILE="$ROOT/.server.pid"
ENV_FILE="$ROOT/.env"

load_env() {
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi
}

load_env

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

notify_link() {
  local url="$1"
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    local msg
    msg="📱 Sesli Çevirmen — güncel link:%0A%0A${url}%0A%0A🎓 Eğitim:%0A${url}/education.html?v=17%0A%0A🌍 Çeviri:%0A${url}/translate.html"
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_CHAT_ID}" \
      -d "text=${msg}" \
      -d "disable_web_page_preview=false" >/dev/null 2>&1 \
      && echo "📲 Link Telegram'a gönderildi (@translate_cevirici_bot)" || echo "⚠️  Telegram gönderilemedi — ./scripts/telegram-kur.sh"
  else
    echo "ℹ️  Telegram yok — bir kez: ./scripts/telegram-kur.sh"
  fi
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
      notify_link "$URL"
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
      echo "   iPhone link panosu: YENI-LINK-NEREDEN.md"
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
  telegram)
    load_env
    if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
      echo "Önce: ./scripts/telegram-kur.sh"
      exit 1
    fi
    if [[ -f "$URL_FILE" ]]; then
      notify_link "$(cat "$URL_FILE")"
    else
      echo "Henüz link yok. Önce: ./scripts/baslat.sh start"
      exit 1
    fi
    ;;
  *)
    echo "Kullanım: $0 [start|stop|url|status|telegram]"
    ;;
esac

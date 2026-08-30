#!/usr/bin/env bash
# Telegram bot kurulumu — bir kez çalıştır, sonra baslat.sh linki otomatik gönderir
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"
BOT_USER="${1:-translate_cevirici_bot}"

load_env() {
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi
}

save_env() {
  local token="$1" chat="$2"
  touch "$ENV_FILE"
  grep -v '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" 2>/dev/null | grep -v '^TELEGRAM_CHAT_ID=' > "${ENV_FILE}.tmp" || true
  {
    cat "${ENV_FILE}.tmp" 2>/dev/null || true
    echo "TELEGRAM_BOT_TOKEN=${token}"
    echo "TELEGRAM_CHAT_ID=${chat}"
  } > "$ENV_FILE"
  rm -f "${ENV_FILE}.tmp"
  chmod 600 "$ENV_FILE"
}

load_env

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "BotFather'dan aldığın token'ı yapıştır:"
  read -r TELEGRAM_BOT_TOKEN
fi

if [[ -z "$TELEGRAM_BOT_TOKEN" ]]; then
  echo "❌ Token boş."
  exit 1
fi

echo "▶ Bot doğrulanıyor..."
ME=$(curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe")
if ! echo "$ME" | grep -q '"ok":true'; then
  echo "❌ Token geçersiz. BotFather → /mybots → botun → API Token → Revoke → yeni token al."
  echo "$ME"
  exit 1
fi
BOT_NAME=$(echo "$ME" | python3 -c "import sys,json; print(json.load(sys.stdin)['result'].get('username',''))" 2>/dev/null || true)
echo "✅ Bot: @${BOT_NAME:-?}"

if [[ -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo ""
  echo "📱 Telegram'da @${BOT_USER} botuna /start yaz, Enter'a bas..."
  read -r _
  UPD=$(curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates")
  TELEGRAM_CHAT_ID=$(echo "$UPD" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for u in reversed(d.get('result', [])):
    m = u.get('message') or u.get('edited_message') or {}
    c = m.get('chat') or {}
    if c.get('id'):
        print(c['id'])
        break
" 2>/dev/null || true)
fi

if [[ -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo "❌ Chat ID bulunamadı. Önce bota /start yaz."
  exit 1
fi

save_env "$TELEGRAM_BOT_TOKEN" "$TELEGRAM_CHAT_ID"
echo "✅ Kaydedildi: $ENV_FILE"

MSG="✅ Telegram bağlandı!%0A%0ABundan sonra sunucu her başlayınca güncel link buraya gelecek.%0A%0AKomut:%0A/link — güncel adresi tekrar iste"
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT_ID}" \
  -d "text=${MSG}" >/dev/null

if [[ -f "$ROOT/PUBLIC_URL.txt" ]]; then
  URL=$(cat "$ROOT/PUBLIC_URL.txt")
  MSG2="📱 Güncel link:%0A${URL}%0A%0AEğitim: ${URL}/education.html?v=17%0AÇeviri: ${URL}/translate.html"
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=${MSG2}" >/dev/null
  echo "📲 Mevcut link Telegram'a gönderildi."
fi

echo ""
echo "Tamam! Artık: ./scripts/baslat.sh"

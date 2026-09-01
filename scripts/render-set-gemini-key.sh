#!/usr/bin/env bash
# Render'a GEMINI_API_KEY ekler (Groq limit dolunca otomatik yedek devreye girer).
# Kullanım:
#   export RENDER_API_KEY=rnd_...   # https://dashboard.render.com/u/settings#api-keys
#   export RENDER_SERVICE_ID=srv-... # Servis → Settings → Service ID
#   ./scripts/render-set-gemini-key.sh "AQ.... veya AIzaSy...."
set -euo pipefail

KEY="${1:-}"
if [[ -z "${RENDER_API_KEY:-}" || -z "${RENDER_SERVICE_ID:-}" || -z "$KEY" ]]; then
  echo "Kullanım: RENDER_API_KEY=... RENDER_SERVICE_ID=srv-... $0 \"GEMINI_API_KEY\""
  exit 1
fi

curl -fsS -X PUT \
  "https://api.render.com/v1/services/${RENDER_SERVICE_ID}/env-vars/GEMINI_API_KEY" \
  -H "Authorization: Bearer ${RENDER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"value\": \"${KEY}\"}"

echo ""
echo "GEMINI_API_KEY güncellendi. Render otomatik yeniden deploy edecek."
echo "Kontrol: curl -s https://sesli-cevirmen.onrender.com/api/status | python3 -m json.tool"

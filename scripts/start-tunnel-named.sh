#!/usr/bin/env bash
# SABİT adres — Cloudflare Named Tunnel (kendi domain'iniz gerekir)
# Önce docs/SABIT-ADRES.md adımlarını tamamlayın.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${CLOUDFLARE_TUNNEL_CONFIG:-$ROOT/cloudflare-tunnel.yml}"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "❌ cloudflared bulunamadı."
  exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
  echo "❌ Tünel config bulunamadı: $CONFIG"
  echo "   Örnek: cp cloudflare-tunnel.example.yml cloudflare-tunnel.yml"
  echo "   Sonra docs/SABIT-ADRES.md adımlarını izleyin."
  exit 1
fi

echo "▶ Sabit Cloudflare tüneli başlatılıyor..."
echo "   Config: $CONFIG"
exec cloudflared tunnel --config "$CONFIG" run

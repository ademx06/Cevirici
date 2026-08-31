#!/usr/bin/env bash
# GitHub'a ilk push — KULLANICI ve REPO adını düzenleyin.
set -euo pipefail
cd "$(dirname "$0")/.."

GITHUB_USER="${GITHUB_USER:-ademix06}"
REPO="${REPO:-symmetrical-guacamole}"
REMOTE="https://github.com/${GITHUB_USER}/${REPO}.git"

git checkout -B main 2>/dev/null || git checkout main
git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE"
echo "→ Push: $REMOTE"
git push -u origin main

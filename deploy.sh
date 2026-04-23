#!/bin/bash
# Pull latest code from git and ship it on this server.
# Run after pushing to main. Idempotent.
#
# Assumes:
#   - Repo lives at ~/api-dashboard (clone of this repo)
#   - Backend venv at backend/.venv (created by setup.sh)
#   - nvm installed in $HOME/.nvm (installed by setup.sh)
#   - Frontend served by nginx from /var/www/api-dashboard
#   - Backend runs under systemd unit "api-dashboard"
#
# backend/.env, backend/.secret.key, backend/data.db are never touched.

set -euo pipefail

cd "$(dirname "$0")"

echo "==> git pull"
git pull --ff-only

echo "==> backend deps"
# shellcheck disable=SC1091
source backend/.venv/bin/activate
pip install -q -r backend/requirements.txt
deactivate

echo "==> frontend build"
export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
(cd frontend && npm install --silent && npm run build)

echo "==> publish frontend"
sudo rsync -a --delete frontend/dist/ /var/www/api-dashboard/
sudo chown -R nginx:nginx /var/www/api-dashboard

echo "==> restart backend"
sudo systemctl restart api-dashboard
sudo systemctl is-active api-dashboard

echo "==> done"

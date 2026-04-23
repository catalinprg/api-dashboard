#!/usr/bin/env bash
# Bootstrap a fresh Linux server to run the API Dashboard.
# Installs: system deps, Python 3 + venv + pip, Node.js (via nvm), then backend/frontend deps.
# Tested on Ubuntu 22.04 / 24.04 + Debian 12. Works on RHEL-family via dnf.
# Run as a regular user (will use sudo for system packages).
#
# Usage:   ./setup.sh
# Remote:  curl -fsSL https://example.com/setup.sh | bash
#
# After this finishes, run ./dev.sh to start the app.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
NODE_VERSION="${NODE_VERSION:-lts/*}"
PY_BIN="${PYTHON:-python3}"

log() { printf "\n\033[1;35m→ %s\033[0m\n" "$*"; }
ok()  { printf "  \033[1;32m✓\033[0m %s\n" "$*"; }
warn(){ printf "  \033[1;33m⚠\033[0m %s\n" "$*"; }

sudo_if_needed() {
  if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}

# ---- 1. Detect package manager ----
if command -v apt-get >/dev/null 2>&1; then
  PKG="apt"
elif command -v dnf >/dev/null 2>&1; then
  PKG="dnf"
elif command -v yum >/dev/null 2>&1; then
  PKG="yum"
else
  echo "Unsupported package manager. Install python3, python3-venv, git, curl, build-essential manually."
  exit 1
fi

log "Updating package index (${PKG})"
case "$PKG" in
  apt)
    sudo_if_needed apt-get update -y
    ;;
  dnf|yum)
    sudo_if_needed "$PKG" -y makecache
    ;;
esac

# ---- 2. System packages ----
log "Installing system packages"
case "$PKG" in
  apt)
    sudo_if_needed apt-get install -y \
      ca-certificates curl git build-essential \
      python3 python3-venv python3-pip \
      libssl-dev pkg-config
    ;;
  dnf|yum)
    sudo_if_needed "$PKG" -y install \
      ca-certificates curl git gcc gcc-c++ make \
      python3 python3-pip \
      openssl-devel pkgconf-pkg-config
    ;;
esac
ok "system packages installed"

# ---- 3. Node.js via nvm ----
export NVM_DIR="$HOME/.nvm"
if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  log "Installing nvm"
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
fi
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"

if ! nvm ls "$NODE_VERSION" >/dev/null 2>&1; then
  log "Installing Node ($NODE_VERSION) via nvm"
  nvm install "$NODE_VERSION"
fi
nvm use "$NODE_VERSION" >/dev/null
nvm alias default "$NODE_VERSION" >/dev/null
ok "node $(node -v), npm $(npm -v)"

# ---- 4. Python venv + backend deps ----
if [ ! -d "$REPO_DIR/backend/.venv" ]; then
  log "Creating Python venv ($PY_BIN)"
  "$PY_BIN" -m venv "$REPO_DIR/backend/.venv"
fi
# shellcheck disable=SC1091
. "$REPO_DIR/backend/.venv/bin/activate"
log "Installing backend Python deps"
pip install --upgrade pip >/dev/null
pip install -r "$REPO_DIR/backend/requirements.txt"
deactivate
ok "backend deps installed"

# ---- 5. Frontend deps ----
if [ ! -d "$REPO_DIR/frontend/node_modules" ]; then
  log "Installing frontend npm deps"
  (cd "$REPO_DIR/frontend" && npm install)
else
  ok "frontend node_modules already present"
fi

# ---- 6. Summary ----
cat <<EOF

$(printf '\033[1;32m✓ setup complete\033[0m')

Next:
  cd "$REPO_DIR"
  ./dev.sh

Access locally on the VM at:
  frontend: http://127.0.0.1:5173
  backend:  http://127.0.0.1:8000

To reach the dashboard from your laptop **securely** without exposing ports:
  ssh -L 5173:localhost:5173 -L 8000:localhost:8000 user@your-vm-ip
  # then open http://localhost:5173 in your local browser

Do NOT open ports 5173 / 8000 to the public internet — the dashboard has no auth layer yet.

Open a new shell (or run:  source ~/.bashrc  /  source ~/.zshrc ) so nvm is on PATH for future sessions.
EOF

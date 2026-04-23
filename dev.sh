#!/usr/bin/env bash
# Start backend (FastAPI on :8000) and frontend (Vite on :5173) together.
# Ctrl+C stops both.

set -e
cd "$(dirname "$0")"

BACKEND_PORT=8000
FRONTEND_PORT=5173

PY_BIN="${PYTHON:-python3}"

# ---- Backend setup (first run only) ----
if [ ! -d backend/.venv ]; then
  echo "→ Creating backend virtualenv (first run)…"
  "$PY_BIN" -m venv backend/.venv
fi

# shellcheck disable=SC1091
source backend/.venv/bin/activate

if ! python -c "import fastapi" 2>/dev/null; then
  echo "→ Installing backend dependencies…"
  pip install --upgrade pip >/dev/null
  pip install -r backend/requirements.txt
fi

# ---- Frontend setup (first run only) ----
if [ ! -d frontend/node_modules ]; then
  echo "→ Installing frontend dependencies…"
  (cd frontend && npm install)
fi

# ---- Launch both, forward logs, clean up on exit ----
BACK_PID=""
FRONT_PID=""

cleanup() {
  echo ""
  echo "→ Shutting down…"
  [ -n "$BACK_PID" ] && kill "$BACK_PID" 2>/dev/null || true
  [ -n "$FRONT_PID" ] && kill "$FRONT_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "→ Backend  → http://127.0.0.1:$BACKEND_PORT"
# Load backend/.env (if present) into the backend subshell for OAuth / secrets
(
  cd backend
  if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
  fi
  uvicorn main:app --reload --port "$BACKEND_PORT" 2>&1 | sed 's/^/[backend] /'
) &
BACK_PID=$!

echo "→ Frontend → http://127.0.0.1:$FRONTEND_PORT"
(cd frontend && npm run dev -- --port "$FRONTEND_PORT" 2>&1 | sed 's/^/[frontend] /') &
FRONT_PID=$!

wait

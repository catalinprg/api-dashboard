# API Dashboard

A local control center for configuring and testing APIs — both LLMs and any HTTP/REST service — with persistent chat sessions, variable substitution, streaming, tool calling, presets, history, and more.

Three panels in the sidebar:

- **Playground** — three tabs: **LLM chat** (streaming, markdown, images/files, tools, saved sessions), **Compare** (same prompt across multiple providers/models side-by-side), **HTTP request** (call any REST endpoint with saved presets).
- **History** — every request you've sent with full-text search, filters, and "copy as cURL".
- **Admin** — configure providers, endpoints, models, variables, auth; import/export config; import REST specs; ping providers.

## Stack

- **Backend:** FastAPI + SQLite + SQLAlchemy. API keys encrypted with Fernet.
- **Frontend:** Vite + React + Tailwind. Mobile-optimized.

## Setup

### On a fresh Linux server (Ubuntu / Debian / RHEL family)

One command installs every system dependency (Python + venv, Node via nvm, build tools, git, curl) plus the dashboard itself:

```bash
./setup.sh
```

It auto-detects `apt` / `dnf` / `yum`, uses `sudo` for system packages, installs Node via nvm (no distro Node needed), creates the Python venv, and pulls both Python and npm deps. After it finishes, start the app with `./dev.sh`.

### On a machine that already has Python + Node

One command starts both services:

```bash
./dev.sh
```

On first run it creates the Python venv, installs backend + frontend deps, and launches:

- backend on http://127.0.0.1:8000
- frontend on http://127.0.0.1:5173

Press `Ctrl+C` to stop both. To use a specific Python binary: `PYTHON=python3.13 ./dev.sh`.

A secret key is auto-generated at `backend/.secret.key` and encrypts all provider/endpoint keys at rest. **Back it up** — losing it means losing access to stored API keys. You can set `DASHBOARD_SECRET_KEY` in the environment instead of using the file.

The dashboard starts empty. Open Admin → **+ Add provider**.

<details>
<summary>Running services individually</summary>

```bash
# Backend
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Vite proxies `/api` to the FastAPI backend on port 8000.
</details>

## Providers

Each provider is either:

- **LLM** — hit via `/chat/completions` (OpenAI-compatible) or `/messages` (Anthropic native). Supports streaming, tool calling, multimodal.
- **HTTP / REST** — any REST API. You define one or more named `method + path` endpoints.

### Auth types

- **Bearer token** — `Authorization: Bearer <key>`, prefix configurable.
- **Custom header** — any header name, optional prefix (`x-api-key`, `X-Auth-Token`, etc.).
- **Query param** — key passed as `?api_key=...`.
- **HMAC-SHA256** — signs `METHOD\npath\nsha256(body)\ntimestamp`. Header names configurable via Extra headers: `hmac_ts_header`, `hmac_sig_header`, `hmac_sig_prefix`.
- **JWT HS256** — mints a token from claims in `jwt_claims` (Extra headers). `iat`/`exp` are added automatically; `jwt_exp_seconds` controls lifetime.
- **None**.

### Per-endpoint auth override

Each endpoint can pick one of:

- **Inherit** from provider (default).
- **Override** with its own stored key.
- **Off** — no credentials sent for that endpoint.

The key-status icon next to each endpoint row shows which mode is active.

### Variables / `{{var}}` substitution

Each provider has a `Variables` JSON field (e.g. `{"base_path": "v1", "user_id": "42"}`). Reference anywhere with `{{name}}` — in paths, headers, query, and request bodies. Substitution happens server-side before auth signing.

### Models list (LLM)

Maintain a list of model IDs per provider, set one as default. In the Playground the model field becomes a dropdown; "Custom…" lets you type an ad-hoc model for one-off tests.

### Provider health / ping

Admin → `Ping` runs a safe probe (`/models` for LLM; first endpoint or base URL for HTTP) and shows status + latency, so you can confirm auth works without firing a real request.

## Playground

### LLM chat tab

- **Sessions** in a left drawer (hidden on mobile behind `☰ Chats`) — auto-titled from first message, persist across reloads, lazy-created on first send (no empty placeholders).
- **Streaming SSE** with a `Stop` button mid-stream.
- **Markdown rendering** for assistant replies, including fenced code blocks with per-block `copy` buttons.
- **Multi-turn by default** — session messages persist and re-send as context.
- **Edit / regenerate** — hover a bubble: `copy` (any), `edit` (user), `regenerate` (last assistant). Truncates the session and re-runs.
- **File / image upload** — 📎 attaches images (sent as multimodal content parts) or text files (inlined in the prompt).
- **Tool / function calling** — paste an array of OpenAI-format tool schemas under `Advanced`. When the model returns `tool_calls` they render as chips with a `reply as tool` shortcut; paste the result and the model continues.
- **Token + cost display** — per-response usage (`in↑ / out↓`) and estimated `$cost` accumulated across the session, based on a built-in pricing table for common models.
- **Advanced** — system prompt, temperature (with quick-reference guide), max tokens (blank = model max), tools.

### Compare tab

Pick 2+ provider/model targets, enter one prompt, run in parallel. Each target card shows the reply (markdown-rendered), status, latency, tokens, and cost.

### HTTP request tab

- Pick a provider + endpoint. Method and path come from the endpoint config.
- Edit Extra headers / Query (JSON) and optional Body (JSON, form, or text).
- The computed full URL shows above the Send button so you can verify before firing.
- **Presets** — Save the current headers/query/body/body-type combo under a name; reload with one click. Works separately from endpoints.
- **Response panel** shows status, latency, masked request headers (so you can see exactly what was sent), response body, and response headers.
- **Copy as cURL** on every request and history entry.

## History

Every LLM and HTTP request is logged. The History tab supports:

- Filters: All / LLM / HTTP / Success / Errors.
- **Full-text search** across provider name, label, request JSON, and response JSON (debounced).
- Expand any row to see full request + response JSON, with a `copy as cURL` button.
- Per-row delete and Clear-all.

## Export / import

- **Export** — downloads a JSON with all providers, endpoints, models, variables, extra headers. Optionally includes decrypted API keys (treat the file as sensitive).
- **Import config** — restores a previously exported file. Existing providers with the same name are skipped.
- **Import REST spec** — auto-detects **OpenAPI 3.x**, **Postman Collection 2.1**, or **HAR** files and creates a new HTTP/REST provider with endpoints. LLMs don't have spec files — add them manually.

## Authentication (GitHub OAuth)

The dashboard has **optional GitHub OAuth login** with a username (or email) allowlist. When no OAuth config is set, the app runs with no auth (dev mode) — perfect for localhost. When you expose it to the internet, configure OAuth.

### One-time GitHub setup (≈3 minutes)

1. GitHub → **Settings → Developer settings → OAuth Apps → New OAuth App**.
2. Fill in:
   - **Application name:** API Dashboard (or anything).
   - **Homepage URL:** `http://localhost:5173` (or your prod URL).
   - **Authorization callback URL** — must match exactly:
     - `http://localhost:5173/api/auth/github/callback` (local dev), or
     - `https://dashboard.yourdomain.com/api/auth/github/callback` (production).
3. Copy the **Client ID** and generate a **Client Secret**.

No consent-screen review, no test-user list — GitHub OAuth Apps are usable immediately.

### Configure the dashboard

```bash
cp backend/.env.example backend/.env
# edit backend/.env:
#   GITHUB_CLIENT_ID=...
#   GITHUB_CLIENT_SECRET=...
#   GITHUB_REDIRECT_URI=http://localhost:5173/api/auth/github/callback
#   ALLOWED_LOGINS=your-github-username,other-person
```

Restart `./dev.sh` — now every `/api/*` call requires a valid session cookie. The frontend shows a **Continue with GitHub** screen; after OAuth the cookie is set and the dashboard unlocks.

### How the allowlist works

Two modes, in this order of precedence:

- **`ALLOWED_LOGINS`** (preferred) — comma-separated GitHub usernames. Stable, case-insensitive, can't be spoofed by changing email. Example: `ALLOWED_LOGINS=you,teammate`.
- **`ALLOWED_EMAILS`** — comma-separated verified primary emails. Only used if `ALLOWED_LOGINS` is empty. The `user:email` scope is requested so GitHub returns the primary verified email even when it's private.
- If **both** are empty, any GitHub user can sign in — **not recommended**; always set one.

### Turning auth off again

Remove `GITHUB_CLIENT_ID` from the env (or delete `backend/.env`). Auth silently disables and the app becomes open again.

## Security notes

- The server binds to localhost only. **Do not expose to the internet** as-is (no auth layer).
- API keys are encrypted in SQLite, but the encryption key (`.secret.key`) lives next to the DB; treat the whole `backend/` directory as sensitive.
- `.secret.key` and `data.db` are gitignored.
- Auth headers in the UI are masked (`sk-a…TgAA`) for display; full values are only decrypted on the backend at request time.

## Project layout

```
backend/
  main.py            FastAPI app — providers, endpoints, presets, sessions,
                     history, invoke/llm (+ /stream), invoke/http, export/import,
                     import-spec, ping, variable substitution, auth helpers (HMAC/JWT)
  models.py          SQLAlchemy models: Provider, Endpoint, ChatSession, ChatMessage,
                     RequestPreset, HistoryEntry
  schemas.py         Pydantic schemas
  crypto.py          Fernet encrypt/decrypt for stored API keys
  database.py        SQLite engine + migration runner
frontend/
  src/
    App.jsx
    api.js                          Thin fetch wrapper for the backend
    components/
      Sidebar.jsx                   Nav (mobile drawer)
      AdminPanel.jsx                Providers list, export/import, ping
      ProviderForm.jsx              Provider modal — basics, auth, models,
                                    variables, extra headers, endpoints
      Playground.jsx                Tab router
      LLMChat.jsx                   Sessions, streaming, markdown, tools,
                                    uploads, edit/regen, usage/cost
      ComparePanel.jsx              Side-by-side multi-provider runs
      GenericRequest.jsx            HTTP request tab + presets
      HistoryPanel.jsx              Full-text search, filters, cURL export
      ResponseView.jsx              Masked request echo, collapsible body
    utils/
      curl.js                       Build cURL commands from request echoes
      markdown.jsx                  Minimal markdown renderer with code blocks
      pricing.js                    Per-model cost estimates
```

## Keyboard shortcuts

- `⌘↵` / `Ctrl↵` — send chat message.

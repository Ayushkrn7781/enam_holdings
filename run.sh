#!/usr/bin/env bash
# FINN: one command to run locally, refresh live data, test, or deploy to Render.
#   ./run.sh local              build and serve on http://localhost:${PORT:-8000}
#   ./run.sh refresh [TICKERS]  pull live NSE/screener/Yahoo data, then save it as the seed snapshot
#   ./run.sh snapshot           rebuild the illustrative demo snapshot in backend/seed
#   ./run.sh test               pytest + evaluation
#   ./run.sh deploy             push to GitHub and deploy on Render (free plan)
# bash 3.2 compatible (macOS); uses python3 for JSON, no jq.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"
PY="$VENV/bin/python"
RENDER_API="${RENDER_API:-https://api.render.com/v1}"
SERVICE_NAME="${SERVICE_NAME:-finn}"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

pick_python() {
  for p in python3.12 python3.11 python3.13 python3; do
    if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
      echo "$p"; return
    fi
  done
  die "Python 3.11+ is required"
}

ensure_venv() {
  if [ ! -x "$PY" ]; then
    say "Creating backend/.venv"
    "$(pick_python)" -m venv "$VENV"
  fi
  "$PY" -m pip install -q --upgrade pip >/dev/null
  "$PY" -m pip install -q -r "$BACKEND/requirements.txt"
}

build_frontend() {
  command -v npm >/dev/null 2>&1 || die "Node.js 18+ (npm) is required"
  say "Building the frontend"
  (cd "$FRONTEND" && npm ci --no-audit --no-fund && npm run build)
}

checkpoint_to_seed() {
  # $1 = data dir holding finn.db and docs/
  local data="$1"
  "$PY" - "$data/finn.db" <<'PYEOF'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
c.execute("PRAGMA journal_mode=DELETE")
c.close()
PYEOF
  mkdir -p "$BACKEND/seed"
  cp "$data/finn.db" "$BACKEND/seed/finn.db"
  rm -rf "$BACKEND/seed/docs"
  if [ -d "$data/docs" ]; then cp -R "$data/docs" "$BACKEND/seed/docs"; fi
  say "Snapshot saved to backend/seed"
}

cmd_local() {
  ensure_venv
  build_frontend
  local port="${PORT:-8000}"
  say "FINN on http://localhost:$port"
  cd "$BACKEND"
  FRONTEND_DIST="$FRONTEND/dist" exec "$PY" -m uvicorn finn.api.app:app --host 0.0.0.0 --port "$port"
}

cmd_snapshot() {
  ensure_venv
  local data="${TMPDIR:-/tmp}/finn_snapshot_$$"
  rm -rf "$data"
  (cd "$BACKEND" && FINN_DATA_DIR="$data" "$PY" -m finn.seed)
  checkpoint_to_seed "$data"
  rm -rf "$data"
}

cmd_refresh() {
  ensure_venv
  local data="$BACKEND/data"
  local args=""
  if [ "$#" -gt 0 ]; then args="--research $*"; fi
  # shellcheck disable=SC2086
  (cd "$BACKEND" && FINN_DATA_DIR="$data" "$PY" -m finn.refresh $args)
  checkpoint_to_seed "$data"
}

cmd_test() {
  ensure_venv
  cd "$BACKEND"
  export FINN_NO_DOTENV=1  # the baseline test and eval run is deterministic, without the .env model key
  "$PY" -m pytest -q tests
  local data="${TMPDIR:-/tmp}/finn_eval_$$"
  FINN_DATA_DIR="$data" FINN_SNAPSHOT_DIR="$BACKEND/seed" "$PY" - <<'PYEOF'
from finn.api.app import restore_snapshot
from finn.db import init_db, session_scope
from finn import demo
from finn.models import Company
if not restore_snapshot():
    init_db()
    with session_scope() as s:
        if s.query(Company).count() == 0:
            demo.reset(s)
PYEOF
  FINN_DATA_DIR="$data" "$PY" -m eval.run_eval
  rm -rf "$data"
}

json_get() {
  # json_get '<python expression on d>'  (reads JSON from stdin)
  python3 -c "import json,sys; d=json.load(sys.stdin); v=$1; print('' if v is None else v)"
}

render() {
  # render METHOD PATH [BODY]
  local method="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    curl -sS -X "$method" "$RENDER_API$path" -H "Authorization: Bearer $RENDER_API_KEY" \
      -H "Accept: application/json" -H "Content-Type: application/json" -d "$body"
  else
    curl -sS -X "$method" "$RENDER_API$path" -H "Authorization: Bearer $RENDER_API_KEY" -H "Accept: application/json"
  fi
}

ask_secret() {
  # silent prompt on the terminal; empty answer when there is no terminal
  local v=""
  if { exec 3</dev/tty; } 2>/dev/null; then
    printf '%s' "$1" >/dev/tty
    IFS= read -rs v <&3 || true
    exec 3<&-
    echo >/dev/tty
  fi
  printf '%s' "$v"
}

cmd_deploy() {
  command -v git >/dev/null 2>&1 || die "git is required"
  command -v curl >/dev/null 2>&1 || die "curl is required"
  cd "$ROOT"

  if [ -z "${RENDER_API_KEY:-}" ]; then
    RENDER_API_KEY="$(ask_secret 'Render API key (dashboard > Account settings > API keys): ')"
  fi
  [ -n "$RENDER_API_KEY" ] || die "a Render API key is required (set RENDER_API_KEY or run from a terminal)"
  # GEMINI_API_KEY set to empty means "keep whatever key Render already stores"; unset means ask.
  if [ -z "${GEMINI_API_KEY+x}" ]; then
    GEMINI_API_KEY="$(ask_secret 'Gemini API key (optional, Enter to skip): ')"
  fi
  # Keys live only in this process's memory; nothing is written to disk.

  if [ ! -d .git ]; then git init -q -b main; fi
  git add -A
  git commit -q -m "FINN deploy $(date +%Y-%m-%d)" >/dev/null 2>&1 || true

  if ! git remote get-url origin >/dev/null 2>&1; then
    command -v gh >/dev/null 2>&1 || die "no git remote 'origin' and the GitHub CLI (gh) is not installed"
    local repo="${REPO_NAME:-finn}" vis="${REPO_VISIBILITY:-}"
    if [ -z "$vis" ]; then
      if { exec 3</dev/tty; } 2>/dev/null; then
        printf 'Create GitHub repo "%s" as public or private? [public]: ' "$repo" >/dev/tty
        IFS= read -r vis <&3 || true
        exec 3<&-
      fi
      vis="${vis:-public}"
    fi
    say "Creating GitHub repo $repo ($vis)"
    gh repo create "$repo" "--$vis" --source . --remote origin --push
  else
    git push -q -u origin HEAD:main
  fi
  local repo_url
  repo_url="$(git remote get-url origin | sed -e 's#^git@github.com:#https://github.com/#' -e 's#\.git$##')"

  say "Looking up your Render workspace"
  local owners owner_id
  owners="$(render GET "/owners?limit=20")"
  owner_id="$(printf '%s' "$owners" | json_get "(d[0].get('owner') or d[0])['id'] if isinstance(d, list) and d else None" 2>/dev/null || true)"
  [ -n "$owner_id" ] || die "Render API rejected the key or returned no workspace: $(printf '%s' "$owners" | head -c 200)"

  local existing service_id
  existing="$(render GET "/services?name=$SERVICE_NAME&ownerId=$owner_id&limit=20")"
  service_id="$(printf '%s' "$existing" | json_get "next(((x.get('service') or x)['id'] for x in d if (x.get('service') or x).get('name') == '$SERVICE_NAME'), None) if isinstance(d, list) else None" 2>/dev/null || true)"

  if [ -n "$service_id" ]; then
    say "Updating service $service_id"
    # Repair settings a hand-made service may have wrong (root directory, Dockerfile path).
    local runtime
    runtime="$(render GET "/services/$service_id" | json_get "(d.get('serviceDetails') or {}).get('runtime') or (d.get('serviceDetails') or {}).get('env')" 2>/dev/null || true)"
    if [ -n "$runtime" ] && [ "$runtime" != "docker" ]; then
      die "service '$SERVICE_NAME' uses the '$runtime' runtime and Render cannot switch it to Docker. Delete it (Dashboard > service > Settings > Delete) and re-run ./run.sh deploy."
    fi
    render PATCH "/services/$service_id" '{"rootDir":"","autoDeploy":"yes","serviceDetails":{"healthCheckPath":"/api/health","envSpecificDetails":{"dockerfilePath":"./Dockerfile","dockerContext":"."}}}' >/dev/null
    # Per-key updates, so a redeploy without a Gemini key never wipes the stored one.
    render PUT "/services/$service_id/env-vars/FINN_DATA_DIR" '{"value":"/tmp/finn"}' >/dev/null
    if [ -n "${GEMINI_API_KEY:-}" ]; then
      render PUT "/services/$service_id/env-vars/GEMINI_API_KEY" "{\"value\":\"$GEMINI_API_KEY\"}" >/dev/null
    fi
    render POST "/services/$service_id/deploys" '{"clearCache":"clear"}' >/dev/null
  else
    say "Creating Render web service $SERVICE_NAME"
    local env='[{"key":"FINN_DATA_DIR","value":"/tmp/finn"}'
    if [ -n "${GEMINI_API_KEY:-}" ]; then env="$env,{\"key\":\"GEMINI_API_KEY\",\"value\":\"$GEMINI_API_KEY\"}"; fi
    env="$env]"
    local body created
    body="{\"type\":\"web_service\",\"name\":\"$SERVICE_NAME\",\"ownerId\":\"$owner_id\",\"repo\":\"$repo_url\",\"branch\":\"main\",\"rootDir\":\"\",\"autoDeploy\":\"yes\",\"envVars\":$env,\"serviceDetails\":{\"runtime\":\"docker\",\"plan\":\"free\",\"region\":\"singapore\",\"healthCheckPath\":\"/api/health\",\"envSpecificDetails\":{\"dockerfilePath\":\"./Dockerfile\",\"dockerContext\":\".\"}}}"
    created="$(render POST "/services" "$body")"
    service_id="$(printf '%s' "$created" | json_get "(d.get('service') or d).get('id')" 2>/dev/null || true)"
    if [ -z "$service_id" ]; then
      echo "$created" | head -c 400 >&2; echo >&2
      die "Render could not create the service. If the repo is private, connect GitHub to Render first (Dashboard > Account > Git providers)."
    fi
  fi

  say "Waiting for the deploy to go live (this takes a few minutes on the free plan)"
  local status="" i=0
  while [ $i -lt 120 ]; do
    status="$(render GET "/services/$service_id/deploys?limit=1" | json_get "((d[0].get('deploy') or d[0]).get('status')) if isinstance(d, list) and d else None" 2>/dev/null || true)"
    case "$status" in
      live) break ;;
      build_failed|update_failed|canceled|deactivated) die "deploy ended with status: $status" ;;
    esac
    printf '.'; sleep "${POLL_S:-10}"; i=$((i + 1))
  done
  echo
  [ "$status" = "live" ] || die "timed out waiting for the deploy (last status: ${status:-unknown})"

  local url
  url="$(render GET "/services/$service_id" | json_get "(d.get('serviceDetails') or {}).get('url')" 2>/dev/null || true)"
  if [ -n "$url" ]; then curl -fsS "$url/api/health" >/dev/null && say "Health check passed"; fi
  say "Live:      ${url:-'(see dashboard)'}"
  say "Repo:      $repo_url"
  say "Dashboard: https://dashboard.render.com/web/$service_id"
}

case "${1:-local}" in
  local) shift || true; cmd_local "$@" ;;
  refresh) shift; cmd_refresh "$@" ;;
  snapshot) cmd_snapshot ;;
  test) cmd_test ;;
  deploy) cmd_deploy ;;
  *) die "usage: ./run.sh [local|refresh [TICKERS]|snapshot|test|deploy]" ;;
esac

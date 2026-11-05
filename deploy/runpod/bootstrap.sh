#!/usr/bin/env bash
# One-command first boot for a RunPod GPU pod.
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/zeeburgers00-glitch/universal-ai-backend/main/deploy/runpod/bootstrap.sh)
#
# Safe to re-run: it updates an existing checkout instead of clobbering it, and
# it refuses to overwrite an existing .env.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/zeeburgers00-glitch/universal-ai-backend.git}"
WORK_DIR="${WORK_DIR:-/workspace}"
APP_DIR="$WORK_DIR/universal-ai-backend"
COMPOSE_DIR="$APP_DIR/deploy/runpod"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn] %s\033[0m\n' "$*"; }

# --- 0. sanity -------------------------------------------------------------
if ! command -v nvidia-smi >/dev/null 2>&1; then
  warn "nvidia-smi not found — this pod may not have a GPU attached."
else
  say "GPU detected"
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
fi

# --- 1. docker -------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi

if ! docker compose version >/dev/null 2>&1; then
  say "Installing the Docker Compose plugin"
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

if ! docker info >/dev/null 2>&1; then
  warn "Docker daemon is not reachable. Starting it..."
  (dockerd >/var/log/dockerd.log 2>&1 &) || true
  sleep 5
fi
docker info >/dev/null 2>&1 || { echo "Docker is not running. Start it and re-run."; exit 1; }

# --- 2. code ---------------------------------------------------------------
mkdir -p "$WORK_DIR"
if [ -d "$APP_DIR/.git" ]; then
  say "Updating existing checkout"
  git -C "$APP_DIR" fetch --all --prune
  git -C "$APP_DIR" pull --ff-only || warn "Pull skipped (local changes present)"
else
  say "Cloning repository"
  git clone "$REPO_URL" "$APP_DIR"
fi

# --- 3. environment --------------------------------------------------------
if [ ! -f "$COMPOSE_DIR/.env" ]; then
  say "Creating .env from template"
  cp "$COMPOSE_DIR/.env.runpod.example" "$COMPOSE_DIR/.env"
  chmod 600 "$COMPOSE_DIR/.env"
  echo
  warn "Fill in the CHANGE_ME values, then re-run this script:"
  echo "    nano $COMPOSE_DIR/.env"
  exit 0
fi

if grep -q "CHANGE_ME" "$COMPOSE_DIR/.env"; then
  warn "Your .env still contains CHANGE_ME placeholders."
  grep -n "CHANGE_ME" "$COMPOSE_DIR/.env" | head -20
  echo
  read -r -p "Start anyway? [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || exit 1
fi

# --- 4. data dirs ----------------------------------------------------------
mkdir -p /workspace/data /workspace/redis

# --- 5. build & start ------------------------------------------------------
cd "$COMPOSE_DIR"
say "Building images (the voice worker pulls PyTorch — this can take a while)"
docker compose build --pull

say "Starting the stack"
docker compose up -d

say "Waiting for the API to answer /health"
for i in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "API is up."
    break
  fi
  sleep 5
  [ "$i" -eq 60 ] && warn "API did not come up in 5 minutes — check: docker compose logs api"
done

say "Worker readiness"
curl -fsS http://127.0.0.1:8000/v1/runtime/capabilities 2>/dev/null | python3 -m json.tool || true

cat <<'EOF'

Next steps
----------
1. Confirm ready_workers above is > 0.
2. Open your RunPod HTTP URL for port 8000 followed by /app  (the Studio UI)
   and /docs (the API reference).
3. Put the same BACKEND_API_KEY into your frontend / Base44 apps.
4. Useful:
     docker compose ps
     docker compose logs -f api
     docker compose restart api
EOF

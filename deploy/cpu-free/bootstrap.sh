#!/usr/bin/env bash
# One-command setup for the free-tier CPU stack.
#
#   sudo bash <(curl -fsSL https://raw.githubusercontent.com/zeeburgers00-glitch/universal-ai-backend/main/deploy/cpu-free/bootstrap.sh)
#
# Target: Oracle Cloud Always Free ARM (VM.Standard.A1.Flex, Ubuntu 22.04/24.04)
# or any small x86 VM. Safe to re-run.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/zeeburgers00-glitch/universal-ai-backend.git}"
APP_DIR="${APP_DIR:-/opt/universal-ai-backend}"
COMPOSE_DIR="$APP_DIR/deploy/cpu-free"
PUBLIC_PORT="${PUBLIC_PORT:-8000}"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn] %s\033[0m\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with sudo (it installs packages and edits firewall rules)." >&2
  exit 1
fi

# --- 0. environment --------------------------------------------------------
say "Host: $(uname -m) / $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || echo unknown)"
if [ "$(uname -m)" = "aarch64" ]; then
  echo "ARM detected — correct for Oracle Always Free. voice_worker is excluded"
  echo "from this stack because it needs an NVIDIA GPU (see README.md)."
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
systemctl enable --now docker >/dev/null 2>&1 || true
docker info >/dev/null 2>&1 || { echo "Docker is not running."; exit 1; }

# --- 2. firewall -----------------------------------------------------------
# Oracle images ship with iptables rules that block everything except 22.
# The OCI Security List is a SECOND layer you must open in the web console.
say "Opening port $PUBLIC_PORT in the local firewall"
if command -v iptables >/dev/null 2>&1; then
  if ! iptables -C INPUT -p tcp --dport "$PUBLIC_PORT" -j ACCEPT 2>/dev/null; then
    # Oracle's REJECT rule lives in INPUT; insert our ACCEPT above it.
    iptables -I INPUT 1 -p tcp --dport "$PUBLIC_PORT" -j ACCEPT
  fi
  if command -v netfilter-persistent >/dev/null 2>&1; then
    netfilter-persistent save >/dev/null 2>&1 || true
  elif [ -d /etc/iptables ]; then
    iptables-save > /etc/iptables/rules.v4 || true
  else
    warn "Could not persist the iptables rule. Re-apply it after reboot."
  fi
fi
echo
warn "REMEMBER: also open TCP $PUBLIC_PORT in the OCI Security List"
echo "     (Networking -> VCN -> Security Lists -> Default -> Add Ingress Rule)"
echo "     Without that step the API is up but unreachable from the internet."

# --- 3. code ---------------------------------------------------------------
say "Fetching the repository"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --all --prune
  git -C "$APP_DIR" pull --ff-only || warn "Pull skipped (local changes present)"
else
  mkdir -p "$(dirname "$APP_DIR")"
  git clone "$REPO_URL" "$APP_DIR"
fi

# --- 4. environment --------------------------------------------------------
ENV_FILE="$COMPOSE_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  say "Creating .env from the template"
  cp "$COMPOSE_DIR/.env.cpu-free.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"

  # Pre-fill secrets so the stack can start without hand-editing.
  RANDOM_REDIS="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
  RANDOM_BACKEND="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 48)"
  sed -i "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$RANDOM_REDIS|" "$ENV_FILE"
  sed -i "s|^BACKEND_API_KEY=.*|BACKEND_API_KEY=$RANDOM_BACKEND|" "$ENV_FILE"
  sed -i "s|CHANGE_ME_redis_password|$RANDOM_REDIS|g" "$ENV_FILE"
  for w in youtube channel media agent automation rea; do
    k="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
    sed -i "s|^$(echo "$w" | tr 'a-z' 'A-Z')_WORKER_API_KEY=.*|$(echo "$w" | tr 'a-z' 'A-Z')_WORKER_API_KEY=$k|" "$ENV_FILE"
  done

  IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || echo CHANGE_ME_your_ip)"
  sed -i "s|http://CHANGE_ME_your_ip:8000|http://$IP:$PUBLIC_PORT|" "$ENV_FILE"

  echo
  say "Secrets generated. Your backend API key:"
  grep '^BACKEND_API_KEY=' "$ENV_FILE"
  echo "Save it — the Studio UI and protected routes need it."
  echo "Add a model provider key (e.g. GROQ_API_KEY) to enable chat:"
  echo "    nano $ENV_FILE"
fi

mkdir -p "${DATA_DIR:-/opt/universal-ai-backend/data}"

# --- 5. build & start -----------------------------------------------------
cd "$COMPOSE_DIR"
say "Building images (first run takes a few minutes on a free-tier CPU)"
docker compose build --pull

say "Starting the stack"
docker compose up -d

say "Waiting for /health"
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PUBLIC_PORT/health" >/dev/null 2>&1; then
    echo "API is up."
    break
  fi
  sleep 5
  [ "$i" -eq 60 ] && warn "API did not come up — check: docker compose logs api"
done

say "Worker readiness"
curl -fsS "http://127.0.0.1:$PUBLIC_PORT/v1/runtime/capabilities" 2>/dev/null | python3 -m json.tool || true

# --- 6. survive reboots ----------------------------------------------------
say "Installing the systemd unit so the stack comes back after a reboot"
sed "s|/opt/universal-ai-backend|$APP_DIR|g" "$COMPOSE_DIR/universal-ai-backend.service" \
  > /etc/systemd/system/universal-ai-backend.service
systemctl daemon-reload
systemctl enable universal-ai-backend.service >/dev/null 2>&1 || true

cat <<EOF

Done.
-----
Studio UI : http://<your-vm-ip>:$PUBLIC_PORT/app
API docs  : http://<your-vm-ip>:$PUBLIC_PORT/docs
Voice     : intentionally 503 — needs a GPU host (see README.md)

Useful:
  cd $COMPOSE_DIR
  docker compose ps
  docker compose logs -f api
  docker compose restart api
  systemctl status universal-ai-backend
EOF

#!/usr/bin/env bash
#
# Treadwell Proposal Tool — VPS install script (Ubuntu 24.04 LTS)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/HDLC01/Treadwell-Proposal-Tool/main/deploy/install-vps.sh | bash -s -- proposals.wetreadwell.com
#
# What it does:
#   1. Installs Docker, nginx, certbot
#   2. Clones the repo to /opt/treadwell
#   3. Prompts for Dropbox credentials (or accepts existing .env)
#   4. Builds + runs the Docker container (binds 127.0.0.1:8888)
#   5. Configures nginx as reverse proxy for $DOMAIN → :8888
#   6. Runs certbot for free Let's Encrypt SSL
#   7. Prints final instructions for `claude login` (one-time)

set -euo pipefail

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
  echo "Usage: $0 <domain>   (e.g. proposals.wetreadwell.com)"
  exit 1
fi

REPO_URL="https://github.com/HDLC01/Treadwell-Proposal-Tool.git"
APP_DIR="/opt/treadwell"

echo "==============================================================="
echo " Treadwell Proposal Tool — deploying to $DOMAIN"
echo "==============================================================="

# ─── 1. Install Docker, nginx, certbot ────────────────────────────────
echo "[1/7] Installing Docker, nginx, certbot..."
apt-get update -y
apt-get install -y ca-certificates curl gnupg git nginx certbot python3-certbot-nginx ufw

# Docker official repo
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

# ─── 2. Firewall — allow SSH + HTTP + HTTPS ──────────────────────────
echo "[2/7] Configuring firewall (ufw)..."
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ─── 3. Clone repo ────────────────────────────────────────────────────
echo "[3/7] Cloning repo to $APP_DIR..."
if [[ -d "$APP_DIR" ]]; then
  cd "$APP_DIR" && git pull
else
  git clone "$REPO_URL" "$APP_DIR"
  cd "$APP_DIR"
fi

# ─── 4. Set up .env ───────────────────────────────────────────────────
if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "[4/7] Creating .env template — EDIT THIS before container starts..."
  cat > "$APP_DIR/.env" <<'EOF'
# Treadwell Proposal Tool environment

# Dropbox — paste from the local .env on Hanz's laptop
DROPBOX_APP_KEY=
DROPBOX_APP_SECRET=
DROPBOX_REFRESH_TOKEN=
# NOTE: DROPBOX_ROOT_FOLDER is intentionally NOT set here. It's defined in
# docker-compose.yml (environment:) because the production path contains a
# literal "$" that must be escaped as "$$" — and env_file values are also
# interpolated by Compose, which would corrupt it. environment: overrides
# env_file:, so the compose value always wins.

# Anthropic API (optional fallback if Claude CLI login expires)
ANTHROPIC_API_KEY=
EOF
  echo ""
  echo "  >>> .env created at $APP_DIR/.env"
  echo "  >>> Edit it with the Dropbox credentials, then re-run this script,"
  echo "  >>> or manually run: cd $APP_DIR && docker compose up -d --build"
  echo ""
  read -p "  Press Enter once .env is filled in to continue..."
else
  echo "[4/7] .env already exists, keeping it"
fi

# ─── 5. Build + run the container ─────────────────────────────────────
echo "[5/7] Building + starting the container..."
cd "$APP_DIR"
docker compose up -d --build
sleep 5

# Verify it's healthy
if curl -fsS http://127.0.0.1:8888/healthz > /dev/null; then
  echo "  ✓ Container healthy on http://127.0.0.1:8888"
else
  echo "  ✗ Container not responding on :8888 — check logs: docker compose logs"
  exit 1
fi

# ─── 6. nginx reverse proxy ───────────────────────────────────────────
echo "[6/7] Configuring nginx reverse proxy for $DOMAIN..."
cat > /etc/nginx/sites-available/treadwell-proposal <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    # Pre-cert: serve ACME challenge files, redirect everything else.
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        proxy_pass http://127.0.0.1:8888;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        # Generation endpoint can take 20-30s (Dropbox upload + AI)
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;

        client_max_body_size 25M;
    }
}
EOF
ln -sf /etc/nginx/sites-available/treadwell-proposal /etc/nginx/sites-enabled/treadwell-proposal
# Remove the default landing page if present
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# ─── 7. Let's Encrypt SSL cert ────────────────────────────────────────
echo "[7/7] Requesting Let's Encrypt SSL certificate for $DOMAIN..."
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m hanz@wetreadwell.com --redirect
systemctl reload nginx

echo ""
echo "==============================================================="
echo " ✓ Deploy complete"
echo "==============================================================="
echo ""
echo " Tool live at:  https://$DOMAIN"
echo ""
echo " ONE MORE STEP — enable AI Autofill (one-time):"
echo "   docker exec -it treadwell-proposal-tool claude login"
echo ""
echo "   That command prints a URL — open it in your browser, complete"
echo "   the Claude auth flow, paste the result back into the SSH"
echo "   session. After that, /api/autofill works server-side."
echo ""
echo " To view logs:        cd $APP_DIR && docker compose logs -f"
echo " To restart:          cd $APP_DIR && docker compose restart"
echo " To update from git:  cd $APP_DIR && git pull && docker compose up -d --build"
echo ""

#!/usr/bin/env bash
# Off-box deploy for the Treadwell Proposal Tool.
#
# The VPS is 1 core / 2 GB. Building on it (`docker compose up --build`) spikes
# load to ~60 and browns out every site on the box. So we build the image HERE,
# ship it over SSH, and the VPS only git-pulls the compose + loads + restarts
# (NO --build). Note: this image bakes in the Claude CLI + LibreOffice, so it's
# large — the transfer takes a bit, but it never storms the prod CPU.
#
# Prereqs: local Docker engine running; SSH key at ~/.ssh/treadwell_vps.
# Usage:   bash deploy/ship.sh
set -euo pipefail

VPS_HOST="${VPS_HOST:-50.6.110.215}"
VPS_USER="${VPS_USER:-root}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/treadwell_vps}"
APP_DIR="/opt/treadwell"
IMAGE="treadwell-proposal-tool:latest"
SSH=(ssh -i "$SSH_KEY" -o ConnectTimeout=20 "${VPS_USER}@${VPS_HOST}")

cd "$(dirname "$0")/.."

echo "==> Building $IMAGE locally (off the prod box)…"
docker build --platform linux/amd64 -t "$IMAGE" .

echo "==> Shipping image over SSH…"
docker save "$IMAGE" | gzip | "${SSH[@]}" "cat > /tmp/proposal-tool.tar.gz"

echo "==> git pull + load + restart on the VPS (NO build)…"
"${SSH[@]}" "set -euo pipefail
  cd $APP_DIR
  git pull --ff-only
  gunzip -c /tmp/proposal-tool.tar.gz | docker load
  rm -f /tmp/proposal-tool.tar.gz
  docker compose up -d
  for i in \$(seq 1 24); do
    if curl -fsS http://localhost:8888/healthz >/dev/null; then echo '   proposal-tool healthy'; exit 0; fi
    sleep 5
  done
  echo '   post-deploy healthcheck failed'; exit 1
"
echo "==> Done — proposals.wetreadwell.com is on the freshly-shipped image."

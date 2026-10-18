#!/usr/bin/env bash
# Ship the code to the server and (re)build the stack.
#   infrastructure/deployment/deploy.sh root@139.59.160.17
# Secrets live on the server in /etc/wob/env (mode 600), never in the repository.
set -euo pipefail
HOST=${1:?usage: deploy.sh user@host}
KEY=${SSH_KEY:-$HOME/.ssh/wob_do}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SSH="ssh -i $KEY"

rsync -az --delete -e "$SSH" \
  --exclude '.env' --exclude '.venv' --exclude 'node_modules' --exclude '.next' \
  --exclude 'backend/var' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude '.ruff_cache' --exclude '.DS_Store' \
  "$ROOT/" "$HOST:/opt/wob/"

$SSH "$HOST" 'cd /opt/wob/infrastructure/deployment \
  && docker compose --env-file /etc/wob/env up -d --build --remove-orphans \
  && docker image prune -f >/dev/null \
  && docker compose --env-file /etc/wob/env ps --format "{{.Service}}: {{.Status}}"'

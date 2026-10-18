#!/usr/bin/env bash
# Replace the server's data with this machine's: the database and the encrypted document store.
#   infrastructure/deployment/copy-data.sh root@139.59.160.17
# Run deploy.sh first. The server must use the same FILE_ENCRYPTION_KEYS and SECRET_KEY as the
# local .env, or stored files and two-factor secrets cannot be read there.
# This moves personal data to the server's country: see docs/operations/data-protection-review.md.
set -euo pipefail
HOST=${1:?usage: copy-data.sh user@host}
KEY=${SSH_KEY:-$HOME/.ssh/wob_do}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SSH="ssh -i $KEY"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "Dumping the local database…"
docker exec wob-ai-ranking-db-1 pg_dump -U wob -d wob -Fc --no-owner > "$TMP/wob.dump"

echo "Copying the database dump and encrypted files…"
scp -q -i "$KEY" "$TMP/wob.dump" "$HOST:/root/wob.dump"
rsync -az --delete -e "$SSH" "$ROOT/backend/var/storage/" "$HOST:/srv/wob/storage/"

echo "Restoring on the server…"
$SSH "$HOST" 'set -euo pipefail
cd /opt/wob/infrastructure/deployment
compose() { docker compose --env-file /etc/wob/env "$@"; }
compose stop api worker web
compose exec -T db dropdb -U wob --force --if-exists wob
compose exec -T db createdb -U wob wob
compose exec -T db pg_restore -U wob -d wob --no-owner --exit-on-error < /root/wob.dump
shred -u /root/wob.dump
compose up -d
echo "$(compose exec -T db psql -U wob -d wob -tAc "select count(*) from finalists") finalists, $(compose exec -T db psql -U wob -d wob -tAc "select count(*) from documents") documents, $(find /srv/wob/storage -type f | wc -l) stored files"'
echo "Done."

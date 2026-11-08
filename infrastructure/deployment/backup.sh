#!/usr/bin/env bash
# Back up the server's data to this machine: the database and the encrypted document store.
#   infrastructure/deployment/backup.sh root@139.59.160.17
# Writes $BACKUP_DIR/<timestamp>/ (default ~/wob-backups) containing
#   wob.dump   pg_dump custom format (restore with pg_restore --no-owner)
#   storage/   the encrypted files, exactly as stored on the server
#   counts.txt row and file counts, to check a restore against
# The server's secrets (/etc/wob/env: FILE_ENCRYPTION_KEYS, SECRET_KEY, ...) go to a separate
# file, $BACKUP_DIR/keys/env-<timestamp> (mode 600). Without them the stored files and two-factor
# secrets cannot be read, so keep that file apart from the data (data-protection-review §4.9).
set -euo pipefail
HOST=${1:?usage: backup.sh user@host}
KEY=${SSH_KEY:-$HOME/.ssh/wob_do}
SSH="ssh -i $KEY"
STAMP=$(date +%Y%m%d-%H%M%S)
BASE=${BACKUP_DIR:-$HOME/wob-backups}
OUT="$BASE/$STAMP"
umask 077
mkdir -p "$OUT/storage" "$BASE/keys"

REMOTE_COMPOSE='cd /opt/wob/infrastructure/deployment && docker compose --env-file /etc/wob/env'

echo "Dumping the database…"
$SSH "$HOST" "$REMOTE_COMPOSE exec -T db pg_dump -U wob -d wob -Fc --no-owner" > "$OUT/wob.dump"
# A truncated dump fails this listing (checked locally when Docker is available).
if docker info >/dev/null 2>&1; then
  docker run --rm -i pgvector/pgvector:0.8.0-pg17 pg_restore --list < "$OUT/wob.dump" > /dev/null
else
  echo "Docker is not running: skipping the local check of the dump."
fi

echo "Copying the encrypted files…"
rsync -az -e "$SSH" "$HOST:/srv/wob/storage/" "$OUT/storage/"

echo "Copying the server secrets…"
scp -q -i "$KEY" "$HOST:/etc/wob/env" "$BASE/keys/env-$STAMP"

$SSH "$HOST" "$REMOTE_COMPOSE exec -T db psql -U wob -d wob -tA -c \"
  select 'finalists', count(*) from finalists union all
  select 'documents', count(*) from documents union all
  select 'users', count(*) from users\"" | tr '|' ' ' > "$OUT/counts.txt"
echo "stored_files $(find "$OUT/storage" -type f | wc -l | tr -d ' ')" >> "$OUT/counts.txt"

echo "Backup written to $OUT ($(du -sh "$OUT" | cut -f1))"
cat "$OUT/counts.txt"
echo "Secrets in $BASE/keys/env-$STAMP: store them separately from the data."

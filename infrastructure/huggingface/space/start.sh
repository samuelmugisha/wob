#!/usr/bin/env bash
# Runs the whole stack in one container: PostgreSQL, ClamAV, the API, the worker and the web UI.
# Data lives in $DATA (/data, the Space's persistent storage). On first boot, or when the
# RESTORE_BACKUP variable names a backup other than the one in use, the database and files are
# restored from the private dataset BACKUP_DATASET. If any service stops, the container exits
# and the Space restarts it.
#
# Spaces have no persistent disk, so with BACKUP_UPLOAD=true the dataset is the persistence: the
# Space saves a backup every BACKUP_INTERVAL_MINUTES (default 60) when the data has changed, and
# once more when it stops (sleep, restart or update). On start it restores the newest backup.
set -euo pipefail

DATA=${DATA_DIR:-/data}
PGDATA=$DATA/pgdata
STORAGE=$DATA/storage
MARK=$DATA/.restored-backup  # id of the backup the data came from ("empty" if none)
ORIGIN=$DATA/.origin         # the server backup that data descends from (see hub_sync.py)
SAVED=$DATA/.saved-fingerprint  # fingerprint of the data in the last backup saved
BACKUPS=false
if [ "${BACKUP_UPLOAD:-false}" = true ] && [ -n "${BACKUP_DATASET:-}" ]; then BACKUPS=true; fi
log() { echo "[start] $*"; }
# The image's ~/.cache belongs to root (created at build time), so keep the Hub cache in $DATA.
export HF_HOME=$DATA/huggingface

touch "$DATA/.write-test" && rm "$DATA/.write-test"
if ! mountpoint -q "$DATA"; then
  if $BACKUPS; then
    log "$DATA is not persistent storage: changes are kept by saving backups to $BACKUP_DATASET."
  else
    log "WARNING: $DATA is not persistent storage and BACKUP_UPLOAD is off;" \
      "every change is lost when the Space restarts."
  fi
fi

if [ ! -s "$DATA/.pgpassword" ]; then
  python -c 'import secrets; print(secrets.token_urlsafe(32))' > "$DATA/.pgpassword"
  chmod 600 "$DATA/.pgpassword"
fi
PGPW=$(cat "$DATA/.pgpassword")

start_postgres() {
  postgres -D "$PGDATA" -c listen_addresses=127.0.0.1 -c unix_socket_directories=/tmp \
    -c shared_buffers=512MB &
  PG_PID=$!
  for _ in $(seq 120); do
    pg_isready -q -h /tmp -U wob && return 0
    kill -0 "$PG_PID" 2>/dev/null || { log "PostgreSQL exited"; exit 1; }
    sleep 1
  done
  log "PostgreSQL did not become ready"
  exit 1
}

# --- Database and files: restore from the dataset, or start what is already on disk ---------
current=$(cat "$MARK" 2>/dev/null || true)
restore=false
if [ -z "$current" ]; then
  restore=true
elif [ -n "${RESTORE_BACKUP:-}" ] && [ "$RESTORE_BACKUP" != "$current" ] \
  && [ "$RESTORE_BACKUP" != "$(cat "$ORIGIN" 2>/dev/null)" ]; then
  log "RESTORE_BACKUP=$RESTORE_BACKUP differs from the data in use ($current)."
  log "Keeping the current data in $DATA/previous and restoring $RESTORE_BACKUP."
  rm -rf "$DATA/previous" && mkdir -p "$DATA/previous"
  mv "$PGDATA" "$STORAGE" "$MARK" "$DATA/previous/"
  rm -f "$ORIGIN" "$SAVED"
  restore=true
fi

if $restore; then
  # Also clears what an interrupted earlier attempt left behind.
  rm -rf "$PGDATA" "$STORAGE" "$DATA/restore"
  initdb -D "$PGDATA" -U wob --pwfile=<(echo "$PGPW") -E UTF8 --locale=C.UTF-8 \
    --auth-local=trust --auth-host=scram-sha-256 >/dev/null
  mkdir -p "$STORAGE"
  start_postgres
  createdb -h /tmp -U wob wob
  backup_id=empty
  if [ -n "${BACKUP_DATASET:-}" ]; then
    python /app/space/hub_sync.py fetch "$DATA/restore" "${RESTORE_BACKUP:-}"
    backup_id=$(cat "$DATA/restore/BACKUP_ID")
    cp "$DATA/restore/ORIGIN" "$ORIGIN"
    log "restoring backup $backup_id"
    pg_restore -h /tmp -U wob -d wob --no-owner --exit-on-error "$DATA/restore/wob.dump"
    tar -xf "$DATA/restore/storage.tar" -C "$STORAGE"
    rm -rf "$DATA/restore"
  else
    log "BACKUP_DATASET is not set: starting with an empty database"
    echo empty > "$ORIGIN"
  fi
  rm -f "$SAVED"
  echo "$backup_id" > "$MARK"  # written last, so a failed restore is retried on the next boot
else
  start_postgres
fi
log "data from backup $(cat "$MARK"): $(psql -h /tmp -U wob -d wob -tAc \
  "select count(*) from finalists" 2>/dev/null || echo '?') finalists, \
$(find "$STORAGE" -type f | wc -l) stored files"

# --- Backups to the dataset ------------------------------------------------------------------
# The fingerprint covers the database contents and the stored files, so an unchanged system is
# not uploaded again. A lock keeps a timed backup and the final one from running together.
fingerprint() {
  {
    pg_dump -h /tmp -U wob -d wob -Fp --no-owner
    (cd "$STORAGE" && find . -type f -printf '%P %s %T@\n' | sort)
  } | sha256sum | cut -d' ' -f1
}
save_backup() {
  (
    flock 9
    fp=$(fingerprint) || { log "backup: could not read the data"; exit 1; }
    if [ "$fp" = "$(cat "$SAVED" 2>/dev/null)" ]; then
      log "backup: no changes since the last backup"
      exit 0
    fi
    dir=$(mktemp -d)
    if pg_dump -h /tmp -U wob -d wob -Fc --no-owner -f "$dir/wob.dump" \
      && tar -cf "$dir/storage.tar" -C "$STORAGE" . \
      && python /app/space/hub_sync.py push "$dir" "$(cat "$ORIGIN")"; then
      echo "$fp" > "$SAVED"
      python /app/space/hub_sync.py prune "${BACKUP_KEEP:-24}" || log "backup: pruning failed"
    else
      log "backup to $BACKUP_DATASET failed"
    fi
    rm -rf "$dir"
  ) 9>"$DATA/.backup.lock"
}
# Data just restored needs no backup of its own.
if $BACKUPS && [ ! -s "$SAVED" ]; then fingerprint > "$SAVED"; fi

# --- ClamAV ----------------------------------------------------------------------------------
mkdir -p "$DATA/clamav" "$DATA/models"
has_signatures() { ls "$DATA"/clamav/main.c[lv]d >/dev/null 2>&1; }
has_signatures || cp -a /opt/clamav-seed/. "$DATA/clamav/" 2>/dev/null || true
has_signatures || freshclam --config-file=/app/space/freshclam.conf
clamd --config-file=/app/space/clamd.conf &
CLAMD_PID=$!
freshclam --config-file=/app/space/freshclam.conf --daemon &

# --- Application -----------------------------------------------------------------------------
export ENVIRONMENT=production
export DATABASE_URL="postgresql+psycopg://wob:${PGPW}@127.0.0.1:5432/wob"
export STORAGE_DIR=$STORAGE MODEL_CACHE_DIR=$DATA/models
export SCANNER=clamav CLAMD_HOST=127.0.0.1 CLAMD_PORT=3310
export PUBLIC_BASE_URL=${PUBLIC_BASE_URL:-https://${SPACE_HOST:-localhost:7860}}
export COOKIE_SECURE=true

cd /app/backend
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!
python -m app.workers.main &
WORKER_PID=$!
(cd /app/frontend && exec node node_modules/next/dist/bin/next start --port 7860 --hostname 0.0.0.0) &
WEB_PID=$!

# Once the API is up, the same one-off tasks deploy.sh runs (each skips work already done).
(
  for _ in $(seq 120); do
    curl -fs http://127.0.0.1:8000/api/v1/health >/dev/null && break
    sleep 5
  done
  for task in auto-accept-research match-research-claims verify-supporting-claims; do
    python -m app.cli "$task" || log "$task failed"
  done
) &

# Timed backups to the dataset (HF_TOKEN needs write access to it).
BACKUP_PID=
if $BACKUPS; then
  (
    while sleep $((${BACKUP_INTERVAL_MINUTES:-60} * 60)); do
      save_backup || true
    done
  ) &
  BACKUP_PID=$!
fi

shutdown() {
  log "stopping"
  # Stop the app first, so the final backup holds everything it wrote.
  kill $BACKUP_PID "$WEB_PID" "$WORKER_PID" "$API_PID" 2>/dev/null || true
  for _ in $(seq 20); do
    running=false
    for pid in "$WEB_PID" "$WORKER_PID" "$API_PID"; do
      kill -0 "$pid" 2>/dev/null && running=true
    done
    $running || break
    sleep 0.5
  done
  if $BACKUPS && kill -0 "$PG_PID" 2>/dev/null; then
    log "saving a final backup"
    save_backup || true
  fi
  kill "$CLAMD_PID" 2>/dev/null || true
  pg_ctl -D "$PGDATA" stop -m fast >/dev/null 2>&1 || true
}
trap 'shutdown; exit 0' TERM INT

set +e
wait -n "$PG_PID" "$CLAMD_PID" "$API_PID" "$WORKER_PID" "$WEB_PID"
log "a service stopped; exiting so the Space restarts"
shutdown
exit 1

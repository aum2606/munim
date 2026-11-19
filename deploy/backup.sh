#!/bin/bash
# Nightly backup: a database dump and the uploaded files, with retention. Runs inside the
# `backup` container (the pgvector image has pg_dump). `backup.sh once` takes one backup and exits.
# Backups hold customer conversations: keep the folder private and copy it off this machine.
set -euo pipefail
umask 077

BACKUP_DIR=/backups
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
AT="${BACKUP_TIME_UTC:-20:30}"  # 20:30 UTC is 02:00 in India

run_backup() {
  local stamp tmp
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  tmp="$BACKUP_DIR/.munim-$stamp.dump.partial"
  pg_dump --format=custom --no-owner --file "$tmp"
  pg_restore --list "$tmp" > /dev/null          # a dump that cannot be read back is not a backup
  mv "$tmp" "$BACKUP_DIR/munim-$stamp.dump"
  if [ -d /data/uploads ]; then
    tar -C /data -czf "$BACKUP_DIR/uploads-$stamp.tgz" uploads
  fi
  find "$BACKUP_DIR" \( -name 'munim-*.dump' -o -name 'uploads-*.tgz' \) -mtime +"$KEEP_DAYS" -delete
  echo "backup ok: munim-$stamp.dump ($(du -h "$BACKUP_DIR/munim-$stamp.dump" | cut -f1))"
}

if [ "${1:-}" = "once" ]; then
  run_backup
  exit 0
fi

# Take one at start if there is none yet, so a fresh install is covered before the first night.
ls "$BACKUP_DIR"/munim-*.dump > /dev/null 2>&1 || run_backup

while true; do
  now="$(date -u +%s)"
  next="$(date -u -d "today $AT" +%s)"
  [ "$next" -le "$now" ] && next="$(date -u -d "tomorrow $AT" +%s)"
  sleep "$((next - now))"
  run_backup || echo "BACKUP FAILED" >&2   # the health check turns unhealthy if this keeps failing
done

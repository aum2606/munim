#!/bin/bash
# Restore a database dump. Run on the host, from the repo root:
#   deploy/restore.sh backups/munim-YYYYmmdd-HHMMSS.dump            # replaces the live database
#   deploy/restore.sh backups/munim-....dump munim_check            # into a scratch database (a drill)
# Stop the api and worker first when replacing the live database:
#   docker compose -f docker-compose.prod.yml stop api worker
set -euo pipefail
DUMP="${1:?usage: restore.sh <dump file> [target database]}"
COMPOSE="docker compose -f docker-compose.prod.yml"
[ -f "$DUMP" ] || { echo "no such file: $DUMP" >&2; exit 1; }

if [ -n "${2:-}" ]; then
  TARGET="$2"
  $COMPOSE exec -T postgres sh -c "dropdb -U \"\$POSTGRES_USER\" --if-exists '$TARGET' && createdb -U \"\$POSTGRES_USER\" '$TARGET'"
  $COMPOSE exec -T postgres sh -c "pg_restore -U \"\$POSTGRES_USER\" --no-owner -d '$TARGET'" < "$DUMP"
else
  $COMPOSE exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" --no-owner --clean --if-exists -d "$POSTGRES_DB"' < "$DUMP"
fi
echo "restored $DUMP"

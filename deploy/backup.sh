#!/bin/sh
# Ежедневная резервная копия базы PostgreSQL. В crontab пользователя chem:
#   15 3 * * * /srv/chem/app/deploy/backup.sh
# Восстановление: pg_restore --clean --if-exists -d chem /srv/chem/backups/db-ГГГГ-ММ-ДД.dump
set -e
cd /srv/chem/app
set -a; . ./.env; set +a
DIR=/srv/chem/backups
mkdir -p "$DIR"
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -Fc -h "${POSTGRES_HOST:-localhost}" -p "${POSTGRES_PORT:-5432}" \
    -U "${POSTGRES_USER:-chem}" "${POSTGRES_DB:-chem}" > "$DIR/db-$(date +%F).dump"
find "$DIR" -name 'db-*.dump' -mtime +30 -delete

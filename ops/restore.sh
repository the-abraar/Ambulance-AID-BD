#!/usr/bin/env bash
# Restore a dump from backups/ into a scratch database and print its row counts. Live data is untouched (the drill).
# With --live it then swaps the restored copy in as `ambulance` and keeps the old one as `ambulance_before_restore`.
# A .gpg dump is decrypted in a throwaway `backup` container with BACKUP_PASSPHRASE from .env; a plain .dump is read as is.
#   ops/restore.sh backups/ambulance-2026-10-14.dump.gpg           # drill
#   ops/restore.sh backups/ambulance-2026-10-14.dump.gpg --live    # real restore; asks first, stops app and backup meanwhile
set -euo pipefail
cd "$(dirname "$0")/.."
f="${1:?usage: ops/restore.sh backups/FILE.dump.gpg [--live]}"
[ -s "$f" ] || { echo "missing or empty: $f" >&2; exit 1; }
sql() { docker compose exec -T db psql -U postgres -v ON_ERROR_STOP=1 -qAt "$@" </dev/null; }  # keep stdin for the prompt

sql -d postgres -c 'DROP DATABASE IF EXISTS restore_drill' -c 'CREATE DATABASE restore_drill'
case "$f" in
  *.gpg) dec() { docker compose run --rm --no-deps -T --entrypoint bash backup -c \
    'gpg --batch --quiet --pinentry-mode loopback --passphrase-fd 3 --decrypt 3<<<"$BACKUP_PASSPHRASE"'; };;
  *) dec() { cat; };;
esac
dec < "$f" | docker compose exec -T db pg_restore -U postgres -d restore_drill --single-transaction
echo "rows per table in $f:"
sql -d restore_drill -F ' ' -c "SELECT table_name, (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I',
  table_name), false, true, '')))[1] FROM information_schema.tables WHERE table_schema = 'public' ORDER BY 1"

if [ "${2:-}" != --live ]; then
  sql -d postgres -c 'DROP DATABASE restore_drill'
  echo "drill OK: $f restores cleanly"; exit 0
fi
[ -z "$(sql -d postgres -c "SELECT 1 FROM pg_database WHERE datname = 'ambulance_before_restore'")" ] ||
  { echo "ambulance_before_restore exists from an earlier restore; drop it first" >&2; exit 1; }
read -r -p "Replace the live database with this dump? Type RESTORE: " ok || true
[ "$ok" = RESTORE ] || { echo "aborted; live data untouched"; exit 1; }
docker compose stop app backup
sql -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
  WHERE datname IN ('ambulance', 'restore_drill') AND pid <> pg_backend_pid()" >/dev/null
sql -d postgres -c 'ALTER DATABASE ambulance RENAME TO ambulance_before_restore' \
  -c 'ALTER DATABASE restore_drill RENAME TO ambulance'
docker compose up -d  # re-runs migrate: brings an older dump up to the current schema and re-applies the app role's grants
echo "restored. Check the console, then drop the old copy:"
echo "  docker compose exec db psql -U postgres -c 'DROP DATABASE ambulance_before_restore'"

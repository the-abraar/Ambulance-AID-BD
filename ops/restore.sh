#!/usr/bin/env bash
# Restore a dump from backups/ into a scratch database and print its row counts (the drill).
# With --live it then swaps the restored copy in as `ambulance` and keeps the old one as `ambulance_before_restore`.
# Treat every dump as untrusted: restore only dumps from your own storage.
# - A .gpg dump is decrypted in a throwaway `backup` container with BACKUP_PASSPHRASE from .env, and is refused unless
#   gpg confirms it was really encrypted with it (gpg --decrypt alone also passes unencrypted gpg files).
# - A plain .dump is refused unless you pass --unencrypted.
# - The dump is loaded and counted by `restore_loader`, a role without superuser rights, so it cannot run programs.
#   ops/restore.sh backups/ambulance-2026-10-14.dump.gpg           # drill
#   ops/restore.sh backups/ambulance-2026-10-14.dump.gpg --live    # real restore; asks first, stops app and backup meanwhile
set -euo pipefail
cd "$(dirname "$0")/.."
f="${1:?usage: ops/restore.sh backups/FILE.dump.gpg [--live] [--unencrypted]}"
live=; plain=
for a in "${@:2}"; do
  case "$a" in --live) live=1;; --unencrypted) plain=1;; *) echo "unknown option: $a" >&2; exit 2;; esac
done
[ -s "$f" ] || { echo "missing or empty: $f" >&2; exit 1; }
sql() { docker compose exec -T db psql -U postgres -v ON_ERROR_STOP=1 -qAt "$@" </dev/null; }  # keep stdin for the prompt

case "$f" in
  # Decrypt to a temp file inside the container and print it only once gpg's status says it really decrypted.
  # A file from `gpg --store` has no encryption at all and decrypts with any passphrase, so the exit code is not enough.
  *.gpg) dec() { docker compose run --rm --no-deps -T --entrypoint bash backup -c '
    t=$(mktemp) s=$(mktemp); rc=0
    gpg --batch --quiet --yes --pinentry-mode loopback --passphrase-fd 3 --status-file "$s" --decrypt -o "$t" \
      3<<<"$BACKUP_PASSPHRASE" || rc=$?
    if [ $rc = 0 ] && grep -q "^\[GNUPG:\] DECRYPTION_OKAY" "$s" && grep -q "^\[GNUPG:\] END_DECRYPTION" "$s" &&
       ! grep -q "^\[GNUPG:\] ERROR" "$s"; then cat "$t"
    else echo "refusing: not a dump encrypted with BACKUP_PASSPHRASE" >&2; exit 1; fi'; };;
  *) [ -n "$plain" ] || { echo "refusing $f: not a .gpg dump; pass --unencrypted if you made this dump yourself" >&2; exit 1; }
     dec() { cat; };;
esac

sql -d postgres -c "DO \$\$BEGIN CREATE ROLE restore_loader LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END\$\$" \
  -c 'ALTER ROLE restore_loader LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB'
# ALTER ROLE keeps role memberships: an old restore_loader in one of these could still run programs or touch server files.
bad=$(sql -d postgres -c "SELECT string_agg(r, ', ') FROM unnest(ARRAY['pg_execute_server_program',
  'pg_read_server_files', 'pg_write_server_files']) AS r WHERE pg_has_role('restore_loader', r, 'MEMBER')")
[ -z "$bad" ] || { echo "refusing: restore_loader is a member of $bad; run DROP ROLE restore_loader (or revoke that) first" >&2; exit 1; }
sql -d postgres -c 'DROP DATABASE IF EXISTS restore_drill' -c 'CREATE DATABASE restore_drill OWNER restore_loader'
dec < "$f" | docker compose exec -T db pg_restore -U restore_loader -d restore_drill --no-owner --no-privileges --single-transaction
echo "rows per table in $f:"
# As restore_loader too: counting a view runs its functions as the caller.
docker compose exec -T db psql -U restore_loader -d restore_drill -v ON_ERROR_STOP=1 -qAt -F ' ' -c "SELECT table_name,
  (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I', table_name), false, true, '')))[1]
  FROM information_schema.tables WHERE table_schema = 'public' ORDER BY 1" </dev/null

if [ -z "$live" ]; then
  sql -d postgres -c 'DROP DATABASE restore_drill'
  echo "drill OK: $f restores cleanly"; exit 0
fi
[ -z "$(sql -d postgres -c "SELECT 1 FROM pg_database WHERE datname = 'ambulance_before_restore'")" ] ||
  { echo "ambulance_before_restore exists from an earlier restore; drop it first" >&2; exit 1; }
read -r -p "Replace the live database with this dump? Type RESTORE: " ok || true
[ "$ok" = RESTORE ] || { echo "aborted; live data untouched"; exit 1; }
docker compose stop app backup
sql -d restore_drill -c 'REASSIGN OWNED BY restore_loader TO postgres'  # migrate and the app's grants expect postgres
sql -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
  WHERE datname IN ('ambulance', 'restore_drill') AND pid <> pg_backend_pid()" >/dev/null
sql -d postgres -c 'ALTER DATABASE ambulance RENAME TO ambulance_before_restore' \
  -c 'ALTER DATABASE restore_drill RENAME TO ambulance'
docker compose up -d  # re-runs migrate: brings an older dump up to the current schema and re-applies the app role's grants
echo "restored. Check the console, then drop the old copy:"
echo "  docker compose exec db psql -U postgres -c 'DROP DATABASE ambulance_before_restore'"

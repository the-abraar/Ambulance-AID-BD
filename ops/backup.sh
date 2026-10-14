#!/usr/bin/env bash
# Compose `backup` sidecar: one pg_dump at start, then nightly at 20:00 UTC (02:00 Dhaka); keeps the newest 14 dumps.
# Connection comes from PGHOST/PGUSER/PGPASSWORD/PGDATABASE. Restore with ops/restore.sh (see docs/deploy.md).
# shortcut: dumps stay on this host's ./backups; copy them offsite before real data (owner TODO in docs/deploy.md).
set -uo pipefail  # no -e: one failed dump must not stop the next night's
while :; do
  f=/backups/ambulance-$(date -u +%F).dump
  if pg_dump -Fc -f "$f.partial"; then
    mv "$f.partial" "$f" && echo "backup ok: $f ($(stat -c %s "$f") bytes)"
    ls -1t /backups/ambulance-*.dump | tail -n +15 | xargs -r rm --
  else
    rm -f "$f.partial"; echo "BACKUP FAILED at $(date -u +%FT%TZ)" >&2
  fi
  s=$(( (72000 - $(date -u +%s) % 86400 + 86400) % 86400 ))
  sleep $(( s > 0 ? s : 86400 ))
done

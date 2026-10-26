#!/usr/bin/env bash
# Compose `backup` sidecar: one pg_dump at start, then nightly at 20:00 UTC (02:00 Dhaka); keeps the newest 14 dumps.
# Each dump is encrypted with BACKUP_PASSPHRASE (gpg, AES-256) before it touches the disk: ambulance-DATE.dump.gpg.
# Connection comes from PGHOST/PGUSER/PGPASSWORD/PGDATABASE. Restore with ops/restore.sh; offsite copy: ops/offsite.sh.
set -uo pipefail  # no -e: one failed dump must not stop the next night's
p="${BACKUP_PASSPHRASE:-}"
case "$p" in *change-me*) p=;; esac
[ ${#p} -ge 24 ] || { echo "refusing to start: set BACKUP_PASSPHRASE in .env (openssl rand -hex 32)" >&2; exit 1; }
export GNUPGHOME=/tmp/gnupg; mkdir -p -m 700 "$GNUPGHOME"
while :; do
  f=/backups/ambulance-$(date -u +%F).dump.gpg
  if pg_dump -Fc | gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 3 --symmetric --cipher-algo AES256 \
      -o "$f.partial" 3<<<"$p"; then
    mv "$f.partial" "$f" && echo "backup ok: $f ($(stat -c %s "$f") bytes)"
    ls -1t /backups/ambulance-*.dump* | tail -n +15 | xargs -r rm --  # also ages out pre-encryption .dump files
  else
    rm -f "$f.partial"; echo "BACKUP FAILED at $(date -u +%FT%TZ)" >&2
  fi
  s=$(( (72000 - $(date -u +%s) % 86400 + 86400) % 86400 ))
  sleep $(( s > 0 ? s : 86400 ))
done

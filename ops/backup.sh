#!/usr/bin/env bash
# Compose `backup` sidecar: one pg_dump at start, then nightly at 20:00 UTC (02:00 Dhaka); dumps are deleted after 14 days.
# Each dump is encrypted with BACKUP_PASSPHRASE (gpg, AES-256) before it touches the disk: ambulance-DATE.dump.gpg.
# Connection comes from PGHOST/PGUSER/PGPASSWORD/PGDATABASE. Restore with ops/restore.sh; offsite copy: ops/offsite.sh.
set -uo pipefail  # no -e: one failed dump must not stop the next night's
p="${BACKUP_PASSPHRASE:-}"
case "$p" in *change-me*) p=;; esac
[ ${#p} -ge 24 ] || { echo "refusing to start: set BACKUP_PASSPHRASE in .env (openssl rand -hex 32)" >&2; exit 1; }
export GNUPGHOME="${GNUPGHOME:-/tmp/gnupg}"; mkdir -p -m 700 "$GNUPGHOME"
d="${BACKUP_DIR:-/backups}"  # overridden only by backend/tests/test_ops_backup.py
while :; do
  f=$d/ambulance-$(date -u +%F).dump.gpg
  if pg_dump -Fc | gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 3 --symmetric --cipher-algo AES256 \
      -o "$f.partial" 3<<<"$p"; then
    mv "$f.partial" "$f" && echo "backup ok: $f ($(stat -c %s "$f") bytes)"
  else
    rm -f "$f.partial"; echo "BACKUP FAILED at $(date -u +%FT%TZ)" >&2
  fi
  # 14-day retention (the promise in docs/driver-consent-bn-draft.md), kept after failed nights too; also ages out
  # pre-encryption .dump files. 13d22h, not 14d: tonight's run may start a little earlier than the one 14 nights ago.
  find "$d" -maxdepth 1 -name 'ambulance-*.dump*' -mmin +$(( 14 * 1440 - 120 )) -delete
  s=$(( (72000 - $(date -u +%s) % 86400 + 86400) % 86400 ))
  sleep $(( s > 0 ? s : 86400 ))
done

#!/bin/sh
# Compose `offsite` sidecar (profile `offsite`, off by default): copies the encrypted dumps in ./backups to
# $BACKUP_OFFSITE (an rclone remote from ./rclone.conf, e.g. `offsite:bucket/ambulance`) at start, then nightly at
# 20:30 UTC, after ops/backup.sh. Copies older than 15 days are deleted there, to keep the 14-day retention promise.
# Only *.dump.gpg leaves the host; the passphrase never does. Setup: docs/deploy.md, "Offsite copy".
set -u
: "${BACKUP_OFFSITE:?set BACKUP_OFFSITE in .env, e.g. offsite:bucket/ambulance}"
while :; do
  if rclone copy /backups "$BACKUP_OFFSITE" --include 'ambulance-*.dump.gpg' &&
     rclone delete "$BACKUP_OFFSITE" --include 'ambulance-*.dump.gpg' --min-age 15d; then
    echo "offsite ok: $(rclone lsf "$BACKUP_OFFSITE" --include 'ambulance-*.dump.gpg' | wc -l) dumps at $BACKUP_OFFSITE"
  else
    echo "OFFSITE FAILED at $(date -u +%FT%TZ)" >&2
  fi
  s=$(( (73800 - $(date -u +%s) % 86400 + 86400) % 86400 ))
  sleep $(( s > 0 ? s : 86400 ))
done

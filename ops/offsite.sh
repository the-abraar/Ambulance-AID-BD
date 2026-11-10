#!/bin/sh
# Compose `offsite` sidecar (profile `offsite`, off by default): copies the encrypted dumps in ./backups to
# $BACKUP_OFFSITE (an rclone remote from ./rclone.conf, e.g. `offsite:bucket/ambulance`) at start, then nightly at
# 20:30 UTC, after ops/backup.sh. Copies older than 14 days are deleted there, the same retention as on the host,
# unless BACKUP_OFFSITE_PRUNE=0 (a bucket whose own lifecycle rule deletes them and whose key cannot delete).
# A run is good only when the copy and the cleanup both worked and the newest local dump is on the remote; it then
# touches /tmp/offsite-ok, and the compose health check turns unhealthy when that is over 26 hours old. A bad run
# (or no dump yet, on a fresh start) retries within the hour.
# Only *.dump.gpg leaves the host; the passphrase never does. Setup: docs/deploy.md, "Offsite copy".
set -u
: "${BACKUP_OFFSITE:?set BACKUP_OFFSITE in .env, e.g. offsite:bucket/ambulance}"
d="${BACKUP_DIR:-/backups}" okf="${OFFSITE_OK_FILE:-/tmp/offsite-ok}"  # overridden only by backend/tests/test_ops_offsite.py
inc='ambulance-*.dump.gpg'
while :; do
  ok=1
  rclone copy "$d" "$BACKUP_OFFSITE" --include "$inc" || ok=
  # Runs even when the copy failed, so old copies never outlive the 14 days.
  [ "${BACKUP_OFFSITE_PRUNE:-1}" = 0 ] || rclone delete "$BACKUP_OFFSITE" --include "$inc" --min-age 14d || ok=
  newest=$(cd "$d" && ls -t $inc 2>/dev/null | head -n 1)
  remote=$(rclone lsf "$BACKUP_OFFSITE" --include "$inc") || ok=
  s=$(( (73800 - $(date -u +%s) % 86400 + 86400) % 86400 ))
  if [ -n "$ok" ] && [ -n "$newest" ] && printf '%s\n' "$remote" | grep -qxF "$newest"; then
    touch "$okf"
    echo "offsite ok: $(printf '%s\n' "$remote" | grep -c .) dumps at $BACKUP_OFFSITE, newest $newest"
  else
    echo "OFFSITE FAILED at $(date -u +%FT%TZ)$([ -n "$newest" ] || echo ': no local dump yet')" >&2
    [ "$s" -gt 3600 ] && s=3600
  fi
  sleep $(( s > 0 ? s : 86400 ))
done

"""ops/offsite.sh: cleanup runs even when the upload fails, and the health marker means the newest dump is offsite.

Runs the real script with a stub rclone (a local folder as the remote) and a stub sleep that ends the loop after one run.
"""
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "ops" / "offsite.sh"
DAY = 86400

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh")

RCLONE = """#!/bin/sh
cmd=$1; shift
case $cmd in
  copy) [ -n "${FAIL_COPY:-}" ] && exit 1; cp -p "$1"/ambulance-*.dump.gpg "$R"/ 2>/dev/null; exit 0;;
  delete) echo delete >> "$R/../calls"; [ -n "${FAIL_DELETE:-}" ] && exit 1
          find "$R" -name 'ambulance-*.dump.gpg' -mtime +13 -delete;;
  lsf) ls "$R";;
esac
"""


def run_once(tmp_path, local=(), remote=(), **env):
    stubs, d, r = tmp_path / "stubs", tmp_path / "b", tmp_path / "remote"
    for p in (stubs, d, r): p.mkdir(exist_ok=True)
    (stubs / "rclone").write_text(RCLONE)
    (stubs / "sleep").write_text('#!/bin/sh\necho "$1" > "$R/../slept"; kill -TERM $PPID\n')
    for s in stubs.iterdir(): s.chmod(0o755)
    for folder, files in ((d, local), (r, remote)):
        for name, age_days in files:
            f = folder / name; f.write_text("x"); t = time.time() - age_days * DAY; os.utime(f, (t, t))
    ok = tmp_path / "ok"
    e = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "BACKUP_DIR": str(d), "R": str(r),
         "BACKUP_OFFSITE": "remote:x", "OFFSITE_OK_FILE": str(ok), **env}
    p = subprocess.run(["sh", str(SCRIPT)], env=e, capture_output=True, text=True, timeout=30)
    calls = (tmp_path / "calls").read_text() if (tmp_path / "calls").exists() else ""
    return p, ok.exists(), sorted(x.name for x in r.iterdir()), calls, int((tmp_path / "slept").read_text())


def test_good_run_copies_prunes_and_marks_healthy(tmp_path):
    p, ok, remote, _, slept = run_once(tmp_path, local=[("ambulance-new.dump.gpg", 0)], remote=[("ambulance-old.dump.gpg", 20)])
    assert ok and remote == ["ambulance-new.dump.gpg"], p.stderr
    assert "newest ambulance-new.dump.gpg" in p.stdout


def test_failed_upload_still_prunes_and_is_not_healthy(tmp_path):
    p, ok, remote, calls, slept = run_once(tmp_path, local=[("ambulance-new.dump.gpg", 0)],
                                           remote=[("ambulance-old.dump.gpg", 20)], FAIL_COPY="1")
    assert not ok and remote == [] and "delete" in calls
    assert "OFFSITE FAILED" in p.stderr and slept <= 3600  # retried within the hour


def test_no_local_dump_yet_is_not_healthy(tmp_path):
    p, ok, remote, _, slept = run_once(tmp_path)
    assert not ok and "no local dump yet" in p.stderr and slept <= 3600


def test_failed_cleanup_is_not_healthy(tmp_path):
    p, ok, *_ = run_once(tmp_path, local=[("ambulance-new.dump.gpg", 0)], FAIL_DELETE="1")
    assert not ok


def test_prune_off_skips_the_delete(tmp_path):
    p, ok, remote, calls, _ = run_once(tmp_path, local=[("ambulance-new.dump.gpg", 0)],
                                       remote=[("ambulance-old.dump.gpg", 20)], BACKUP_OFFSITE_PRUNE="0")
    assert ok and calls == "" and "ambulance-old.dump.gpg" in remote

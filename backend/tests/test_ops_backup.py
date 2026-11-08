"""ops/backup.sh retention: dumps are deleted by age (14 days), after failed nights as well as good ones.

Runs the real script with stub pg_dump/gpg/sleep on PATH; the stub sleep ends the loop after one night.
"""
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "ops" / "backup.sh"
HOUR = 3600

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def run_one_night(tmp_path, pg_dump_exit):
    stubs = tmp_path / "stubs"; stubs.mkdir()
    (stubs / "pg_dump").write_text(f"#!/bin/sh\necho dump\nexit {pg_dump_exit}\n")
    (stubs / "gpg").write_text('#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && o=$2; shift; done\ncat > "$o"\n')
    (stubs / "sleep").write_text("#!/bin/sh\nkill -TERM $PPID\n")
    for s in stubs.iterdir(): s.chmod(0o755)
    env = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "BACKUP_DIR": str(tmp_path / "b"),
           "GNUPGHOME": str(tmp_path / "gnupg"), "BACKUP_PASSPHRASE": "x" * 32}
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)


def seed(tmp_path, ages_h, suffix=".dump.gpg"):
    d = tmp_path / "b"; d.mkdir(exist_ok=True)
    now = time.time()
    for i, h in enumerate(ages_h):
        f = d / f"ambulance-2000-01-{i + 1:02d}{suffix}"
        f.write_text("old")
        os.utime(f, (now - h * HOUR, now - h * HOUR))
    return d


def ages_left(d):
    now = time.time()
    return sorted(round((now - f.stat().st_mtime) / HOUR) for f in d.iterdir() if f.name.startswith("ambulance-2000"))


@pytest.mark.parametrize("pg_dump_exit", [0, 1])
def test_dumps_older_than_14_days_go_on_good_and_failed_nights(tmp_path, pg_dump_exit):
    d = seed(tmp_path, [24 * n + 2 for n in range(1, 21)])  # 20 nightly dumps, 26 h .. 20 days old
    seed(tmp_path, [24 * 30], suffix=".dump")  # a pre-encryption plain dump ages out too
    r = run_one_night(tmp_path, pg_dump_exit)
    assert ages_left(d) == [24 * n + 2 for n in range(1, 14)], r.stderr
    assert not list(d.glob("*.partial"))
    today = list(d.glob(f"ambulance-{time.strftime('%Y-%m-%d', time.gmtime())}.dump.gpg"))
    assert len(today) == (1 if pg_dump_exit == 0 else 0)
    assert ("BACKUP FAILED" in r.stderr) == bool(pg_dump_exit)


def test_dump_from_14_nights_ago_goes_even_if_tonight_ran_a_little_early(tmp_path):
    d = seed(tmp_path, [14 * 24 - 1, 13 * 24 + 23 - 3, 14 * 24 + 1])
    run_one_night(tmp_path, 0)
    assert ages_left(d) == [13 * 24 + 20]

"""End-to-end browser test against the REAL backend (not collected by pytest: name has no test_ prefix).

Run (from backend/):
    python3.11 -m venv .e2e && .e2e/bin/pip install -r requirements-dev.txt playwright && .e2e/bin/playwright install chromium
    .e2e/bin/python tests/e2e_browser.py [screenshot_dir]   # default: tests/shots/ (gitignored) + INDEX.txt
It creates a fresh SQLite DB in a temp dir, starts uvicorn on a free port, drives /console (1280 px) and /driver
(360 px, fake geolocation) with two browser contexts, and exits non-zero on the first failed check.
"""
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
INDEX = []
PATH = ["DISPATCHED", "EN_ROUTE_PICKUP", "AT_SCENE", "TRANSPORTING_PATIENT", "AT_HOSPITAL", "COMPLETED"]
BN = {"DISPATCHED": "প্রেরিত", "EN_ROUTE_PICKUP": "পিকআপের পথে", "AT_SCENE": "ঘটনাস্থলে",
      "TRANSPORTING_PATIENT": "রোগী নিয়ে যাচ্ছি", "AT_HOSPITAL": "হাসপাতালে পৌঁছেছি", "COMPLETED": "সম্পন্ন"}
EXPECTED_ERR = re.compile(r"Failed to load resource.*\b(401|404|409|429)\b")  # deliberate 401/409; 404 = no active mission
checks = 0


def ok(cond, msg):
    global checks
    checks += 1
    if not cond:
        raise AssertionError(msg)
    print("ok:", msg)


def main():
    tmp = tempfile.mkdtemp(prefix="e2e_")
    env = {**os.environ, "AMBULANCE_DB_PATH": f"{tmp}/e2e.db", "PYTHONPATH": str(ROOT)}
    out = subprocess.run([sys.executable, "-m", "app.bootstrap", "dispatcher", "alice"], env=env, cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    dtok = re.search(r"token=(\S+)", out).group(1)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    base = f"http://127.0.0.1:{port}"
    srv = subprocess.Popen([sys.executable, "-c", f"import uvicorn;from app.main import create_app;"
                            f"uvicorn.run(create_app(),host='127.0.0.1',port={port},log_level='warning')"], env=env, cwd=ROOT)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/console/"); break
            except Exception:
                time.sleep(0.1)
        run(base, dtok)
    finally:
        srv.terminate()
    (SHOTS / "INDEX.txt").write_text("\n".join(INDEX) + "\n")
    print(f"ALL OK ({checks} checks); screenshots in {SHOTS} (see INDEX.txt)")


def shot(page, name, what):
    page.screenshot(path=str(SHOTS / name))  # viewport only, never full_page
    INDEX.append(f"{name}: {what}")


def api(base, tok, path):
    r = urllib.request.Request(base + path, headers={"Authorization": "Bearer " + tok})
    return json.load(urllib.request.urlopen(r))


def run(base, dtok):
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch()

        def page_in(ctx):
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and errors.append(m.text))
            pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
            return pg

        cctx = b.new_context(viewport={"width": 1280, "height": 800})
        con = page_in(cctx)
        con.goto(base + "/console/")
        con.fill("#token", dtok); con.click("#login button")
        con.wait_for_function("document.getElementById('who').textContent==='connected'")
        con.fill("#newv [name=operator]", "RedCrescent"); con.fill("#newv [name=registration]", "DHK-E2E")
        con.click("#newv button")
        con.fill("#newd [name=name]", "Rahim"); con.click("#newd button")
        con.wait_for_selector("#newtok:not([hidden])")
        dr_tok = re.search(r":\s*(\S+)$", con.inner_text("#newtok")).group(1)
        con.wait_for_function("document.querySelector('#newm [name=veh]').options.length>1 && "
                              "document.querySelector('#newm [name=drv]').options.length>1")
        veh_id = con.eval_on_selector("#newm [name=veh]", "s=>s.options[1].value")

        def new_mission(addr):
            con.fill("#newm [name=lat]", "23.7808"); con.fill("#newm [name=lng]", "90.4167"); con.fill("#newm [name=addr]", addr)
            con.select_option("#newm [name=veh]", index=1); con.select_option("#newm [name=drv]", index=1)
            con.click("#newm button")
            con.wait_for_selector(f"#missions tbody tr:has-text('{addr}')")
        new_mission("Mirpur-10")
        row = con.locator("#missions tbody tr:has-text('Mirpur-10')")
        ok(row.inner_text().count("DISPATCHED") == 1, "console shows new mission DISPATCHED")
        btns = row.locator("button").all_inner_texts()
        ok(btns == ["-> CANCELLED", "Audit"], f"console offers only role-allowed action (got {btns})")

        dctx = b.new_context(viewport={"width": 360, "height": 740}, geolocation={"latitude": 23.78, "longitude": 90.41},
                             permissions=["geolocation"], service_workers="block")
        drv = page_in(dctx)
        drv.goto(base + "/driver/")
        shot(drv, "driver_360_login.png", "driver app 360x740, token login form")
        drv.fill("#tk", dr_tok); drv.click("#f button")
        drv.wait_for_selector(".badge")
        href = drv.get_attribute("#nav", "href")
        ok(href and "destination=23.7808,90.4167" in href, f"driver navigate link built from numbers ({href})")

        shot(drv, "driver_360_dispatched.png", "driver app 360x740, mission DISPATCHED with next-step button and navigate link")
        last_ts = None
        for i, st in enumerate(PATH):
            if st != "COMPLETED":  # terminal: driver has no current mission, so no badge
                ok(BN[st] in drv.inner_text(".badge"), f"driver badge shows Bangla label for {st}")
            con.click("#filter"); con.select_option("#filter", ""); con.evaluate("1")
            con.wait_for_function(f"[...document.querySelectorAll('#missions tbody tr')].some(r=>r.textContent.includes('Mirpur-10')&&r.cells[1].textContent==='{st}')", timeout=12000)
            ok(True, f"console reflects {st}")
            if st != "COMPLETED":
                time.sleep(5.2 if i else 0)  # app throttles pings to 1/5 s; headless fires one GPS event per set_geolocation
                dctx.set_geolocation({"latitude": 23.78 + i * 0.001, "longitude": 90.41 + i * 0.001})
                end = time.time() + 15; got = None
                while time.time() < end:
                    try:
                        got = api(base, dtok, f"/vehicles/{veh_id}/position")
                        if got["ts"] != last_ts and abs(got["lat"] - (23.78 + i * 0.001)) < 1e-6: break
                    except Exception:
                        pass
                    time.sleep(0.5)
                ok(got and got["ts"] != last_ts and abs(got["lat"] - (23.78 + i * 0.001)) < 1e-6, f"fresh ping arrived at {st}")
                last_ts = got["ts"]
                nxt = PATH[i + 1]
                drv.click(f"button.big[data-s={nxt}]")
                drv.click("dialog button[data-v='1']")
                drv.wait_for_function(f"!document.querySelector('.badge')||document.querySelector('.badge').textContent!==\"{BN[st]}\"")
        shot(drv, "driver_360_done.png", "driver app 360x740, no active mission after COMPLETED"); shot(con, "console_1280_done.png", "console 1280x800, Mirpur-10 mission COMPLETED, Audit only")
        ok("কোনো মিশন নেই" in drv.inner_text("#app"), "driver sees no-mission after terminal state")
        ok(api(base, dtok, "/missions?status=COMPLETED")[0]["status"] == "COMPLETED", "backend confirms COMPLETED")
        ok(con.locator("#missions tbody tr:has-text('Mirpur-10') button").all_inner_texts() == ["Audit"],
           "console offers no actions on terminal mission")

        # 409: dispatcher cancels while driver has the confirm dialog open; also English toggle
        new_mission("Gulshan-2")
        drv.click("#rf"); drv.wait_for_selector(".badge")
        drv.click("#lang")
        ok("Dispatched" in drv.inner_text(".badge") and drv.inner_text("#title") == "Driver", "English toggle labels")
        shot(drv, "driver_360_english.png", "driver app 360x740, English toggle on a new DISPATCHED mission")
        drv.click("button.big[data-s=EN_ROUTE_PICKUP]")
        ok(drv.is_visible("dialog"), "confirm dialog open")
        con.locator("#missions tbody tr:has-text('Gulshan-2') button:has-text('CANCELLED')").click()
        con.wait_for_function("[...document.querySelectorAll('#missions tbody tr')].some(r=>r.textContent.includes('Gulshan-2')&&r.cells[1].textContent==='CANCELLED')", timeout=12000)
        drv.click("dialog button[data-v='1']")
        drv.wait_for_selector("#status .err")
        ok("Mission changed" in drv.inner_text("#status"), "driver sees English 409 message")
        shot(drv, "driver_360_409.png", "driver app 360x740, 409 error shown after dispatcher cancelled the mission")
        ok(api(base, dtok, "/missions?status=CANCELLED")[0]["status"] == "CANCELLED", "mission stays CANCELLED")

        # denied GPS: the same driver in a browser without location permission, mission active again
        new_mission("Banani-1")
        den = page_in(b.new_context(viewport={"width": 360, "height": 740}, service_workers="block"))
        den.goto(base + "/driver/"); den.fill("#tk", dr_tok); den.click("#f button")
        den.wait_for_selector("#status .err")
        ok("জিপিএস অনুমতি নেই" in den.inner_text("#status"), "denied GPS shows the Bangla permission message")
        shot(den, "driver_360_gps_denied.png", "driver app 360x740, Bangla GPS-denied message on an active mission")

        # offline replay: pings taken offline are queued in localStorage, then sent once back online
        drv.click("#rf"); drv.wait_for_selector(".badge")
        queue = lambda: drv.evaluate("JSON.parse(localStorage.getItem('driver_ping_queue')||'[]')")
        time.sleep(5.2)  # past the app's 5 s ping throttle
        dctx.set_offline(True)
        dctx.set_geolocation({"latitude": 23.9, "longitude": 90.5})
        end = time.time() + 15
        while time.time() < end and not queue():
            time.sleep(0.3)
        ok(queue() and queue()[0]["lat"] == 23.9, "offline ping is queued in localStorage")
        shot(drv, "driver_360_offline.png", "driver app 360x740, offline banner with a queued ping")
        dctx.set_offline(False)
        end = time.time() + 20
        while time.time() < end and queue():
            time.sleep(0.5)
        ok(not queue(), "queue drained after going back online")
        ok(abs(api(base, dtok, f"/vehicles/{veh_id}/position")["lat"] - 23.9) < 1e-6, "replayed ping reached the server")

        # 429: two pings in a row from the driver's own token hit the 1 s per-vehicle limit
        codes = drv.evaluate("""async ([vid, tok]) => {
            const send = () => fetch(`/vehicles/${vid}/pings`, {method: 'POST', body: JSON.stringify({lat: 1, lng: 2, ts: new Date().toISOString()}),
              headers: {Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json'}}).then(r => r.status);
            return [await send(), await send(), await send()]; }""", [veh_id, dr_tok])
        ok(429 in codes, f"server answers 429 on rapid pings (got {codes})")

        # driver app's own 429 message: the server (stubbed here) refuses a ping
        drv.route("**/pings", lambda r: r.fulfill(status=429, body="{}"))
        time.sleep(5.2)  # past the app's 5 s ping throttle
        dctx.set_geolocation({"latitude": 23.91, "longitude": 90.51})
        drv.wait_for_function("document.getElementById('status').textContent.includes('Too many requests')", timeout=15000)
        ok(True, "driver app shows its 429 message when a ping is refused")
        shot(drv, "driver_360_429.png", "driver app 360x740, English 429 'Too many requests' message")
        drv.unroute("**/pings")

        # token expiry banner: /me stubbed with a token that expires in 2 days
        soon = page_in(b.new_context(viewport={"width": 360, "height": 740}, service_workers="block"))
        exp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 2 * 86400))
        soon.route("**/me", lambda r: r.fulfill(json={"role": "driver", "user_id": "u", "driver_id": "d", "vehicle_id": None, "token_expires_at": exp}))
        soon.route("**/missions/current", lambda r: r.fulfill(status=404, json={"detail": "no active mission"}))
        soon.route("**/meta/transitions", lambda r: r.fulfill(json={}))
        soon.goto(base + "/driver/"); soon.fill("#tk", "any"); soon.click("#f button")
        soon.wait_for_function("document.getElementById('status').textContent.includes('৭ দিনের মধ্যে')", timeout=10000)
        ok(True, "driver sees the token-expiry banner within 7 days of expiry")
        shot(soon, "driver_360_token_expiry.png", "driver app 360x740, Bangla token-expiry banner")

        # console token buttons: rotate kills the old token, revoke kills the new one
        con.on("dialog", lambda d: d.accept())
        tok_ok = lambda t: urllib.request.urlopen(urllib.request.Request(base + "/me", headers={"Authorization": "Bearer " + t})).status
        def tok_dead(t):
            try:
                tok_ok(t); return False
            except urllib.error.HTTPError as e:
                return e.code == 401
        row = con.locator("#drivers tbody tr:has-text('Rahim')")
        row.locator("button:has-text('Rotate token')").click()
        con.wait_for_function("document.getElementById('newtok').textContent.includes('New token for Rahim')")
        new_tok = re.search(r":\s*(\S+)$", con.inner_text("#newtok")).group(1)
        ok(tok_dead(dr_tok) and tok_ok(new_tok) == 200, "console rotate: old driver token dead, new one works")
        shot(con, "console_1280_token_rotated.png", "console 1280x800, new driver token shown once after rotate")
        row.locator("button:has-text('Revoke')").click()
        con.wait_for_selector(".toast:has-text('Token revoked')")
        ok(tok_dead(new_tok), "console revoke: driver token no longer works")

        # 401: bad token
        bctx = b.new_context(viewport={"width": 360, "height": 740})
        bad = page_in(bctx)
        bad.goto(base + "/driver/"); bad.fill("#tk", "bad-token"); bad.click("#f button")
        bad.wait_for_selector("#status .err")
        ok("টোকেন বাতিল" in bad.inner_text("#status") and bad.is_visible("#tk"), "401 shows Bangla message and login form")
        shot(bad, "driver_360_401.png", "driver app 360x740, Bangla 401 message with login form")
        shot(con, "console_1280_final.png", "console 1280x800, Mirpur-10 COMPLETED and Gulshan-2 CANCELLED")
        b.close()
    bad_errs = [e for e in errors if not EXPECTED_ERR.search(e)]
    ok(not bad_errs, f"no unexpected console errors (expected 401/404/409/429 resource errors seen: {len(errors) - len(bad_errs)}; unexpected: {bad_errs})")


if __name__ == "__main__":
    main()

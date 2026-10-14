"""End-to-end browser test against the REAL backend (not collected by pytest: name has no test_ prefix).

Run (from backend/):
    python3.11 -m venv .e2e && .e2e/bin/pip install -r requirements-dev.txt playwright && .e2e/bin/playwright install chromium
    .e2e/bin/python tests/e2e_browser.py [screenshot_dir]   # default: tests/shots/ (gitignored) + INDEX.txt
It creates a fresh SQLite DB in a temp dir, starts uvicorn on a free port, drives /console (1280 px) and /driver
(360 px, fake geolocation, stubbed alerts, wake lock and native bridge) in several browser contexts, and exits
non-zero on the first failed check.
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
# Records what the driver app's new-mission alert and wake lock do (real WebAudio, counted oscillators).
ALERT_STUBS = """
window.__al = {vib: 0, osc: 0, notes: [], perm: 'default', wake: 0};
navigator.vibrate = () => { __al.vib++; return true; };
const _osc = AudioContext.prototype.createOscillator;
AudioContext.prototype.createOscillator = function () { __al.osc++; return _osc.call(this); };
window.Notification = class { constructor(t, o) { __al.notes.push(t + ': ' + o.body); }
  static get permission() { return __al.perm; } static async requestPermission() { return (__al.perm = 'granted'); } };
Object.defineProperty(navigator, 'wakeLock', {value: {request: async () => { __al.wake++;
  const s = {onrelease: null, release: async () => { __al.wake--; s.onrelease && s.onrelease(); }}; return s; }}});
"""
# The Android wrapper's contract: window.AmbulanceNative with startTracking(json), stopTracking(), isTracking().
BRIDGE = """
window.__calls = []; window.__watches = 0;
const _w = navigator.geolocation.watchPosition.bind(navigator.geolocation);
navigator.geolocation.watchPosition = (...a) => { __watches++; return _w(...a); };
window.AmbulanceNative = {on: false, startTracking(j) { __calls.push(['start', JSON.parse(j)]); this.on = true; },
  stopTracking() { __calls.push(['stop']); this.on = false; }, isTracking() { return this.on; }};
"""
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
    out = subprocess.run([sys.executable, "-m", "app.bootstrap", "admin", "alice"], env=env, cwd=ROOT,
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


def api(base, tok, path, body=None, method=None):
    r = urllib.request.Request(base + path, None if body is None else json.dumps(body).encode(), method=method,
                               headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    with urllib.request.urlopen(r) as resp:
        return json.loads(resp.read() or b"null")


def wait_until(fn, what, secs=15):
    end = time.time() + secs
    while time.time() < end and not fn():
        time.sleep(0.3)
    ok(fn(), what)


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
        dctx.add_init_script(ALERT_STUBS)
        drv = page_in(dctx)
        drv.goto(base + "/driver/")
        shot(drv, "driver_360_login.png", "driver app 360x740, 6-digit pairing code form")
        drv.fill("#code", "000000"); drv.click("#f button")
        drv.wait_for_function("document.getElementById('status').textContent.includes('কোডটি ভুল')")
        ok(drv.is_visible("#code"), "wrong pairing code: Bangla message, still on the code form")
        rahim = next(d["driver_id"] for d in api(base, dtok, "/drivers") if d["name"] == "Rahim")
        drv.fill("#code", api(base, dtok, f"/drivers/{rahim}/pairing-code", {}, "POST")["code"]); drv.click("#f button")
        drv.wait_for_selector(".card.new")
        ok(len(drv.evaluate("localStorage.getItem('tok')") or "") > 20, "6-digit code signs in; token kept in localStorage")
        drv.wait_for_function("__al.osc > 0 && __al.vib > 0 && document.title.includes('নতুন মিশন')", timeout=8000)
        ok(not drv.is_visible("button.big[data-s]"), "new mission alert: siren, vibration, flashing title; steps wait for Accept")
        drv.click("#al")
        drv.wait_for_function("__al.notes.length === 1 && __al.notes[0].includes('Mirpur-10')", timeout=5000)
        ok(True, "alerts button asks notification permission on a tap; one notification carries the address")
        href = drv.get_attribute("#nav", "href")
        ok(href and "destination=23.7808,90.4167" in href, f"driver navigate link built from numbers ({href})")
        shot(drv, "driver_360_new_mission.png", "driver app 360x740, flashing NEW MISSION card with Navigate and Accept")
        mirpur = next(m for m in api(base, dtok, "/missions?active=true") if m["pickup_address"] == "Mirpur-10")["mission_id"]
        drv.click("#ack"); drv.wait_for_selector(".badge")
        ok(api(base, dtok, f"/missions/{mirpur}")["acknowledged_at"], "Accept calls /ack: acknowledged_at is set")
        osc = drv.evaluate("__al.osc"); time.sleep(3.5)
        ok(drv.evaluate("__al.osc") == osc and drv.title() == "Driver", "alert stops after Accept")
        ok(drv.evaluate("__al.wake") == 1, "screen wake lock held during the mission")

        shot(drv, "driver_360_dispatched.png", "driver app 360x740, mission DISPATCHED with next-step button and navigate link")
        last_ts = None
        for i, st in enumerate(PATH):
            if st != "COMPLETED":  # terminal: the "mission completed" card has no badge
                ok(BN[st] in drv.inner_text(".badge"), f"driver badge shows Bangla label for {st}")
            con.click("#filter"); con.select_option("#filter", ""); con.evaluate("1")
            con.wait_for_function(f"[...document.querySelectorAll('#missions tbody tr')].some(r=>r.textContent.includes('Mirpur-10')&&r.cells[1].textContent==='{st}')", timeout=12000)
            ok(True, f"console reflects {st}")
            if st != "COMPLETED":
                time.sleep(5.2)  # app throttles pings to 1/5 s; headless fires one GPS event per new position
                lat = 23.781 + i * 0.001
                dctx.set_geolocation({"latitude": lat, "longitude": 90.41 + i * 0.001})
                end = time.time() + 15; got = None
                while time.time() < end:
                    try:
                        got = api(base, dtok, f"/vehicles/{veh_id}/position")
                        if got["ts"] != last_ts and abs(got["lat"] - lat) < 1e-6: break
                    except Exception:
                        pass
                    time.sleep(0.5)
                fresh = got and got["ts"] != last_ts and abs(got["lat"] - lat) < 1e-6
                if not fresh:
                    print("driver status:", drv.inner_text("#status"), "queue:", drv.evaluate("localStorage.getItem('driver_ping_queue')"))
                ok(fresh, f"fresh ping arrived at {st}")
                last_ts = got["ts"]
                nxt = PATH[i + 1]
                drv.click(f"button.big[data-s={nxt}]")
                drv.click("dialog button[data-v='1']")
                drv.wait_for_function(f"!document.querySelector('.badge')||document.querySelector('.badge').textContent!==\"{BN[st]}\"")
        shot(drv, "driver_360_done.png", "driver app 360x740, 'mission completed' card after COMPLETED"); shot(con, "console_1280_done.png", "console 1280x800, Mirpur-10 mission COMPLETED, Audit only")
        ok("মিশন সম্পন্ন" in drv.inner_text("#app"), "driver sees 'mission completed' after the terminal state (B15)")
        ok(drv.evaluate("__al.wake") == 0, "wake lock released after the mission")
        again = page_in(dctx); again.goto(base + "/driver/"); again.wait_for_selector(".card.ended")
        ok(True, "a new tab (installed app reopened) is still signed in: token in localStorage"); again.close()
        ok(api(base, dtok, "/missions?status=COMPLETED")[0]["status"] == "COMPLETED", "backend confirms COMPLETED")
        ok(con.locator("#missions tbody tr:has-text('Mirpur-10') button").all_inner_texts() == ["Audit"],
           "console offers no actions on terminal mission")

        # 409: dispatcher cancels while driver has the confirm dialog open; also English toggle
        new_mission("Gulshan-2")
        drv.click("#rf"); drv.wait_for_selector("#ack"); drv.click("#ack"); drv.wait_for_selector(".badge")
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
        drv.wait_for_selector(".card.ended")
        ok("Cancelled by dispatcher" in drv.inner_text("#app"), "driver sees 'Cancelled by dispatcher', not a blank screen (B15)")
        ok(api(base, dtok, "/missions?status=CANCELLED")[0]["status"] == "CANCELLED", "mission stays CANCELLED")

        # denied GPS: the same driver in a browser without location permission, mission active again
        new_mission("Banani-1")
        den = page_in(b.new_context(viewport={"width": 360, "height": 740}, service_workers="block"))
        drv_tok = drv.evaluate("localStorage.getItem('tok')")
        den.goto(base + "/driver/"); den.click("summary"); den.fill("#tk", drv_tok); den.click("#ft button")  # paste-token fallback
        den.wait_for_selector("#status .err")
        ok("জিপিএস অনুমতি নেই" in den.inner_text("#status"), "denied GPS shows the Bangla permission message")
        shot(den, "driver_360_gps_denied.png", "driver app 360x740, Bangla GPS-denied message on an active mission")

        # offline replay: pings taken offline are queued in localStorage, then sent once back online
        drv.click("#rf"); drv.wait_for_selector("#ack"); drv.click("#ack"); drv.wait_for_selector(".badge")
        queue = lambda: drv.evaluate("JSON.parse(localStorage.getItem('driver_ping_queue')||'[]')")
        # B9: entries queued for another mission or vehicle are dropped on replay, never sent
        banani = next(m for m in api(base, dtok, "/missions?active=true") if m["pickup_address"] == "Banani-1")["mission_id"]
        sent = []; drv.on("request", lambda r: "/pings" in r.url and sent.append(r.url))
        drv.evaluate("""([vid, mid]) => localStorage.setItem('driver_ping_queue', JSON.stringify([
            {lat: 23.7801, lng: 90.4101, ts: new Date().toISOString(), vehicle_id: vid, mission_id: 'old-mission'},
            {lat: 23.7802, lng: 90.4102, ts: new Date().toISOString(), vehicle_id: 'old-vehicle', mission_id: mid}]))""", [veh_id, banani])
        drv.click("#rf")
        wait_until(lambda: not queue(), "B9: queued pings of another mission or vehicle are dropped")
        ok(not any("old-vehicle" in u for u in sent) and api(base, dtok, f"/vehicles/{veh_id}/position")["lat"] not in (23.7801, 23.7802),
           "B9: they never reach the server")
        time.sleep(5.2)  # past the app's 5 s ping throttle
        dctx.set_offline(True)
        dctx.set_geolocation({"latitude": 23.79, "longitude": 90.42, "accuracy": 25})  # near the last fix: the server refuses jumps
        wait_until(lambda: queue(), "offline ping is queued in localStorage")
        ok(queue()[0]["lat"] == 23.79 and queue()[0]["accuracy"] == 25 and queue()[0]["vehicle_id"] == veh_id
           and queue()[0]["mission_id"] == banani, "queued ping keeps its accuracy, vehicle and mission")
        ok("up to 5 minutes" in drv.inner_text("#status"), "offline text says locations are kept up to 5 minutes")
        shot(drv, "driver_360_offline.png", "driver app 360x740, offline banner with a queued ping")
        dctx.set_offline(False)
        wait_until(lambda: not queue(), "queue drained after going back online", 20)
        pos = api(base, dtok, f"/vehicles/{veh_id}/position")
        ok(abs(pos["lat"] - 23.79) < 1e-6 and pos["accuracy"] == 25, "replayed ping reached the server with its accuracy")

        # 429: two pings in a row from the driver's own token hit the 1 s per-vehicle limit
        codes = drv.evaluate("""async ([vid, tok]) => {
            const send = () => fetch(`/vehicles/${vid}/pings`, {method: 'POST', body: JSON.stringify({lat: 23.79, lng: 90.42, ts: new Date().toISOString()}),
              headers: {Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json'}}).then(r => r.status);
            return [await send(), await send(), await send()]; }""", [veh_id, drv_tok])
        ok(429 in codes, f"server answers 429 on rapid pings (got {codes})")

        # driver app's own 429 message: the server (stubbed here) refuses a ping
        drv.route("**/pings", lambda r: r.fulfill(status=429, body="{}"))
        time.sleep(5.2)  # past the app's 5 s ping throttle
        dctx.set_geolocation({"latitude": 23.791, "longitude": 90.421})
        drv.wait_for_function("document.getElementById('status').textContent.includes('Too many requests')", timeout=15000)
        ok(True, "driver app shows its 429 message when a ping is refused")
        shot(drv, "driver_360_429.png", "driver app 360x740, English 429 'Too many requests' message")
        drv.unroute("**/pings")
        # B4: the server accepts a skewed phone clock and reports it; the app tells the driver to fix the clock
        drv.route("**/pings", lambda r: r.fulfill(status=201, json={"ok": True, "clock_skew_s": 125.0}))
        time.sleep(5.2)
        dctx.set_geolocation({"latitude": 23.792, "longitude": 90.422})
        drv.wait_for_function("document.getElementById('status').textContent.includes('Phone clock is off')", timeout=15000)
        ok(True, "B4: clock skew over 60 s shows the phone-clock message")
        shot(drv, "driver_360_clock_skew.png", "driver app 360x740, English phone-clock-wrong message")
        drv.unroute("**/pings")

        # token expiry banner: /me stubbed with a token that expires in 2 days
        # B7 in the same stubbed app: an active mission without a vehicle shows a message and never pings /vehicles/null
        soon = page_in(b.new_context(viewport={"width": 360, "height": 740}, geolocation={"latitude": 23.78, "longitude": 90.41},
                                     permissions=["geolocation"], service_workers="block"))
        exp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 2 * 86400))
        soon.route("**/me", lambda r: r.fulfill(json={"role": "driver", "user_id": "u", "driver_id": "d", "vehicle_id": None, "token_expires_at": exp}))
        soon.route("**/missions/current", lambda r: r.fulfill(json={
            "mission_id": "00000000-0000-4000-8000-000000000000", "status": "EN_ROUTE_PICKUP", "pickup_address": "Uttara",
            "pickup_lat": 23.87, "pickup_lng": 90.4, "assigned_vehicle_id": None, "acknowledged_at": "2026-01-01T00:00:00+00:00"}))
        soon.route("**/meta/transitions", lambda r: r.fulfill(json={}))
        vreq = []; soon.on("request", lambda r: "/vehicles/" in r.url and vreq.append(r.url))
        soon.goto(base + "/driver/"); soon.click("summary"); soon.fill("#tk", "any"); soon.click("#ft button")
        soon.wait_for_function("document.getElementById('status').textContent.includes('৭ দিনের মধ্যে')", timeout=10000)
        ok(True, "driver sees the token-expiry banner within 7 days of expiry")
        ok("অ্যাম্বুলেন্স যুক্ত নেই" in soon.inner_text("#status"), "B7: mission without a vehicle shows a clear message")
        time.sleep(3)
        ok(not vreq, f"B7: no ping to /vehicles/null ({vreq})")
        shot(soon, "driver_360_token_expiry.png", "driver app 360x740, Bangla token-expiry banner and no-vehicle message")

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
        bad.goto(base + "/driver/"); bad.click("summary"); bad.fill("#tk", "bad-token"); bad.click("#ft button")
        bad.wait_for_selector("#status .err")
        ok("প্রবেশ বাতিল" in bad.inner_text("#status") and bad.is_visible("#code"), "401 shows Bangla message and the pairing form")
        shot(bad, "driver_360_401.png", "driver app 360x740, Bangla 401 message with the pairing form")
        bridge_checks(b, base, dtok, page_in)
        shot(con, "console_1280_final.png", "console 1280x800, Mirpur-10 COMPLETED and Gulshan-2 CANCELLED")
        b.close()
    bad_errs = [e for e in errors if not EXPECTED_ERR.search(e)]
    ok(not bad_errs, f"no unexpected console errors (expected 401/404/409/429 resource errors seen: {len(errors) - len(bad_errs)}; unexpected: {bad_errs})")


def bridge_checks(b, base, atok, page_in):
    """Second driver inside the Android wrapper (fake window.AmbulanceNative): QR pairing, timeout, native tracking, B8."""
    vid = api(base, atok, "/vehicles", {"operator": "RedCrescent", "registration": "DHK-E2E-2"}, "POST")["vehicle_id"]
    kid = api(base, atok, "/drivers", {"name": "Karim"}, "POST")["driver_id"]
    api(base, atok, f"/vehicles/{vid}/driver", {"driver_id": kid}, "PUT")
    code = lambda: api(base, atok, f"/drivers/{kid}/pairing-code", {}, "POST")["code"]
    mission = lambda addr: api(base, atok, "/missions", {"pickup_address": addr, "assigned_vehicle_id": vid}, "POST")["mission_id"]
    ctx = b.new_context(viewport={"width": 360, "height": 740}, geolocation={"latitude": 23.87, "longitude": 90.4},
                        permissions=["geolocation"], service_workers="block")
    ctx.add_init_script(BRIDGE)
    k = page_in(ctx)
    calls, tok = (lambda: k.evaluate("__calls")), (lambda: k.evaluate("localStorage.getItem('tok')"))
    k.goto(base + "/driver/#pair=" + code())
    k.wait_for_selector("#rf")
    ok(k.evaluate("location.hash") == "" and "কোনো মিশন নেই" in k.inner_text("#app"), "QR link #pair=CODE signs in; the code leaves the URL")
    shot(k, "driver_360_paired_qr.png", "driver app 360x740 after opening the console's QR link, no mission")

    # lie-fi: a request that never answers gives up after 10 s with a visible message, which clears on the next answer
    hung = []
    k.route("**/missions/current", lambda r: hung.append(r))  # never answered: the app's 10 s timeout must fire
    k.click("#rf")
    k.wait_for_function("document.getElementById('status').textContent.includes('নেটওয়ার্ক ধীর')", timeout=15000)
    ok(True, "a hung request times out with the Bangla 'network slow, retrying' message")
    shot(k, "driver_360_network_slow.png", "driver app 360x740, Bangla 'network slow, retrying' message after a 10 s timeout")
    for r in hung:
        r.abort()  # release the parked requests so unroute does not cancel a pending handler
    k.unroute("**/missions/current")
    k.click("#rf")
    k.wait_for_function("!document.getElementById('status').textContent.includes('নেটওয়ার্ক ধীর')")
    ok(True, "'network slow' clears once the server answers")

    mid = mission("Uttara-7")
    k.click("#rf"); k.wait_for_selector("#ack")
    ok(calls() == [["start", {"baseUrl": base, "token": tok(), "vehicleId": vid, "missionId": mid}]],
       "bridge: startTracking(baseUrl, token, vehicleId, missionId) when the mission is active")
    k.evaluate("c => { location.hash = '#pair=' + c; }", code())  # dispatcher re-pairs the phone: the token rotates
    wait_until(lambda: len(calls()) == 2 and calls()[1][1]["token"] == tok() != calls()[0][1]["token"],
               "bridge: startTracking again with the rotated token")
    k.click("#ack"); k.wait_for_selector(".badge")
    api(base, atok, f"/missions/{mid}/status", {"status": "CANCELLED"}, "PATCH")
    k.click("#rf"); k.wait_for_selector(".card.ended")
    ok("ডিসপ্যাচার মিশনটি বাতিল করেছেন" in k.inner_text("#app") and calls()[-1] == ["stop"],
       "B15: Bangla 'cancelled by dispatcher' card; bridge: stopTracking")
    shot(k, "driver_360_cancelled.png", "driver app 360x740, Bangla 'cancelled by dispatcher' card")

    # B8: a revoked token routes to re-pairing and keeps the queued pings
    k.evaluate("localStorage.setItem('driver_ping_queue', JSON.stringify([{lat: 23.87, lng: 90.4, ts: new Date().toISOString(), vehicle_id: 'v', mission_id: 'm'}]))")
    api(base, atok, f"/drivers/{kid}/token/revoke", {}, "POST")
    k.click("#rf"); k.wait_for_selector("#code")
    ok("নতুন ৬ সংখ্যার কোড" in k.inner_text("#status") and len(k.evaluate("JSON.parse(localStorage.getItem('driver_ping_queue'))")) == 1,
       "B8: a revoked token routes to the pairing form and keeps the queue")
    shot(k, "driver_360_repair.png", "driver app 360x740, Bangla 'signed out, get a new code' message on the pairing form")
    k.fill("#code", code()); k.click("#f button"); k.wait_for_selector("#rf")
    mission("Uttara-9")
    k.click("#rf"); k.wait_for_selector("#ack")
    ok(calls()[-1][0] == "start" and calls()[-1][1]["token"] == tok(), "typed code signs the revoked driver back in; tracking restarts")

    k.click("#lo"); k.click("dialog button[data-v='']")
    ok(tok() and k.is_visible("#ack"), "sign-out asks first; 'No' keeps the driver signed in")
    k.click("#lo"); k.click("dialog button[data-v='1']"); k.wait_for_selector("#code")
    ok(calls()[-1] == ["stop"] and tok() is None and k.evaluate("localStorage.getItem('driver_ping_queue')") is None,
       "confirmed sign-out stops native tracking and clears token and queue")
    ok(k.evaluate("__watches") == 0, "bridge: the web GPS watch never ran, so the server never gets double pings")
    ctx.close()


if __name__ == "__main__":
    main()

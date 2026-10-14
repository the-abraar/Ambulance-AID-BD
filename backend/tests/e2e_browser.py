"""End-to-end browser test against the REAL backend (not collected by pytest: name has no test_ prefix).

Run (from backend/):
    python3.11 -m venv .e2e && .e2e/bin/pip install -r requirements-dev.txt playwright && .e2e/bin/playwright install chromium
    .e2e/bin/python tests/e2e_browser.py [screenshot_dir]   # default: tests/shots/ (gitignored) + INDEX.txt
It creates a fresh SQLite DB in a temp dir, bootstraps an admin and a plain dispatcher, starts uvicorn on a free port and
exits non-zero on the first failed check. Part 1 drives /console alone (1280 px, browser in New York time, the Caddyfile's
CSP added to every console response, OSM tiles stubbed) and plays the driver through the API. Part 2 drives /driver
(360 px, fake geolocation) against the console; a failure after "== part 2" is in the driver app or the loop between them.
"""
import base64
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
from datetime import datetime, timedelta, timezone
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
CSP = re.search(r'Content-Security-Policy "([^"]+)"', (ROOT.parent / "Caddyfile").read_text()).group(1)  # the deployed one
TILE = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
DHAKA = timezone(timedelta(hours=6))
PAGE = 25  # console history page size (app.js PAGE)
checks = 0


def ok(cond, msg):
    global checks
    checks += 1
    if not cond:
        raise AssertionError(msg)
    print("ok:", msg)


def bootstrap(env, role, name):
    out = subprocess.run([sys.executable, "-m", "app.bootstrap", role, name], env=env, cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return re.search(r"token=(\S+)", out).group(1)


def main():
    tmp = tempfile.mkdtemp(prefix="e2e_")
    env = {**os.environ, "AMBULANCE_DB_PATH": f"{tmp}/e2e.db", "PYTHONPATH": str(ROOT)}
    dtok, ctok = bootstrap(env, "admin", "alice"), bootstrap(env, "dispatcher", "carol")
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
        run(base, dtok, ctok)
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


def call(base, method, path, tok=None, body=None):
    r = urllib.request.Request(base + path, method=method, data=None if body is None else json.dumps(body).encode(),
                               headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    with urllib.request.urlopen(r) as resp:
        return None if resp.status == 204 else json.load(resp)


def wait(page, expr, timeout=10000):
    """wait_for_function needs eval, which the console's CSP blocks; page.evaluate goes through the devtools protocol."""
    end = time.time() + timeout / 1000
    while not page.evaluate(expr):
        if time.time() > end:
            raise TimeoutError(f"timed out after {timeout} ms: {expr}")
        time.sleep(0.1)


def dhaka(ts):
    """The console's time format (app.js DHAKA), computed independently."""
    return datetime.fromisoformat(ts).astimezone(DHAKA).strftime("%Y-%m-%d %H:%M:%S")


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def run(base, dtok, ctok):
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch()

        def page_in(ctx):
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and errors.append(m.text))
            pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
            return pg

        def with_csp(route):
            resp = route.fetch()
            route.fulfill(response=resp, headers={**resp.headers, "content-security-policy": CSP})

        csp_bad = []

        def close(pg):
            csp_bad.extend(pg.evaluate("__csp")); pg.context.close()

        def console_page(tok, clock=False):
            # New York browser clock: any time shown in browser-local time instead of Dhaka time fails the checks.
            ctx = b.new_context(viewport={"width": 1280, "height": 800}, timezone_id="America/New_York")
            ctx.route(f"{base}/console/**", with_csp)
            ctx.route("https://tile.openstreetmap.org/**", lambda r: r.fulfill(body=TILE, content_type="image/png"))
            ctx.add_init_script("""window.__csp = []; window.__beeps = 0;
                addEventListener('securitypolicyviolation', e => __csp.push(e.violatedDirective + ' ' + e.blockedURI));
                (() => { const o = AudioContext.prototype.createOscillator;
                         AudioContext.prototype.createOscillator = function () { __beeps++; return o.call(this); }; })();""")
            pg = page_in(ctx)
            if clock:
                pg.clock.install()
            pg.goto(base + "/console/")
            pg.fill("#token", tok); pg.click("#login button")
            wait(pg, "document.getElementById('who').textContent.startsWith('connected')")
            return pg

        rows_js = "[...document.querySelectorAll('#missions tbody tr')]"
        has_row = lambda addr, st: f"{rows_js}.some(r=>r.textContent.includes('{addr}')&&r.cells[1].title==='{st}')"
        no_row = lambda addr: f"!{rows_js}.some(r=>r.textContent.includes('{addr}'))"

        print("== part 1: console")
        con = console_page(dtok)
        con.on("dialog", lambda d: d.accept())
        ok(con.inner_text("#who") == "connected (admin)", "bootstrap admin connects as admin")
        wait(con, "[...document.querySelectorAll('#map img.leaflet-tile')].some(i=>i.complete&&i.naturalWidth>0)")
        ok("OpenStreetMap" in con.inner_text(".leaflet-control-attribution"), "map loads tiles and shows the OSM attribution")
        ok("No patient names or phone numbers" in con.inner_text("#addr-warn"), "address field warns against patient data")

        con.fill("#newv [name=operator]", "RedCrescent"); con.fill("#newv [name=registration]", "DHK-E2E")
        con.click("#newv button")
        con.wait_for_selector("#vehicles tbody tr:has-text('DHK-E2E')")
        opts = lambda: con.eval_on_selector("#newm [name=veh]", "s=>[...s.options].filter(o=>o.value).map(o=>[o.textContent,o.disabled])")
        ok(opts() == [["DHK-E2E · no driver (no driver: pair one below)", True]], f"unpaired vehicle cannot be dispatched ({opts()})")

        def add_driver(name, phone=""):
            con.fill("#newd [name=name]", name); con.fill("#newd [name=phone]", phone); con.click("#newd button")
            con.wait_for_selector("#pair-dlg[open]")
            code = con.inner_text("#pair-code")
            ok(re.fullmatch(r"\d{6}", code) and con.inner_text("#pair-url") == f"{base}/driver/#pair={code}",
               f"new driver {name} gets a 6-digit pairing code and the app link")
            return code
        code = add_driver("Rahim", "01711-234567")
        ok(con.eval_on_selector("#pair-qr", "c=>c.width>100&&c.getContext('2d').getImageData(0,0,c.width,c.height).data.some(v=>v===0)"),
           "pairing dialog draws a QR code")
        ok(con.is_hidden("#newtok"), "no raw token shown when a driver is created")
        shot(con, "console_1280_pairing.png", "console 1280x800, pairing dialog: 6-digit code, QR of /driver/#pair=CODE, expiry in Dhaka time")
        con.click("#pair-dlg button")
        dr_tok = call(base, "POST", "/pair", body={"code": code})["token"]
        ok(api(base, dr_tok, "/me")["role"] == "driver", "the console's pairing code redeems at POST /pair")
        drow = con.locator("#drivers tbody tr:has-text('Rahim')")
        wait(con, "document.querySelector('#drivers tbody').textContent.includes('+8801711234567')")
        ok("valid until" in drow.inner_text(), "drivers list shows the phone and the token state")

        con.select_option("#pairf [name=veh]", label="DHK-E2E"); con.select_option("#pairf [name=drv]", label="Rahim")
        con.click("#pairf button")
        wait(con, "[...document.querySelectorAll('#vehicles tbody tr')].some(r=>r.cells[0].textContent==='DHK-E2E'&&r.cells[3].textContent==='Rahim')")
        ok(opts() == [["DHK-E2E · Rahim", False]], "paired vehicle is offered with its driver")
        veh_id = con.eval_on_selector("#newm [name=veh]", "s=>s.options[1].value")

        def new_mission(addr, dx=40, dy=-30):
            con.fill("#newm [name=addr]", addr)
            box = con.locator("#map").bounding_box()
            con.mouse.click(box["x"] + box["width"] / 2 + dx, box["y"] + box["height"] / 2 + dy)
            wait(con, r"/^\d+\.\d+, \d+\.\d+$/.test(document.getElementById('pickup').textContent)")
            picked = con.inner_text("#pickup")
            con.select_option("#newm [name=veh]", label="DHK-E2E · Rahim")
            con.click("#newm button:has-text('Dispatch')")
            con.wait_for_selector(f"#missions tbody tr:has-text('{addr}')")
            m = api(base, dtok, "/missions?active=true")[0]
            ok(m["pickup_address"] == addr and picked == f"{m['pickup_lat']}, {m['pickup_lng']}",
               f"map click placed the pickup of {addr} ({picked})")
            return m

        m1 = new_mission("Mohakhali-1")
        row = con.locator("#missions tbody tr:has-text('Mohakhali-1')")
        cell = lambda i: row.locator("td").nth(i).inner_text().strip()
        ok(row.locator("td").nth(1).get_attribute("title") == "DISPATCHED", "console shows the new mission DISPATCHED")
        btns = row.locator("button").all_inner_texts()
        ok(btns == ["On behalf: En route pickup", "Audit", "Cancel…"], f"actions: on-behalf move, audit, cancel last ({btns})")
        ok(row.locator("button.danger").inner_text() == "Cancel…", "cancel is the one danger-styled button")
        ok(cell(5) == dhaka(m1["created_at"]), f"dispatch time in Dhaka time, browser in New York ({cell(5)})")
        ok(re.fullmatch(r"\d+:\d\d", cell(6)) and cell(7) == "waiting", f"elapsed and acknowledgement columns ({cell(6)}, {cell(7)})")
        ok(opts() == [["DHK-E2E · Rahim (busy)", True]], "busy vehicle cannot be dispatched twice")

        # the driver (played through the API) acknowledges and sends one fix with accuracy
        ack = call(base, "POST", f"/missions/{m1['mission_id']}/ack", dr_tok)
        call(base, "POST", f"/vehicles/{veh_id}/pings", dr_tok, {"lat": 23.78, "lng": 90.41, "ts": utcnow(), "accuracy": 35})
        con.wait_for_selector("#map path.veh-busy", timeout=12000)
        ok(con.locator("#map path.acc").count() == 1, "map draws the accuracy circle")
        vrow = con.inner_text("#vehicles tbody tr:has-text('DHK-E2E')")
        ok("busy" in vrow and "23.78000, 90.41000 ±35 m at " in vrow, f"vehicle table reads last_position ({vrow})")
        wait(con, f"{rows_js}.some(r=>r.cells[7].textContent==='{dhaka(ack['acknowledged_at'])}')")
        ok(True, "acknowledged time shown in Dhaka time")
        shot(con, "console_1280_map.png", "console 1280x800, map with the busy vehicle and its accuracy circle, mission acknowledged")

        # on-behalf move: reason required, event time in Dhaka time
        row.locator("button:has-text('On behalf')").click()
        ok(con.is_visible("#behalf-dlg") and "Mohakhali-1" in con.inner_text("#behalf-what"), "on-behalf dialog names the mission")
        con.click("#behalf-dlg button[value=go]")
        ok(con.is_visible("#behalf-dlg"), "on-behalf move refused without a reason")
        at = datetime.fromisoformat(m1["created_at"]) + timedelta(seconds=1)
        at += timedelta(seconds=at.second == 0)  # :00 would be normalised away and break fill()
        con.fill("#behalf-dlg [name=reason]", "driver phone dead")
        con.fill("#behalf-dlg [name=at]", at.astimezone(DHAKA).strftime("%Y-%m-%dT%H:%M:%S"))
        con.click("#behalf-dlg button[value=go]")
        wait(con, has_row("Mohakhali-1", "EN_ROUTE_PICKUP"))
        last = api(base, dtok, f"/missions/{m1['mission_id']}/audit")[-1]
        ok(last["on_behalf_of"] == m1["assigned_driver_id"] and last["reason"] == "driver phone dead"
           and dhaka(last["event_time"]) == at.astimezone(DHAKA).strftime("%Y-%m-%d %H:%M:%S"),
           "on-behalf move sent reason and Dhaka event time; audit names the driver")
        row.locator("button:has-text('Audit')").click()
        con.wait_for_selector("#audit li:has-text('reason')")
        audit = con.inner_text("#audit")
        ok(f"{dhaka(last['ts'])} · Dispatched -> En route pickup · by you · for driver Rahim · happened {dhaka(last['event_time'])}"
           " · reason: driver phone dead" in audit and not re.search(r"\d{4}-\d\d-\d\dT", audit),
           f"audit drawer: Dhaka times, no raw UTC ({audit!r})")
        shot(con, "console_1280_audit.png", "console 1280x800, audit drawer with an on-behalf move, reason and event time in Dhaka time")
        con.click("#close")

        # B5 cancel: address shown, reason required, Keep is the default
        row.locator("button:has-text('Cancel')").click()
        ok(con.inner_text("#cancel-addr") == "Mohakhali-1", "cancel dialog shows the mission's address")
        con.click("#cancel-dlg button[value=cancel]")
        ok(con.is_visible("#cancel-dlg"), "cancel refused without a reason")
        shot(con, "console_1280_cancel.png", "console 1280x800, cancel dialog: address, required reason, separated red cancel button")
        con.press("#cancel-dlg [name=reason]", "Enter")
        ok(not con.is_visible("#cancel-dlg") and api(base, dtok, f"/missions/{m1['mission_id']}")["status"] == "EN_ROUTE_PICKUP",
           "Enter in the dialog keeps the mission")
        row.locator("button:has-text('Cancel')").click()
        con.fill("#cancel-dlg [name=reason]", "caller found a taxi"); con.click("#cancel-dlg button[value=cancel]")
        wait(con, no_row("Mohakhali-1"))
        ok(api(base, dtok, f"/missions/{m1['mission_id']}/audit")[-1]["reason"] == "caller found a taxi",
           "cancelled mission leaves the active view; reason in the audit")

        # 409: another dispatcher cancels while this one has the dialog open
        m2 = new_mission("Gulshan-409")
        con.locator("#missions tbody tr:has-text('Gulshan-409') button:has-text('Cancel')").click()
        con.fill("#cancel-dlg [name=reason]", "duplicate call")
        call(base, "PATCH", f"/missions/{m2['mission_id']}/status", ctok, {"status": "CANCELLED", "reason": "carol got there first"})
        con.click("#cancel-dlg button[value=cancel]")
        con.wait_for_selector(".toast:has-text('409')")
        ok("Someone changed it first" in con.inner_text(".toast:has-text('409')"), "console explains a 409")

        # history: paged, newest first; the active view lists every live mission newest first (B1)
        for i in range(PAGE - 1):
            mid = call(base, "POST", "/missions", ctok, {"pickup_address": f"Hist-{i:02d}"})["mission_id"]
            call(base, "PATCH", f"/missions/{mid}/status", ctok, {"status": "CANCELLED", "reason": "e2e history"})
        live = [call(base, "POST", "/missions", ctok, {"pickup_address": f"Live-{i}"})["mission_id"] for i in range(2)]
        ids = lambda: con.eval_on_selector_all("#missions tbody code", "cs=>cs.map(c=>c.title)")
        wait(con, f"{rows_js}.length===2")
        ok(ids() == live[::-1], "active view: every live mission, newest first")
        con.click("#tab-history")
        newest = [m["mission_id"] for m in api(base, dtok, f"/missions?limit={PAGE}")]
        wait(con, f"{rows_js}.length==={PAGE}")
        ok(ids() == newest and not con.is_disabled("#older") and con.is_disabled("#newer"), "history page 1: newest first, Older enabled")
        con.click("#older")
        rest = [m["mission_id"] for m in api(base, dtok, f"/missions?limit={PAGE}&offset={PAGE}")]
        wait(con, f"{rows_js}.length==={len(rest)}")
        ok(ids() == rest and con.is_disabled("#older") and con.inner_text("#page") == f"{PAGE + 1}-{PAGE + len(rest)}", "history page 2")
        shot(con, "console_1280_history.png", "console 1280x800, history view page 2 with pager")
        con.click("#tab-active")
        for mid in live:
            call(base, "PATCH", f"/missions/{mid}/status", ctok, {"status": "CANCELLED", "reason": "e2e"})

        # 2-minute acknowledgement alarm: browser clock moved forward, sound armed by a click
        al = console_page(dtok, clock=True)
        late = call(base, "POST", "/missions", dtok, {"pickup_address": "Uttara-ack"})["mission_id"]
        al.click("#sound")
        ok(al.evaluate("__beeps") == 1 and al.get_attribute("#sound", "aria-pressed") == "true", "alarm sound armed by a click (test beep)")
        wait(al, f"{rows_js}.some(r=>r.textContent.includes('Uttara-ack'))")
        ok(al.is_hidden("#alarm"), "no alarm before 2 minutes")
        al.clock.fast_forward("02:05")
        al.wait_for_selector("#missions tbody tr.late:has-text('NOT ACKNOWLEDGED')")
        ok("Uttara-ack" in al.inner_text("#alarm") and al.evaluate("__beeps") > 1, "not acknowledged in 2 minutes: red row, banner and beep")
        shot(al, "console_1280_alarm.png", "console 1280x800, alarm banner and red row for a mission not acknowledged in 2 minutes")
        call(base, "PATCH", f"/missions/{late}/status", dtok, {"status": "CANCELLED", "reason": "e2e"})
        close(al)

        # plain dispatcher: no admin actions
        dis = console_page(ctok)
        dis.wait_for_selector("#drivers tbody tr:has-text('Rahim')")
        seen = [dis.inner_text("#who"), dis.is_hidden("#newd"), dis.locator("#drivers button").count(), dis.is_visible("#pairf")]
        ok(seen == ["connected (dispatcher)", True, 0, True], f"plain dispatcher: no driver create, token or pairing-code buttons; can pair ({seen})")
        shot(dis, "console_1280_dispatcher.png", "console 1280x800, plain dispatcher: drivers list without admin actions")
        close(dis)

        # map states and token-expiry list from fixtures shaped like the real responses
        rv, rd = api(base, dtok, "/vehicles")[0], api(base, dtok, "/drivers")[0]
        soon = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        fx_d = [{**rd, "driver_id": "d-karim", "name": "Karim", "expires_at": soon},
                {**rd, "driver_id": "d-salam", "name": "Salam", "revoked": True}]
        pos = lambda **k: {**rv["last_position"], **k}
        fx_v = [{**rv, "vehicle_id": "v-free", "registration": "V-FREE", "busy": False, "driver_id": "d-karim", "last_position": pos(lat=23.8, lng=90.4, accuracy=400, stale=False)},
                {**rv, "vehicle_id": "v-busy", "registration": "V-BUSY", "busy": True, "driver_id": None, "last_position": pos(lat=23.75, lng=90.39, accuracy=None, stale=False)},
                {**rv, "vehicle_id": "v-stale", "registration": "V-STALE", "busy": False, "driver_id": None, "last_position": pos(lat=23.77, lng=90.43, accuracy=None, stale=True)},
                {**rv, "vehicle_id": "v-rev", "registration": "V-REV", "busy": False, "driver_id": "d-salam", "last_position": None}]
        fx = console_page(dtok)
        fx.route("**/vehicles", lambda r: r.fulfill(json=fx_v)); fx.route("**/drivers", lambda r: r.fulfill(json=fx_d))
        fx.wait_for_selector("#map path.veh-stale", timeout=12000)
        ok([fx.locator(f"#map path.veh-{k}").count() for k in ("free", "busy", "stale")] == [1, 1, 1]
           and fx.locator("#map path.acc").count() == 1, "map: free, busy and stale vehicles, one accuracy circle")
        fopts = fx.eval_on_selector("#newm [name=veh]", "s=>[...s.options].filter(o=>o.value).map(o=>o.textContent+(o.disabled?' X':''))")
        ok(fopts == ["V-FREE · Karim", "V-BUSY · no driver (busy) X", "V-STALE · no driver (no driver: pair one below) X",
                     "V-REV · Salam (driver revoked) X"], f"only free vehicles with a valid driver can be dispatched ({fopts})")
        ok("Karim" in fx.inner_text("#expiring") and "Salam" not in fx.inner_text("#expiring")
           and "revoked" in fx.inner_text("#drivers tbody tr:has-text('Salam')"), "expires-within-7-days list; revoked driver shown")
        fx.click("#map path.veh-free")
        ok(fx.eval_on_selector("#newm [name=veh]", "s=>s.value") == "v-free" and fx.inner_text("#pickup") == "not set, click the map",
           "clicking a free vehicle on the map selects it (and does not move the pickup)")
        shot(fx, "console_1280_fleet.png", "console 1280x800, fixture fleet: free (green, accuracy circle), busy (red), stale (grey dashed)")
        close(fx)

        # raw token only behind "Show token"; revoke
        add_driver("Tarek"); con.click("#pair-dlg button")
        trow = con.locator("#drivers tbody tr:has-text('Tarek')")
        trow.locator("button:has-text('Show token')").click()
        wait(con, "document.getElementById('newtok').textContent.includes('New token for Tarek')")
        t_tok = re.search(r":\s*(\S+)$", con.inner_text("#newtok")).group(1)
        ok(api(base, t_tok, "/me")["role"] == "driver", "Show token: rotates and shows a working raw token")
        trow.locator("button:has-text('Revoke')").click()
        con.wait_for_selector(".toast:has-text('Token revoked for Tarek')")
        try:
            api(base, t_tok, "/me"); dead = False
        except urllib.error.HTTPError as e:
            dead = e.code == 401
        wait(con, "document.querySelector('#drivers tbody').textContent.includes('revoked')")
        ok(dead, "revoke: the token stops working and the list says revoked")

        for w, hgt in ((375, 812), (768, 1024)):
            con.set_viewport_size({"width": w, "height": hgt}); con.evaluate("scrollTo(0, 0)")
            ok(con.evaluate("document.documentElement.scrollWidth") <= w, f"no sideways page scroll at {w} px")
            shot(con, f"console_{w}_top.png", f"console {w}x{hgt}, top of the page: map and new-mission form")
        con.set_viewport_size({"width": 1280, "height": 800})
        csp_bad.extend(con.evaluate("__csp"))
        ok(not csp_bad, f"no CSP violations on any console page ({csp_bad})")
        print(f"== part 1 passed ({checks} checks)")

        print("== part 2: driver app with the console")
        m = new_mission("Mirpur-10")
        last_ts = api(base, dtok, f"/vehicles/{veh_id}/position")["ts"]  # part 1's fix; the app must send a newer one
        dctx = b.new_context(viewport={"width": 360, "height": 740}, geolocation={"latitude": 23.779, "longitude": 90.409},
                             permissions=["geolocation"], service_workers="block")
        drv = page_in(dctx)
        drv.goto(base + "/driver/")
        shot(drv, "driver_360_login.png", "driver app 360x740, token login form")
        drv.fill("#tk", dr_tok); drv.click("#f button")
        drv.wait_for_selector(".badge")
        href = drv.get_attribute("#nav", "href")
        ok(href and f"destination={m['pickup_lat']},{m['pickup_lng']}" in href, f"driver navigate link built from numbers ({href})")

        shot(drv, "driver_360_dispatched.png", "driver app 360x740, mission DISPATCHED with next-step button and navigate link")
        for i, st in enumerate(PATH):
            if st != "COMPLETED":  # terminal: driver has no current mission, so no badge
                ok(BN[st] in drv.inner_text(".badge"), f"driver badge shows Bangla label for {st}")
                wait(con, has_row("Mirpur-10", st), timeout=12000)
            else:  # the active view drops ended missions
                wait(con, no_row("Mirpur-10"), timeout=12000)
            ok(True, f"console reflects {st}")
            if st != "COMPLETED":
                # app throttles pings to 1/5 s; headless fires one GPS event per set_geolocation, none if the position is unchanged
                time.sleep(5.2)
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
        con.click("#tab-history")
        wait(con, has_row("Mirpur-10", "COMPLETED"))
        shot(drv, "driver_360_done.png", "driver app 360x740, no active mission after COMPLETED")
        shot(con, "console_1280_done.png", "console 1280x800, history view, Mirpur-10 COMPLETED, Audit only")
        ok(con.locator("#missions tbody tr:has-text('Mirpur-10') button").all_inner_texts() == ["Audit"],
           "console offers no actions on terminal mission")
        con.click("#tab-active")
        ok("কোনো মিশন নেই" in drv.inner_text("#app"), "driver sees no-mission after terminal state")
        ok(api(base, dtok, "/missions?status=COMPLETED")[0]["status"] == "COMPLETED", "backend confirms COMPLETED")

        # 409: dispatcher cancels (with a reason) while the driver has the confirm dialog open; also English toggle
        new_mission("Gulshan-2")
        drv.click("#rf"); drv.wait_for_selector(".badge")
        drv.click("#lang")
        ok("Dispatched" in drv.inner_text(".badge") and drv.inner_text("#title") == "Driver", "English toggle labels")
        shot(drv, "driver_360_english.png", "driver app 360x740, English toggle on a new DISPATCHED mission")
        drv.click("button.big[data-s=EN_ROUTE_PICKUP]")
        ok(drv.is_visible("dialog"), "confirm dialog open")
        con.locator("#missions tbody tr:has-text('Gulshan-2') button:has-text('Cancel')").click()
        con.fill("#cancel-dlg [name=reason]", "caller cancelled"); con.click("#cancel-dlg button[value=cancel]")
        wait(con, no_row("Gulshan-2"), timeout=12000)
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
        dctx.set_geolocation({"latitude": 23.79, "longitude": 90.42})  # ~1 km on: the server refuses impossible jumps
        end = time.time() + 15
        while time.time() < end and not queue():
            time.sleep(0.3)
        ok(queue() and queue()[0]["lat"] == 23.79, "offline ping is queued in localStorage")
        shot(drv, "driver_360_offline.png", "driver app 360x740, offline banner with a queued ping")
        dctx.set_offline(False)
        end = time.time() + 20
        while time.time() < end and queue():
            time.sleep(0.5)
        ok(not queue(), "queue drained after going back online")
        ok(abs(api(base, dtok, f"/vehicles/{veh_id}/position")["lat"] - 23.79) < 1e-6, "replayed ping reached the server")

        # 429: two pings in a row from the driver's own token hit the 1 s per-vehicle limit
        codes = drv.evaluate("""async ([vid, tok]) => {
            const send = () => fetch(`/vehicles/${vid}/pings`, {method: 'POST', body: JSON.stringify({lat: 23.79, lng: 90.42, ts: new Date().toISOString()}),
              headers: {Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json'}}).then(r => r.status);
            return [await send(), await send(), await send()]; }""", [veh_id, dr_tok])
        ok(429 in codes, f"server answers 429 on rapid pings (got {codes})")

        # driver app's own 429 message: the server (stubbed here) refuses a ping
        drv.route("**/pings", lambda r: r.fulfill(status=429, body="{}"))
        time.sleep(5.2)  # past the app's 5 s ping throttle
        dctx.set_geolocation({"latitude": 23.791, "longitude": 90.421})
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

        # 401: bad token
        bctx = b.new_context(viewport={"width": 360, "height": 740})
        bad = page_in(bctx)
        bad.goto(base + "/driver/"); bad.fill("#tk", "bad-token"); bad.click("#f button")
        bad.wait_for_selector("#status .err")
        ok("টোকেন বাতিল" in bad.inner_text("#status") and bad.is_visible("#tk"), "401 shows Bangla message and login form")
        shot(bad, "driver_360_401.png", "driver app 360x740, Bangla 401 message with login form")
        shot(con, "console_1280_final.png", "console 1280x800, active view with Banani-1 and the busy vehicle on the map")
        b.close()
    bad_errs = [e for e in errors if not EXPECTED_ERR.search(e)]
    ok(not bad_errs, f"no unexpected console errors (expected 401/404/409/429 resource errors seen: {len(errors) - len(bad_errs)}; unexpected: {bad_errs})")


if __name__ == "__main__":
    main()

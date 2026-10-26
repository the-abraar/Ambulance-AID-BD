"""End-to-end browser test against the REAL backend (not collected by pytest: name has no test_ prefix).

Run (from backend/):
    python3.11 -m venv .e2e && .e2e/bin/pip install -r requirements-dev.txt playwright && .e2e/bin/playwright install chromium
    .e2e/bin/python tests/e2e_browser.py [screenshot_dir]   # default: tests/shots/ (gitignored) + INDEX.txt
It creates a fresh SQLite DB in a temp dir, bootstraps an admin and a plain dispatcher, starts uvicorn on a free port and
exits non-zero on the first failed check. Part 1 drives /console alone (1280 px, browser in New York time, the Caddyfile's
CSP added to every console response, OSM tiles stubbed) and plays the driver through the API. Part 2 drives /driver
(360 px, fake geolocation, stubbed alerts and wake lock) against the console, then a second driver in a fake Android
wrapper (window.AmbulanceNative); a failure after "== part 2" is in the driver app or the loop between them.
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
# The Android wrapper's contract: window.AmbulanceNative with startTracking(json) -> bool, stopTracking(), isTracking(),
# and an `ambulance-native-stopped` event {status, reason} when its service stops itself (401, 403, 404).
BRIDGE = """
window.__calls = []; window.__watches = 0; window.__nativeFail = false;
const _w = navigator.geolocation.watchPosition.bind(navigator.geolocation);
navigator.geolocation.watchPosition = (...a) => { __watches++; return _w(...a); };
window.AmbulanceNative = {on: false, startTracking(j) { __calls.push(['start', JSON.parse(j)]); return (this.on = !__nativeFail); },
  stopTracking() { __calls.push(['stop']); this.on = false; }, isTracking() { return this.on; }};
window.__nativeStop = status => { AmbulanceNative.on = false;
  dispatchEvent(new CustomEvent('ambulance-native-stopped', {detail: {status, reason: 'e2e'}})); };
"""
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


def wait_until(fn, what, secs=15):
    end = time.time() + secs
    while time.time() < end and not fn():
        time.sleep(0.3)
    ok(fn(), what)


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
        ok("Nominatim" in con.inner_text("#search-warn"), "landmark search says its text goes to Nominatim")
        hits = [{"lat": "23.7461", "lon": "90.3742", "display_name": "Dhanmondi 27, Dhaka"},
                {"lat": "23.7104", "lon": "90.4074", "display_name": "Dhanmondi, Old Dhaka"}]
        con.route("https://nominatim.openstreetmap.org/**",
                  lambda r: r.fulfill(json=hits, headers={"Access-Control-Allow-Origin": "*"}))
        con.fill("#map-search-input", "Dhanmondi"); con.press("#map-search-input", "Enter")
        con.wait_for_selector("#map-search-results button")
        ok(con.eval_on_selector_all("#map-search-results button", "b=>b.map(x=>x.textContent)") == [x["display_name"] for x in hits]
           and con.evaluate("document.activeElement.textContent") == hits[0]["display_name"]
           and con.inner_text("#pickup") == "not set, click the map",
           "landmark search lists every match, focuses the first and leaves the pickup unset")
        con.keyboard.press("Tab"); con.keyboard.press("Enter")
        wait(con, "document.getElementById('map-search-results').hidden")
        ok(con.inner_text("#pickup") == "23.7104, 90.4074" and con.evaluate("document.activeElement.id") == "map-search-input",
           "picking the second match by keyboard sets the pickup there and returns focus to the search box")
        ok(con.input_value("#newm [name=addr]") == "Dhanmondi, Old Dhaka", "an empty address field is filled from the pick")
        con.route("https://nominatim.openstreetmap.org/**", lambda r: r.fulfill(status=429, body="slow down"))
        con.fill("#map-search-input", "Gulshan"); con.press("#map-search-input", "Enter")
        wait(con, "document.getElementById('toasts').textContent.includes('Search unavailable')")
        con.evaluate("map.setView(DHAKA_CENTRE, 12)")  # back to the start view: later checks need the vehicles on screen

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

        # N6: back-fill a paper-log mission onto the busy vehicle: written already over, the driver is not alerted
        t0 = (datetime.now(DHAKA) - timedelta(hours=2)).replace(second=7, microsecond=0)
        local = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S")
        con.click("#newm summary")
        con.fill("#newm [name=addr]", "Paper-log-1")
        con.fill("#newm [name=dispatched]", local(t0))
        ok(opts() == [["DHK-E2E · Rahim (busy)", False]], "back-fill: the busy vehicle can be picked")
        con.select_option("#newm [name=veh]", label="DHK-E2E · Rahim (busy)")
        con.fill("#newm [name=bf_AT_SCENE]", local(t0 + timedelta(minutes=12)))
        con.fill("#newm [name=bf_end_at]", local(t0 + timedelta(minutes=50)))
        shot(con, "console_1280_backfill.png", "console 1280x800, back-fill form: a paper-log mission on the busy vehicle, step times")
        con.click("#newm button:has-text('Dispatch')")
        wait(con, "!document.querySelector('#newm [name=dispatched]').value")
        bf = next(x for x in api(base, dtok, "/missions") if x["pickup_address"] == "Paper-log-1")
        ok(bf["status"] == "COMPLETED" and dhaka(bf["created_at"]) == t0.strftime("%Y-%m-%d %H:%M:%S")
           and bf["en_route_pickup_at"] is None and dhaka(bf["at_scene_at"]) == (t0 + timedelta(minutes=12)).strftime("%Y-%m-%d %H:%M:%S")
           and dhaka(bf["completed_at"]) == (t0 + timedelta(minutes=50)).strftime("%Y-%m-%d %H:%M:%S"),
           "back-fill recorded COMPLETED with the paper log's Dhaka times; an empty step stays unknown")
        ok(api(base, dr_tok, "/missions/current")["mission_id"] == m1["mission_id"] and opts() == [["DHK-E2E · Rahim (busy)", True]],
           "back-fill: the driver still sees only his live mission; the form resets and the vehicle is busy again")

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

        # response-time report: the date range filters the table and the CSV
        counts = "[...document.querySelectorAll('#reports-table tbody tr')].map(r=>+r.cells[1].textContent)"
        con.click("#btn-reports"); con.wait_for_selector("#reports-dlg[open]")
        ok(sum(con.evaluate(counts)) > 0, "report dialog: all missions when no dates are set")
        con.fill("#report-to", "2000-01-01")
        wait(con, f"{counts}.every(c=>c===0)")
        with con.expect_request("**/reports/response-times?*format=csv*") as req:
            con.click("#btn-export-csv")
        ok("end_date=2000-01-01" in req.value.url, "report date range filters the table and the CSV export")
        con.fill("#report-to", ""); con.click("#reports-dlg button[value=close]")

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
        dctx.add_init_script(ALERT_STUBS)
        drv = page_in(dctx)
        drv.goto(base + "/driver/")
        shot(drv, "driver_360_login.png", "driver app 360x740, 6-digit pairing code form")
        drv.fill("#code", "000000"); drv.click("#f button")
        drv.wait_for_function("document.getElementById('status').textContent.includes('কোডটি ভুল')")
        ok(drv.is_visible("#code"), "wrong pairing code: Bangla message, still on the code form")
        rahim = next(d["driver_id"] for d in api(base, dtok, "/drivers") if d["name"] == "Rahim")
        drv.fill("#code", call(base, "POST", f"/drivers/{rahim}/pairing-code", dtok)["code"]); drv.click("#f button")
        drv.wait_for_selector(".card.new")
        drv_tok = drv.evaluate("localStorage.getItem('tok')")  # the new code rotated Rahim's token: dr_tok is dead
        ok(len(drv_tok or "") > 20, "6-digit code signs in; token kept in localStorage")
        drv.wait_for_function("__al.osc > 0 && __al.vib > 0 && document.title.includes('নতুন মিশন')", timeout=8000)
        ok(not drv.is_visible("button.big[data-s]"), "new mission alert: siren, vibration, flashing title; steps wait for Accept")
        drv.click("#al")
        drv.wait_for_function("__al.notes.length === 1 && __al.notes[0].includes('Mirpur-10')", timeout=5000)
        ok(True, "alerts button asks notification permission on a tap; one notification carries the address")
        href = drv.get_attribute("#nav", "href")
        ok(href and f"destination={m['pickup_lat']},{m['pickup_lng']}" in href, f"driver navigate link built from numbers ({href})")
        shot(drv, "driver_360_new_mission.png", "driver app 360x740, flashing NEW MISSION card with Navigate and Accept")
        drv.click("#ack"); drv.wait_for_selector(".badge")
        ok(api(base, dtok, f"/missions/{m['mission_id']}")["acknowledged_at"], "Accept calls /ack: acknowledged_at is set")
        osc = drv.evaluate("__al.osc"); time.sleep(3.5)
        ok(drv.evaluate("__al.osc") == osc and drv.title() == "Driver", "alert stops after Accept")
        ok(drv.evaluate("__al.wake") == 1, "screen wake lock held during the mission")

        shot(drv, "driver_360_dispatched.png", "driver app 360x740, mission DISPATCHED with next-step button and navigate link")
        for i, st in enumerate(PATH):
            if st != "COMPLETED":  # terminal: the "mission completed" card has no badge
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
        shot(drv, "driver_360_done.png", "driver app 360x740, 'mission completed' card after COMPLETED")
        shot(con, "console_1280_done.png", "console 1280x800, history view, Mirpur-10 COMPLETED, Audit only")
        ok(con.locator("#missions tbody tr:has-text('Mirpur-10') button").all_inner_texts() == ["Audit"],
           "console offers no actions on terminal mission")
        con.click("#tab-active")
        ok("মিশন সম্পন্ন" in drv.inner_text("#app"), "driver sees 'mission completed' after the terminal state (B15)")
        ok(drv.evaluate("__al.wake") == 0, "wake lock released after the mission")
        again = page_in(dctx); again.goto(base + "/driver/"); again.wait_for_selector(".card.ended")
        ok(True, "a new tab (installed app reopened) is still signed in: token in localStorage"); again.close()
        ok(api(base, dtok, "/missions?status=COMPLETED")[0]["status"] == "COMPLETED", "backend confirms COMPLETED")

        # 409: dispatcher cancels (with a reason) while the driver has the confirm dialog open; also English toggle
        new_mission("Gulshan-2")
        drv.click("#rf"); drv.wait_for_selector("#ack"); drv.click("#ack"); drv.wait_for_selector(".badge")
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
        drv.wait_for_selector(".card.ended")
        ok("Cancelled by dispatcher" in drv.inner_text("#app"), "driver sees 'Cancelled by dispatcher', not a blank screen (B15)")
        ok(api(base, dtok, "/missions?status=CANCELLED")[0]["status"] == "CANCELLED", "mission stays CANCELLED")

        # denied GPS: the same driver in a browser without location permission, mission active again
        banani = new_mission("Banani-1")["mission_id"]
        den = page_in(b.new_context(viewport={"width": 360, "height": 740}, service_workers="block"))
        den.goto(base + "/driver/"); den.click("summary"); den.fill("#tk", drv_tok); den.click("#ft button")  # paste-token fallback
        den.wait_for_selector("#status .err")
        ok("জিপিএস অনুমতি নেই" in den.inner_text("#status"), "denied GPS shows the Bangla permission message")
        shot(den, "driver_360_gps_denied.png", "driver app 360x740, Bangla GPS-denied message on an active mission")

        # offline replay: pings taken offline are queued in localStorage, then sent once back online
        drv.click("#rf"); drv.wait_for_selector("#ack"); drv.click("#ack"); drv.wait_for_selector(".badge")
        queue = lambda: drv.evaluate("JSON.parse(localStorage.getItem('driver_ping_queue')||'[]')")
        # B9: entries queued for another mission or vehicle are dropped on replay, never sent
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

        # 401: bad token
        bctx = b.new_context(viewport={"width": 360, "height": 740})
        bad = page_in(bctx)
        bad.goto(base + "/driver/"); bad.click("summary"); bad.fill("#tk", "bad-token"); bad.click("#ft button")
        bad.wait_for_selector("#status .err")
        ok("প্রবেশ বাতিল" in bad.inner_text("#status") and bad.is_visible("#code"), "401 shows Bangla message and the pairing form")
        shot(bad, "driver_360_401.png", "driver app 360x740, Bangla 401 message with the pairing form")
        bridge_checks(b, base, dtok, page_in)
        shot(con, "console_1280_final.png", "console 1280x800, active view with Banani-1 and the busy vehicle on the map")
        b.close()
    bad_errs = [e for e in errors if not EXPECTED_ERR.search(e)]
    ok(not bad_errs, f"no unexpected console errors (expected 401/404/409/429 resource errors seen: {len(errors) - len(bad_errs)}; unexpected: {bad_errs})")


def bridge_checks(b, base, atok, page_in):
    """Second driver inside the Android wrapper (fake window.AmbulanceNative): QR pairing, timeout, native tracking, B8."""
    vid = call(base, "POST", "/vehicles", atok, {"operator": "RedCrescent", "registration": "DHK-E2E-2"})["vehicle_id"]
    kid = call(base, "POST", "/drivers", atok, {"name": "Karim"})["driver_id"]
    call(base, "PUT", f"/vehicles/{vid}/driver", atok, {"driver_id": kid})
    code = lambda: call(base, "POST", f"/drivers/{kid}/pairing-code", atok)["code"]
    mission = lambda addr: call(base, "POST", "/missions", atok, {"pickup_address": addr, "assigned_vehicle_id": vid})["mission_id"]
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
    ok(calls() == [["start", {"baseUrl": base, "token": tok(), "vehicleId": vid, "missionId": mid, "shift": False}]],
       "bridge: startTracking(baseUrl, token, vehicleId, missionId) when the mission is active")
    k.evaluate("c => { location.hash = '#pair=' + c; }", code())  # dispatcher re-pairs the phone: the token rotates
    wait_until(lambda: len(calls()) == 2 and calls()[1][1]["token"] == tok() != calls()[0][1]["token"],
               "bridge: startTracking again with the rotated token")
    k.click("#ack"); k.wait_for_selector(".badge")
    call(base, "PATCH", f"/missions/{mid}/status", atok, {"status": "CANCELLED", "reason": "e2e"})
    k.click("#rf"); k.wait_for_selector(".card.ended")
    ok("ডিসপ্যাচার মিশনটি বাতিল করেছেন" in k.inner_text("#app") and calls()[-1] == ["stop"],
       "B15: Bangla 'cancelled by dispatcher' card; bridge: stopTracking")
    shot(k, "driver_360_cancelled.png", "driver app 360x740, Bangla 'cancelled by dispatcher' card")

    # startTracking answers false (e.g. it refused the baseUrl): the web GPS path pings instead, until native works again
    def web_pinged():
        try:
            return api(base, atok, f"/vehicles/{vid}/position")["lat"] == 23.87
        except urllib.error.HTTPError:
            return False
    k.evaluate("__nativeFail = true"); m8 = mission("Uttara-8")
    k.click("#rf"); k.wait_for_selector("#ack")
    wait_until(lambda: k.evaluate("__watches") == 1 and web_pinged(), "bridge: startTracking false falls back to the web GPS watch, which pings")
    k.evaluate("__nativeFail = false"); k.click("#rf")
    wait_until(lambda: k.evaluate("watchId === null && AmbulanceNative.on"), "bridge: once startTracking succeeds the web watch stops")
    # the wrapper's service stops itself because the mission ended (403/404): its event makes the app reload
    call(base, "PATCH", f"/missions/{m8}/status", atok, {"status": "CANCELLED", "reason": "e2e"})
    k.evaluate("__nativeStop(404)"); k.wait_for_selector(".card.ended")
    ok("ডিসপ্যাচার মিশনটি বাতিল করেছেন" in k.inner_text("#app"), "ambulance-native-stopped 404: the app reloads and shows the cancelled mission")

    # B8: the token is revoked mid-mission; the service gets 401 and stops itself; re-pairing keeps the queued pings
    m9 = mission("Uttara-9")
    k.click("#rf"); k.wait_for_selector("#ack")
    k.evaluate("localStorage.setItem('driver_ping_queue', JSON.stringify([{lat: 23.87, lng: 90.4, ts: new Date().toISOString(), vehicle_id: 'v', mission_id: 'm'}]))")
    call(base, "POST", f"/drivers/{kid}/token/revoke", atok)
    k.evaluate("__nativeStop(401)"); k.wait_for_selector("#code")
    ok("নতুন ৬ সংখ্যার কোড" in k.inner_text("#status") and len(k.evaluate("JSON.parse(localStorage.getItem('driver_ping_queue'))")) == 1,
       "B8: ambulance-native-stopped 401 routes to the pairing form and keeps the queue")
    shot(k, "driver_360_repair.png", "driver app 360x740, Bangla 'signed out, get a new code' message on the pairing form")
    k.fill("#code", code()); k.click("#f button"); k.wait_for_selector("#ack")
    ok(calls()[-1][0] == "start" and calls()[-1][1]["token"] == tok() and calls()[-1][1]["missionId"] == m9,
       "typed code signs the revoked driver back in; native tracking restarts with the new token")
    k.reload(); k.wait_for_selector("#ack")  # WebView restarted, service not running
    ok(calls() == [["start", {"baseUrl": base, "token": tok(), "vehicleId": vid, "missionId": m9, "shift": False}]],
       "after a reload with an active mission and native tracking off, startTracking on load")

    k.click("#lo"); k.click("dialog button[data-v='']")
    ok(tok() and k.is_visible("#ack"), "sign-out asks first; 'No' keeps the driver signed in")
    k.click("#lo"); k.click("dialog button[data-v='1']"); k.wait_for_selector("#code")
    ok(calls()[-1] == ["stop"] and tok() is None and k.evaluate("localStorage.getItem('driver_ping_queue')") is None,
       "confirmed sign-out stops native tracking and clears token and queue")
    ok(k.evaluate("__watches") == 0, "bridge: since the reload the web GPS watch never ran, so no double pings")

    # N3: a hidden page never starts the wrapper's service (it would get no location); back on screen it starts at once
    start = lambda m, shift: ["start", {"baseUrl": base, "token": tok(), "vehicleId": vid, "missionId": m, "shift": shift}]
    k.fill("#code", code()); k.click("#f button"); k.wait_for_selector("#ack")
    call(base, "PATCH", f"/missions/{m9}/status", atok, {"status": "CANCELLED", "reason": "e2e"})
    k.click("#rf"); k.wait_for_selector(".card.ended")
    ok(calls()[-1] == ["stop"] and k.inner_text("#shift").startswith("ডিউটি শুরু"),
       "off shift, a mission's end stops native tracking; the wrapper offers 'Start shift' (paired vehicle)")
    k.evaluate("Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'})")
    m10, n = mission("Uttara-10"), len(calls())
    k.evaluate("load()")
    ok(k.is_visible("#ack") and len(calls()) == n and k.evaluate("__watches") == 0,
       "N3: with the app hidden, a new mission calls neither startTracking nor the web GPS watch")
    k.evaluate("delete document.visibilityState; document.dispatchEvent(new Event('visibilitychange'))")
    wait_until(lambda: calls()[-1] == start(m10, False), "N3: back on screen, startTracking at once")

    # N1/N2: on shift the service reports the paired vehicle between missions and rings for new ones (native side)
    call(base, "PATCH", f"/missions/{m10}/status", atok, {"status": "CANCELLED", "reason": "e2e"})
    k.click("#rf"); k.wait_for_selector(".card.ended")
    k.click("#shift")
    wait_until(lambda: calls()[-1] == start("", True), "Start shift: startTracking with the paired vehicle, no mission, shift true")
    ok("ডিউটিতে আছেন" in k.inner_text("#status") and k.inner_text("#shift") == "ডিউটি শেষ",
       "on shift: Bangla notice and an 'End shift' button")
    shot(k, "driver_360_on_shift.png", "driver app 360x740 in the wrapper, on shift between missions (Bangla notice)")
    time.sleep(1.1)  # the web path pinged this vehicle a moment ago; the server allows 1 ping/s per vehicle
    ok(call(base, "POST", f"/vehicles/{vid}/pings", tok(), {"lat": 23.87, "lng": 90.4, "ts": utcnow(), "on_shift": True})["ok"],
       "the server accepts the wrapper's on-shift ping between missions (kept one per 30 s)")
    v = next(x for x in api(base, atok, "/vehicles") if x["vehicle_id"] == vid)
    ok(not v["busy"] and not v["last_position"]["stale"], "N2: the console sees the free vehicle with a fresh position")
    m11 = mission("Uttara-11")
    k.click("#rf"); k.wait_for_selector("#ack")
    ok(calls()[-1] == start(m11, True), "on shift, a mission restarts native tracking with the mission, still on shift")
    k.reload(); k.wait_for_selector("#ack")
    ok(calls() == [start(m11, True)] and k.inner_text("#shift") == "ডিউটি শেষ", "the shift survives an app restart")
    k.click("#shift"); k.wait_for_selector("text=ডিউটি শুরু (মিশনের অ্যালার্ম, প্রতি মিনিটে লোকেশন)")
    ok(calls()[-1] == start(m11, False), "End shift during a mission: tracking goes on for the mission only")
    k.click("#shift"); k.click("#lo"); k.click("dialog button[data-v='1']"); k.wait_for_selector("#code")
    ok(calls()[-1] == ["stop"] and k.evaluate("localStorage.getItem('shift')") is None, "sign-out ends the shift too")
    ctx.close()



if __name__ == "__main__":
    main()

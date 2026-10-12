"""Mock of the driver API contract + static serving of this directory at /driver/. Stdlib only.
Usage: python mock_server.py [port]   Token: any string, e.g. 'test'; token 'bad' gives 401."""
import json, os, sys, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
# Same states/edges as app/state_machine.py (a test asserts this). Drivers may not cancel, so /meta/transitions
# (driver view) omits CANCELLED; the mock never produces it.
FLOW = {"DISPATCHED": ["EN_ROUTE_PICKUP"], "EN_ROUTE_PICKUP": ["AT_SCENE"], "AT_SCENE": ["TRANSPORTING_PATIENT"],
        "TRANSPORTING_PATIENT": ["AT_HOSPITAL"], "AT_HOSPITAL": ["COMPLETED"], "COMPLETED": [], "CANCELLED": []}
STATE = {"status": "DISPATCHED"}
PINGS, LAST = [], {}
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".webmanifest": "application/manifest+json"}


class H(BaseHTTPRequestHandler):
    def send(self, code, obj=None, raw=None, ctype="application/json"):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def authed(self):
        a = self.headers.get("Authorization", "")
        if a.startswith("Bearer ") and a[7:] not in ("", "bad"): return True
        self.send(401, {"detail": "unauthorized"}); return False

    def do_GET(self):
        p = self.path.split("?")[0]
        if p.startswith("/driver"):
            f = p[len("/driver"):].strip("/") or "index.html"
            fp = os.path.join(HERE, f)
            if "/" in f or not os.path.isfile(fp): return self.send(404, {})
            return self.send(200, raw=open(fp, "rb").read(), ctype=TYPES.get(os.path.splitext(f)[1], "application/octet-stream"))
        if p == "/_pings": return self.send(200, PINGS)
        if not self.authed(): return
        if p == "/me": return self.send(200, {"role": "driver", "user_id": 1, "driver_id": 1, "vehicle_id": 1})
        if p == "/meta/transitions": return self.send(200, FLOW)
        if p == "/missions/current": return self.send(200, {"mission_id": 7, "status": STATE["status"], "pickup_address": "Mirpur-10", "pickup_lat": 23.78, "pickup_lng": 90.41})
        self.send(404, {})

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def do_PATCH(self):
        if not self.authed(): return
        if self.path == "/missions/7/status":
            s = self.body().get("status")
            if s not in FLOW[STATE["status"]]: return self.send(409, {"detail": "conflict"})
            STATE["status"] = s; return self.send(200, {"mission_id": 7, "status": s})
        self.send(404, {})

    def do_POST(self):
        if not self.authed(): return
        if self.path == "/_reset": STATE["status"] = "DISPATCHED"; PINGS.clear(); return self.send(200, {})
        if self.path == "/vehicles/1/pings":
            b = self.body()
            try:
                ts = datetime.fromisoformat(b["ts"].replace("Z", "+00:00"))
                float(b["lat"]); float(b["lng"])
                if ts.tzinfo is None: raise ValueError
            except Exception: return self.send(422, {"detail": "bad ping"})
            d = (ts - datetime.now(timezone.utc)).total_seconds()
            if d < -300 or d > 60: return self.send(422, {"detail": "ts out of range"})
            if time.time() - LAST.get(1, 0) < 1: return self.send(429, {"detail": "too fast"})
            LAST[1] = time.time(); PINGS.append(b); return self.send(201, {})
        self.send(404, {})

    def log_message(self, *a): pass  # never log (headers carry tokens)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print(f"http://127.0.0.1:{port}/driver/"); ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()

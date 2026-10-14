"""SMS fallback against a local fake of the BulkSMSBD HTTP API; no real gateway is ever called."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest

from tests.test_api import env, mk  # noqa: F401


@pytest.fixture
def gateway(monkeypatch):
    got, reply = [], {"status": 200, "body": {"response_code": 202, "message_id": 1}}

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):
            form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            got.append({"path": self.path, **{k: v[0] for k, v in form.items()}})
            self.send_response(reply["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(reply["body"]).encode())

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for k, v in {"AMBULANCE_SMS_URL": f"http://127.0.0.1:{srv.server_port}/api/smsapi", "AMBULANCE_SMS_API_KEY": "k-test",
                 "AMBULANCE_SMS_SENDER_ID": "8809600000000", "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}.items():
        monkeypatch.setenv(k, v)
    yield got, reply
    srv.shutdown()


def sms_rows(e):
    return [tuple(r) for r in e["db"].execute("SELECT mission_id, driver_id, event, result FROM sms_audit ORDER BY id")]


def with_phone(e):
    assert e["c"].patch(f"/drivers/{e['drv']}", json={"phone": "01711234567"}, headers=e["D"]).status_code == 200


def test_sms_on_create_and_cancel(env, gateway):
    got, _ = gateway
    with_phone(env)
    m = mk(env, pickup_lat=23.78, pickup_lng=90.41)
    assert len(got) == 1
    s = got[0]
    assert (s["path"], s["api_key"], s["senderid"], s["number"], s["type"]) == (
        "/api/smsapi", "k-test", "8809600000000", "8801711234567", "text")
    assert m[:8] in s["message"] and "Mirpur-10" in s["message"] and "maps.google.com/?q=23.78,90.41" in s["message"]
    env["c"].patch(f"/missions/{m}/status", json={"status": "CANCELLED"}, headers=env["D"])
    assert len(got) == 2 and got[1]["message"].startswith("CANCELLED")
    assert sms_rows(env) == [(m, env["drv"], "create", "sent"), (m, env["drv"], "cancel", "sent")]


def test_sms_failure_never_fails_dispatch(env, gateway):
    got, reply = gateway
    with_phone(env)
    reply["status"] = 500
    m = mk(env)  # still 201
    reply.update(status=200, body={"response_code": 1007, "error_message": "Balance Insufficient"})
    env["c"].patch(f"/missions/{m}/status", json={"status": "CANCELLED"}, headers=env["D"])
    assert [r[3] for r in sms_rows(env)] == ["error: HTTPError 500", "error: response_code 1007"]
    assert "k-test" not in str(sms_rows(env))


def test_sms_unreachable_gateway_is_recorded(env, gateway, monkeypatch):
    with_phone(env)
    monkeypatch.setenv("AMBULANCE_SMS_URL", "http://127.0.0.1:9/api/smsapi")  # discard port: nothing listens
    mk(env)
    assert sms_rows(env)[0][3].startswith("error: URLError")


def test_sms_bangla_text_uses_unicode(env, gateway):
    got, _ = gateway
    with_phone(env)
    mk(env, pickup_address="মিরপুর ১০")
    assert got[0]["type"] == "unicode" and "মিরপুর ১০" in got[0]["message"]


def test_sms_disabled_without_env_or_phone(env, gateway, monkeypatch):
    got, _ = gateway
    m = mk(env)  # driver has no phone
    env["c"].patch(f"/missions/{m}/status", json={"status": "CANCELLED"}, headers=env["D"])
    with_phone(env)
    monkeypatch.delenv("AMBULANCE_SMS_API_KEY")
    mk(env)  # no gateway configured
    env["c"].post("/missions", json={"pickup_address": "x"}, headers=env["D"])  # no driver at all
    assert got == [] and sms_rows(env) == []


def test_backfill_keeps_step_order_and_never_pages_the_driver(env, gateway):
    """Paper-log back-fill: the real dispatch time becomes created_at, steps only move forward, no SMS goes out."""
    from tests.test_api import iso
    got, _ = gateway
    with_phone(env)
    c, D = env["c"], env["D"]
    assert c.post("/missions", json={"pickup_address": "x", "assigned_vehicle_id": env["veh"],
                                     "dispatched_at": iso(days=-8)}, headers=D).status_code == 422  # outside 7 days
    m = mk(env, dispatched_at=iso(hours=-3))
    assert got == [] and sms_rows(env) == []  # the driver is not alerted for a mission that is already over
    p = f"/missions/{m}/status"
    assert c.patch(p, json={"status": "EN_ROUTE_PICKUP", "reason": "outage, paper log", "event_time": iso(hours=-4)},
                   headers=D).status_code == 422  # before the dispatch time
    assert c.patch(p, json={"status": "EN_ROUTE_PICKUP", "reason": "outage, paper log", "event_time": iso(hours=-2)},
                   headers=D).status_code == 200
    assert c.patch(p, json={"status": "AT_SCENE", "reason": "outage, paper log", "event_time": iso(hours=-2, minutes=-10)},
                   headers=D).status_code == 422  # before the previous step
    r = c.patch(p, json={"status": "AT_SCENE", "reason": "outage, paper log", "event_time": iso(hours=-1)}, headers=D)
    assert r.status_code == 200 and r.json()["created_at"] < r.json()["en_route_pickup_at"] < r.json()["at_scene_at"]
    first = c.get(f"/missions/{m}/audit", headers=D).json()[0]
    assert first["reason"] == "back-fill" and first["event_time"] == r.json()["created_at"] and first["ts"] > first["event_time"]

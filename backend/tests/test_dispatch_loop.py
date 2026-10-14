"""Critique 2026-10-14: the dispatch loop (B1-B4, B7, B14, B15, S8) and the API the map console and driver app need."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import bd_phone, create_app
from tests.test_api import DHAKA, env, free, iso, mk  # noqa: F401


def ping(e, hdr="V", veh="veh", **kw):
    return e["c"].post(f"/vehicles/{e[veh]}/pings", json={**DHAKA, "ts": iso(), **kw}, headers=e[hdr])


def walk(e, mid, *states, hdr="V"):
    for s in states:
        assert e["c"].patch(f"/missions/{mid}/status", json={"status": s}, headers=e[hdr]).status_code == 200, s


def test_b1_newest_first_past_200_and_active_unpaged(env):
    c, D, db = env["c"], env["D"], env["db"]
    for i in range(205):  # history older than the default page
        db.execute("INSERT INTO missions (id,status,pickup_address,created_at,updated_at) VALUES (?,?,?,?,?)",
                   (str(uuid.uuid4()), "COMPLETED", f"old{i}", f"2026-01-01T00:00:{i % 60:02d}.{i:06d}+00:00", "t"))
    db.commit()
    new = mk(env)
    other = c.post("/missions", json={"pickup_address": "bare"}, headers=D).json()["mission_id"]
    assert [m["mission_id"] for m in c.get("/missions", headers=D).json()[:2]] == [other, new]
    act = c.get("/missions?active=true&limit=1", headers=D).json()  # limit is ignored for the active view
    assert [m["mission_id"] for m in act] == [other, new]
    c.patch(f"/missions/{other}/status", json={"status": "CANCELLED"}, headers=D)
    assert [m["mission_id"] for m in c.get("/missions?active=true", headers=D).json()] == [new]
    assert [m["mission_id"] for m in c.get("/missions?active=true&status=CANCELLED", headers=D).json()] == []


def test_b2_one_active_mission_per_vehicle_and_driver(env):
    c, D = env["c"], env["D"]
    first = mk(env)
    body = {"pickup_address": "y", "assigned_vehicle_id": env["veh"], "assigned_driver_id": env["drv2"]}
    assert c.post("/missions", json=body, headers=D).status_code == 409  # vehicle busy
    body = {"pickup_address": "y", "assigned_vehicle_id": env["veh2"], "assigned_driver_id": env["drv"]}
    assert c.post("/missions", json=body, headers=D).status_code == 409  # driver busy
    walk(env, first, "CANCELLED", hdr="D")
    assert mk(env)


def test_b2_concurrent_dispatch_has_one_winner(env):
    body = {"pickup_address": "x", "assigned_vehicle_id": env["veh"], "assigned_driver_id": None}
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda _: env["c"].post("/missions", json=body, headers=env["D"]).status_code, range(8)))
    assert codes.count(201) == 1 and set(codes) <= {201, 409}


def test_b2_unique_index_backs_the_check(env):
    import pytest as _p
    from app.db import IntegrityError
    mk(env)
    db = env["db"]
    with _p.raises(IntegrityError):  # a writer that skips the API check still cannot double-dispatch
        db.execute("INSERT INTO missions (id,status,pickup_address,assigned_vehicle_id,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), "AT_SCENE", "x", env["veh"], iso(), iso()))
    db.rollback()


def test_b3_dispatcher_moves_for_the_driver(env):
    c, D, db = env["c"], env["D"], env["db"]
    m = mk(env)
    walk(env, m, "EN_ROUTE_PICKUP", "AT_SCENE", "TRANSPORTING_PATIENT")
    p = f"/missions/{m}/status"
    assert c.patch(p, json={"status": "CANCELLED"}, headers=D).status_code == 409  # cancel rules unchanged
    assert c.patch(p, json={"status": "AT_HOSPITAL"}, headers=D).status_code == 422  # reason required
    assert c.patch(p, json={"status": "AT_HOSPITAL", "reason": "x", "event_time": iso(minutes=5)}, headers=D).status_code == 422
    assert c.patch(p, json={"status": "AT_HOSPITAL", "reason": "x", "event_time": "2000-01-01T00:00:00Z"},
                   headers=D).status_code == 422  # older than the back-fill window
    assert c.patch(p, json={"status": "AT_HOSPITAL", "reason": "x"}, headers=env["V"]).status_code == 422  # drivers cannot
    when = iso(hours=-1)  # before the mission was entered: a paper-log back-fill after an outage
    r = c.patch(p, json={"status": "AT_HOSPITAL", "reason": "driver phone dead", "event_time": when}, headers=D)
    assert r.status_code == 200 and r.json()["status"] == "AT_HOSPITAL"
    assert datetime.fromisoformat(r.json()["at_hospital_at"]) == datetime.fromisoformat(when)
    last = c.get(f"/missions/{m}/audit", headers=D).json()[-1]
    disp = db.execute("SELECT id FROM users WHERE name='disp'").fetchone()[0]
    assert (last["user_id"], last["on_behalf_of"], last["reason"]) == (disp, env["drv"], "driver phone dead")
    assert c.patch(p, json={"status": "COMPLETED", "reason": "closed by radio"}, headers=env["P"]).status_code == 200  # plain dispatcher too
    assert c.get(f"/missions/{m}/audit", headers=D).json()[1]["on_behalf_of"] is None  # the driver's own move


def test_b3_every_advertised_on_behalf_edge_is_accepted(env):
    c, D = env["c"], env["D"]
    tr = c.get("/meta/transitions?on_behalf=true", headers=D).json()
    assert tr["TRANSPORTING_PATIENT"] == ["AT_HOSPITAL"] and tr["DISPATCHED"] == ["EN_ROUTE_PICKUP"] and tr["COMPLETED"] == []
    assert c.get("/meta/transitions?on_behalf=true", headers=env["V"]).json()["DISPATCHED"] == []  # drivers act for nobody
    for src, dsts in tr.items():
        for dst in dsts:
            free(env)
            m = mk(env)
            env["db"].execute("UPDATE missions SET status=? WHERE id=?", (src, m)); env["db"].commit()
            assert c.patch(f"/missions/{m}/status", json={"status": dst, "reason": "r"}, headers=D).status_code == 200


def test_b4_skewed_phone_clock_is_accepted_and_reported(env):
    c = env["c"]
    mk(env)
    r = ping(env, ts=iso(minutes=2))
    assert r.status_code == 201 and 110 < r.json()["clock_skew_s"] < 130
    pos = c.get(f"/vehicles/{env['veh']}/position", headers=env["D"]).json()
    assert datetime.fromisoformat(pos["ts"]) <= datetime.now(timezone.utc)  # stored at receive time
    r = ping(env, ts=iso(minutes=-6))
    assert r.status_code == 201 and -370 < r.json()["clock_skew_s"] < -350
    # queued offline: sent_at says the fix is 30 s old; that age survives any skew
    r = ping(env, ts=iso(minutes=-10, seconds=-30), sent_at=iso(minutes=-10))
    assert r.status_code == 201
    rows = env["db"].execute("SELECT ts FROM vehicle_pings ORDER BY id").fetchall()
    age = datetime.now(timezone.utc) - datetime.fromisoformat(rows[-1]["ts"])
    assert timedelta(seconds=29) < age < timedelta(seconds=40)
    assert ping(env, ts=iso(minutes=-6), sent_at=iso()).status_code == 422  # a 6-minute-old fix is too old


def test_b7_driver_needs_a_vehicle_and_pairing_fills_the_gap(env):
    c, D = env["c"], env["D"]
    body = {"pickup_address": "x", "assigned_driver_id": env["drv"]}
    assert c.post("/missions", json=body, headers=D).status_code == 422  # driver with no vehicle
    assert c.put(f"/vehicles/{env['veh']}/driver", json={"driver_id": env["drv"]}, headers=D).json()["driver_id"] == env["drv"]
    m = c.post("/missions", json=body, headers=D).json()
    assert (m["assigned_vehicle_id"], m["assigned_driver_id"]) == (env["veh"], env["drv"])
    free(env)
    m = c.post("/missions", json={"pickup_address": "x", "assigned_vehicle_id": env["veh"]}, headers=D).json()
    assert m["assigned_driver_id"] == env["drv"]  # vehicle alone: its paired driver
    free(env)
    m = c.post("/missions", json={"pickup_address": "x", "assigned_vehicle_id": env["veh"], "assigned_driver_id": None},
               headers=D).json()
    assert m["assigned_driver_id"] is None  # explicit null: no driver


def test_vehicle_driver_pairing(env):
    c, D = env["c"], env["D"]
    put = lambda v, d, h=D: c.put(f"/vehicles/{env[v]}/driver", json={"driver_id": d}, headers=h)
    assert put("veh", env["drv"]).status_code == 200
    assert put("veh2", env["drv"]).json()["driver_id"] == env["drv"]  # moving him unpairs the first vehicle
    by = {v["vehicle_id"]: v for v in c.get("/vehicles", headers=D).json()}
    assert by[env["veh"]]["driver_id"] is None and by[env["veh2"]]["driver_id"] == env["drv"]
    assert put("veh2", None).json()["driver_id"] is None
    assert put("veh", "nope").status_code == 422
    assert c.put("/vehicles/nope/driver", json={"driver_id": None}, headers=D).status_code == 404
    assert put("veh", env["drv"], env["V"]).status_code == 403
    assert put("veh", env["drv"], env["P"]).status_code == 200  # dispatching, not admin work
    assert c.put(f"/vehicles/{env['veh']}/driver", json={}, headers=D).status_code == 422  # null must be explicit


def test_a5_vehicle_can_be_taken_out_of_service(env):
    c, D = env["c"], env["D"]
    assert c.patch(f"/vehicles/{env['veh']}", json={"active": False}, headers=D).json()["active"] is False
    assert c.post("/missions", json={"pickup_address": "x", "assigned_vehicle_id": env["veh"]}, headers=D).status_code == 422
    assert c.patch(f"/vehicles/{env['veh']}", json={"active": True}, headers=D).status_code == 200
    assert c.post("/missions", json={"pickup_address": "x", "assigned_vehicle_id": env["veh"]}, headers=D).status_code == 201
    assert c.patch("/vehicles/nope", json={"active": True}, headers=D).status_code == 404
    assert c.patch(f"/vehicles/{env['veh']}", json={"active": True}, headers=env["V"]).status_code == 403


def test_b14_revoked_or_expired_driver_not_assignable(env):
    c, D, db = env["c"], env["D"], env["db"]
    c.post(f"/drivers/{env['drv']}/token/revoke", headers=D)
    assert c.post("/missions", json={"pickup_address": "x", "assigned_vehicle_id": env["veh"],
                                     "assigned_driver_id": env["drv"]}, headers=D).status_code == 422
    assert c.put(f"/vehicles/{env['veh']}/driver", json={"driver_id": env["drv"]}, headers=D).status_code == 422
    by = {d["driver_id"]: d for d in c.get("/drivers", headers=D).json()}
    assert by[env["drv"]]["revoked"] is True and by[env["drv2"]]["revoked"] is False and by[env["drv2"]]["expires_at"] > iso()
    db.execute("UPDATE users SET token_expires_at='2000-01-01T00:00:00+00:00' WHERE name='drv2'"); db.commit()
    assert c.post("/missions", json={"pickup_address": "x", "assigned_vehicle_id": env["veh2"],
                                     "assigned_driver_id": env["drv2"]}, headers=D).status_code == 422


def test_ack_and_per_status_times(env):
    c = env["c"]
    m = mk(env)
    r = c.get(f"/missions/{m}", headers=env["D"]).json()
    assert r["acknowledged_at"] is None and r["en_route_pickup_at"] is None and r["created_at"]
    assert c.post(f"/missions/{m}/ack", headers=env["V2"]).status_code == 403
    assert c.post(f"/missions/{m}/ack", headers=env["D"]).status_code == 403
    first = c.post(f"/missions/{m}/ack", headers=env["V"]).json()["acknowledged_at"]
    assert first and c.post(f"/missions/{m}/ack", headers=env["V"]).json()["acknowledged_at"] == first  # once
    walk(env, m, "EN_ROUTE_PICKUP")
    r = c.get(f"/missions/{m}", headers=env["D"]).json()
    assert r["en_route_pickup_at"] == r["updated_at"] and r["at_scene_at"] is None
    walk(env, m, "CANCELLED", hdr="D")
    assert c.get(f"/missions/{m}", headers=env["D"]).json()["cancelled_at"]
    assert c.post(f"/missions/{m}/ack", headers=env["V"]).status_code == 409
    assert c.post(f"/missions/{uuid.uuid4()}/ack", headers=env["V"]).status_code == 404


def test_s8_spoofed_positions(env):
    mk(env)
    assert ping(env).status_code == 201
    assert ping(env, lat=51.5, lng=-0.12).status_code == 422  # London one second later
    assert ping(env, lat=0, lng=0).status_code == 422
    assert ping(env, lat=DHAKA["lat"] + 0.005).status_code == 201  # 550 m: GPS noise is tolerated
    assert ping(env, lat=DHAKA["lat"] + 0.03).status_code == 422  # 3 km in a second
    assert ping(env, lat=DHAKA["lat"] + 0.03, accuracy=2500).status_code == 201  # unless the fix says it is that rough
    env["db"].execute("UPDATE vehicle_pings SET ts='2000-01-01T00:00:00+00:00'"); env["db"].commit()
    assert ping(env, lat=22.35, lng=91.78).status_code == 201  # Chittagong after a long gap is fine


@pytest.mark.parametrize("raw,norm", [
    ("01711234567", "+8801711234567"), ("+8801711234567", "+8801711234567"), ("8801911234567", "+8801911234567"),
    ("০১৭১১২৩৪৫৬৭", "+8801711234567"), ("+৮৮০১৭১১-২৩৪৫৬৭", "+8801711234567"), (" 017 1123 4567 ", "+8801711234567"),
])
def test_phone_normalised(raw, norm):
    assert bd_phone(raw) == norm


@pytest.mark.parametrize("raw", ["", "1711234567", "0171123456", "017112345678", "01211234567", "+44 7700 900123",
                                 "+8801711234567x", "০১৭১১২৩৪৫৬", "8801711234567 ext 2", "+880-1711-234567-1"])
def test_phone_rejected(raw):
    with pytest.raises(ValueError):
        bd_phone(raw)


def test_driver_phone_api(env):
    c, D = env["c"], env["D"]
    r = c.post("/drivers", json={"name": "k", "phone": "০১৮১১২৩৪৫৬৭"}, headers=D)
    assert r.status_code == 201 and r.json()["phone"] == "+8801811234567"
    assert c.post("/drivers", json={"name": "k", "phone": "12345"}, headers=D).status_code == 422
    did = r.json()["driver_id"]
    assert c.patch(f"/drivers/{did}", json={"phone": "01911234567"}, headers=env["P"]).json()["phone"] == "+8801911234567"
    assert c.patch(f"/drivers/{did}", json={"phone": "abc"}, headers=D).status_code == 422
    assert c.patch(f"/drivers/{did}", json={"phone": None}, headers=D).json()["phone"] is None
    assert c.patch("/drivers/nope", json={"phone": None}, headers=D).status_code == 404
    assert c.patch(f"/drivers/{did}", json={"phone": None}, headers=env["V"]).status_code == 403


def test_healthz(env, monkeypatch):
    c = env["c"]
    assert c.get("/healthz").json() == {"ok": True}
    import app.main

    def down(_):
        raise OSError("db down")
    monkeypatch.setattr(app.main, "open_db", down)
    r = c.get("/healthz")
    assert r.status_code == 503 and r.json() == {"ok": False}


def test_s5_docs_only_in_dev(env, monkeypatch):
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert env["c"].get(p).status_code == 404
    monkeypatch.setenv("AMBULANCE_DEV", "1")
    dev = TestClient(create_app(env["path"]))
    assert dev.get("/docs").status_code == 200 and dev.get("/openapi.json").status_code == 200


def test_b10_db_path_required_outside_dev(monkeypatch):
    from app.db import db_target
    monkeypatch.delenv("AMBULANCE_DB_PATH", raising=False)
    monkeypatch.delenv("AMBULANCE_DEV", raising=False)
    with pytest.raises(RuntimeError, match="AMBULANCE_DB_PATH"):
        create_app()
    monkeypatch.setenv("AMBULANCE_DEV", "1")
    assert db_target() == "dev.db"
    monkeypatch.setenv("AMBULANCE_DB_PATH", "/x/y.db")
    assert db_target() == "/x/y.db"


def test_ping_retention(env, monkeypatch):
    db = env["db"]
    old, mid, new = (datetime.now(timezone.utc) - timedelta(days=d) for d in (100, 40, 1))
    for t in (old, mid, new):
        db.execute("INSERT INTO vehicle_pings (vehicle_id,lat,lng,ts) VALUES ('v',1,1,?)", (t.isoformat(),))
    db.commit()
    count = lambda: db.execute("SELECT COUNT(*) FROM vehicle_pings").fetchone()[0]
    create_app(env["path"])  # default 90 days, pruned at startup
    assert count() == 2
    monkeypatch.setenv("AMBULANCE_PING_RETENTION_DAYS", "30")
    create_app(env["path"])
    assert count() == 1
    monkeypatch.setenv("AMBULANCE_PING_RETENTION_DAYS", "0")
    with pytest.raises(RuntimeError):
        create_app(env["path"])


def test_s10_create_rate_limit_per_token(env):
    c = TestClient(create_app(env["path"], create_per_min=2))
    post = lambda h: c.post("/missions", json={"pickup_address": "x"}, headers=env[h]).status_code
    assert [post("D"), post("D"), post("D")] == [201, 201, 429]
    assert c.post("/drivers", json={"name": "n"}, headers=env["D"]).status_code == 429  # same budget
    assert post("P") == 201  # another token is not affected


def test_b12_create_and_audit_are_atomic(env, monkeypatch):
    import app.main

    def boom(*a):
        raise RuntimeError("audit write failed")
    monkeypatch.setattr(app.main, "auth_audit", boom)
    n = lambda t: env["db"].execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    before = n("drivers"), n("users"), n("vehicles")
    with pytest.raises(RuntimeError):
        env["c"].post("/drivers", json={"name": "ghost"}, headers=env["D"])
    with pytest.raises(RuntimeError):
        env["c"].post("/vehicles", json={"operator": "o", "registration": "GHOST"}, headers=env["D"])
    assert (n("drivers"), n("users"), n("vehicles")) == before

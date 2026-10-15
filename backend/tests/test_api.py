import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import add_user, add_vehicle
from app.main import create_app


def iso(**kw):
    return (datetime.now(timezone.utc) + timedelta(**kw)).isoformat()


@pytest.fixture
def env(target):
    app = create_app(target, ping_min_interval_s=0)
    c = TestClient(app)
    # second connection to the same file just for seeding; commit makes it visible
    from app.db import connect
    db = connect(target)
    did, dt = add_user(db, "disp", "dispatcher", admin=True)
    pid, pt = add_user(db, "plain", "dispatcher")
    drv, vt = add_user(db, "drv1", "driver")
    drv2, vt2 = add_user(db, "drv2", "driver")
    veh = add_vehicle(db, "Op", "DHK-1")
    veh2 = add_vehicle(db, "Op", "DHK-2")
    db.commit()
    h = lambda t: {"Authorization": f"Bearer {t}"}
    return dict(c=c, app=app, db=db, D=h(dt), P=h(pt), V=h(vt), V2=h(vt2), drv=drv, drv2=drv2, veh=veh, veh2=veh2,
                did=did, pid=pid, path=target)


def mk(e, **kw):
    body = {"pickup_address": "Mirpur-10", "assigned_vehicle_id": e["veh"], "assigned_driver_id": e["drv"], **kw}
    r = e["c"].post("/missions", json=body, headers=e["D"])
    assert r.status_code == 201, r.text
    return r.json()["mission_id"]


def free(e):
    """End every active mission in the DB, so the next mk() may reuse the same vehicle and driver."""
    e["db"].execute("UPDATE missions SET status='CANCELLED' WHERE status NOT IN ('COMPLETED','CANCELLED')")
    e["db"].commit()


DHAKA = {"lat": 23.8103, "lng": 90.4125}


def test_auth_required(env):
    c = env["c"]
    assert c.post("/missions", json={"pickup_address": "x"}).status_code == 401
    assert c.post("/missions", json={"pickup_address": "x"}, headers={"Authorization": "Bearer no"}).status_code == 401
    assert c.post("/missions", json={"pickup_address": "x"}, headers=env["V"]).status_code == 403


def test_tokens_stored_hashed(env):
    raw = env["D"]["Authorization"][7:]
    assert raw not in str([tuple(r) for r in env["db"].execute("SELECT * FROM users")])
    assert len(env["db"].execute("SELECT token_hash FROM users").fetchone()[0]) == 64


def test_lifecycle_and_audit(env):
    c, V, D = env["c"], env["V"], env["D"]
    m = mk(env)
    uuid.UUID(m)
    assert c.get(f"/missions/{m}", headers=D).json()["status"] == "DISPATCHED"
    for s in ["EN_ROUTE_PICKUP", "AT_SCENE", "TRANSPORTING_PATIENT", "AT_HOSPITAL", "COMPLETED"]:
        assert c.patch(f"/missions/{m}/status", json={"status": s}, headers=V).status_code == 200
    assert c.patch(f"/missions/{m}/status", json={"status": "CANCELLED"}, headers=D).status_code == 409
    rows = env["db"].execute("SELECT user_id,from_status,to_status,ts FROM mission_audit WHERE mission_id=? ORDER BY id", (m,)).fetchall()
    assert [(r["from_status"], r["to_status"]) for r in rows] == [
        (None, "DISPATCHED"), ("DISPATCHED", "EN_ROUTE_PICKUP"), ("EN_ROUTE_PICKUP", "AT_SCENE"),
        ("AT_SCENE", "TRANSPORTING_PATIENT"), ("TRANSPORTING_PATIENT", "AT_HOSPITAL"), ("AT_HOSPITAL", "COMPLETED")]
    assert rows[0]["user_id"] != rows[1]["user_id"] and all(r["ts"] for r in rows)
    # rejected transition leaves no audit row
    assert env["db"].execute("SELECT COUNT(*) FROM mission_audit WHERE mission_id=?", (m,)).fetchone()[0] == 6


def test_roles_binding_and_invalid(env):
    c, V, V2, D = env["c"], env["V"], env["V2"], env["D"]
    m = mk(env)
    p = f"/missions/{m}/status"
    assert c.patch(p, json={"status": "EN_ROUTE_PICKUP"}, headers=V2).status_code == 403  # other driver
    assert c.get(f"/missions/{m}", headers=V2).status_code == 403
    assert c.patch(p, json={"status": "AT_SCENE"}, headers=V).status_code == 409
    assert c.patch(p, json={"status": "CANCELLED"}, headers=V).status_code == 403
    assert c.patch(p, json={"status": "EN_ROUTE_PICKUP"}, headers=D).status_code == 422  # on-behalf needs a reason
    assert c.patch(p, json={"status": "CANCELLED", "notes": "x"}, headers=D).status_code == 422  # notes removed
    assert c.patch(p, json={"status": "CANCELLED"}, headers=D).status_code == 200
    assert c.patch(p, json={"status": "BOGUS"}, headers=V).status_code == 422
    assert c.get("/missions/not-a-uuid", headers=D).status_code == 404
    assert c.get(f"/missions/{uuid.uuid4()}", headers=D).status_code == 404
    unassigned = c.post("/missions", json={"pickup_address": "x"}, headers=D).json()["mission_id"]
    assert c.patch(f"/missions/{unassigned}/status", json={"status": "EN_ROUTE_PICKUP"}, headers=V).status_code == 403


def test_assignment_validation(env):
    c, D = env["c"], env["D"]
    assert c.post("/missions", json={"pickup_address": "x", "assigned_vehicle_id": "nope"}, headers=D).status_code == 422
    assert c.post("/missions", json={"pickup_address": "x", "assigned_driver_id": "nope"}, headers=D).status_code == 422
    env["db"].execute("UPDATE vehicles SET active=? WHERE id=?", (False, env["veh2"])); env["db"].commit()
    assert c.post("/missions", json={"pickup_address": "x", "assigned_vehicle_id": env["veh2"]}, headers=D).status_code == 422


def test_list_missions(env):
    c, D, V = env["c"], env["D"], env["V"]
    a, b = mk(env, assigned_vehicle_id=env["veh2"], assigned_driver_id=env["drv2"]), mk(env)
    c.patch(f"/missions/{b}/status", json={"status": "EN_ROUTE_PICKUP"}, headers=V)
    assert {x["mission_id"] for x in c.get("/missions", headers=D).json()} == {a, b}
    assert [x["mission_id"] for x in c.get("/missions?status=EN_ROUTE_PICKUP", headers=D).json()] == [b]
    assert c.get("/missions?status=BOGUS", headers=D).status_code == 422
    assert c.get("/missions", headers=V).status_code == 403


@pytest.mark.parametrize("body,code", [
    ({"lat": 23.8, "lng": 90.4, "ts": "NOW"}, 201),
    ({"lat": 91, "lng": 90.4, "ts": "NOW"}, 422),
    ({"lat": 23.8, "lng": 181, "ts": "NOW"}, 422),
    ({"lat": 23.8, "lng": 90.4, "ts": "yesterday"}, 422),
    ({"lat": 23.8, "lng": 90.4, "ts": "2026-10-12T10:00:00"}, 422),
    ({"lat": 23.8, "lng": 90.4}, 422),
    ({"lat": 23.8, "lng": 90.4, "ts": "STALE"}, 201),  # skewed phone clocks are accepted (B4)
    ({"lat": 23.8, "lng": 90.4, "ts": "FUTURE"}, 201),
    ({"lat": 0, "lng": 0, "ts": "NOW"}, 422),
])
def test_ping(env, body, code):
    mk(env)
    body = {**body, **({"ts": {"NOW": iso(), "STALE": iso(hours=-1), "FUTURE": iso(hours=1)}[body["ts"]]} if body.get("ts") in ("NOW", "STALE", "FUTURE") else {})}
    assert env["c"].post(f"/vehicles/{env['veh']}/pings", json=body, headers=env["V"]).status_code == code


def test_nan_body_is_422_not_500(env):
    mk(env)
    for path, raw in ((f"/vehicles/{env['veh']}/pings", '{"lat": NaN, "lng": 90.4, "ts": "%s"}' % iso()),
                      ("/missions", '{"pickup_address": "x", "pickup_lat": NaN, "pickup_lng": 1}')):
        r = env["c"].post(path, content=raw, headers={**(env["V"] if "pings" in path else env["D"]),
                                                      "content-type": "application/json"})
        assert r.status_code == 422 and "input" not in r.text, r.text


def test_ping_auth_and_binding(env):
    b = {"lat": 1, "lng": 1, "ts": iso()}
    c, v = env["c"], env["veh"]
    assert c.post(f"/vehicles/{v}/pings", json=b).status_code == 401
    assert c.post(f"/vehicles/{v}/pings", json=b, headers=env["D"]).status_code == 403
    assert c.post(f"/vehicles/{v}/pings", json=b, headers=env["V"]).status_code == 403  # no mission yet
    m = mk(env)
    assert c.post(f"/vehicles/{v}/pings", json=b, headers=env["V2"]).status_code == 403  # other driver
    assert c.post(f"/vehicles/{env['veh2']}/pings", json=b, headers=env["V"]).status_code == 403  # other vehicle
    assert c.post(f"/vehicles/{v}/pings", json=b, headers=env["V"]).status_code == 201
    c.patch(f"/missions/{m}/status", json={"status": "CANCELLED"}, headers=env["D"])
    assert c.post(f"/vehicles/{v}/pings", json=b, headers=env["V"]).status_code == 403  # mission over


def test_ping_rate_limit_and_position(env):
    app = create_app(env["path"], ping_min_interval_s=60)
    c = TestClient(app)
    mk(env)
    v = env["veh"]
    assert c.get(f"/vehicles/{v}/position", headers=env["D"]).status_code == 404
    assert c.post(f"/vehicles/{v}/pings", json={"lat": 23.81, "lng": 90.41, "ts": iso()}, headers=env["V"]).status_code == 201
    assert c.post(f"/vehicles/{v}/pings", json={"lat": 23.811, "lng": 90.41, "ts": iso()}, headers=env["V"]).status_code == 429
    r = c.get(f"/vehicles/{v}/position", headers=env["D"])
    assert r.status_code == 200 and (r.json()["lat"], r.json()["lng"]) == (23.81, 90.41)
    assert c.get(f"/vehicles/{v}/position", headers=env["V"]).status_code == 403


def test_stale_status_update_conflicts_without_audit(env):
    from fastapi import HTTPException
    mid = mk(env)
    assert env["c"].patch(f"/missions/{mid}/status", json={"status": "CANCELLED"}, headers=env["D"]).status_code == 200
    n = lambda: env["db"].execute("SELECT COUNT(*) FROM mission_audit WHERE mission_id=?", (mid,)).fetchone()[0]
    before = n()
    with pytest.raises(HTTPException) as ei:  # loser validated against the pre-cancel status
        env["app"].state.advance(env["db"], mid, "u", "DISPATCHED", "EN_ROUTE_PICKUP")
    assert ei.value.status_code == 409
    assert n() == before
    assert env["c"].get(f"/missions/{mid}", headers=env["D"]).json()["status"] == "CANCELLED"


def test_terminal_state_not_overwritten(env):
    mid = mk(env)
    env["c"].patch(f"/missions/{mid}/status", json={"status": "CANCELLED"}, headers=env["D"])
    r = env["c"].patch(f"/missions/{mid}/status", json={"status": "EN_ROUTE_PICKUP"}, headers=env["V"])
    assert r.status_code == 409
    assert env["c"].get(f"/missions/{mid}", headers=env["D"]).json()["status"] == "CANCELLED"


def test_missions_pagination(env):
    c, D = env["c"], env["D"]
    ids = [c.post("/missions", json={"pickup_address": f"x{i}"}, headers=D).json()["mission_id"] for i in range(3)][::-1]
    assert [m["mission_id"] for m in c.get("/missions", headers=D).json()] == ids  # newest first
    assert [m["mission_id"] for m in c.get("/missions?limit=2&offset=1", headers=D).json()] == ids[1:]
    for q in ("limit=0", "limit=501", "offset=-1"):
        assert c.get(f"/missions?{q}", headers=D).status_code == 422


def test_future_ping_clamped_to_receive_time(env):
    c = env["c"]
    mk(env)
    assert c.post(f"/vehicles/{env['veh']}/pings", json={"lat": 23.81, "lng": 90.41, "ts": iso(seconds=50)}, headers=env["V"]).status_code == 201
    assert c.post(f"/vehicles/{env['veh']}/pings", json={"lat": 23.811, "lng": 90.41, "ts": iso()}, headers=env["V"]).status_code == 201
    assert c.get(f"/vehicles/{env['veh']}/position", headers=env["D"]).json()["lat"] == 23.811


def test_vehicle_create_audited_and_prune_and_body_cap(env):
    c, db = env["c"], env["db"]
    assert c.post("/vehicles", json={"operator": "O", "registration": "X-9"}, headers=env["D"]).status_code == 201
    assert db.execute("SELECT COUNT(*) FROM auth_audit WHERE action='create_vehicle'").fetchone()[0] == 1
    db.execute("INSERT INTO ping_limit (vehicle_id,last_at) VALUES ('old', 1.0)")
    db.commit()
    create_app(env["path"])
    assert db.execute("SELECT COUNT(*) FROM ping_limit WHERE vehicle_id='old'").fetchone()[0] == 0
    r = c.post("/missions", content=b"x" * 70000, headers={**env["D"], "content-type": "application/json"})
    assert r.status_code == 413


def test_body_cap_counts_chunked_bodies(env):
    # A generator body goes out chunked with no Content-Length; the cap must count bytes as they are read.
    r = env["c"].post("/missions", content=(b"x" * 1024 for _ in range(70)),
                      headers={**env["D"], "content-type": "application/json"})
    assert r.status_code == 413 and "content-length" not in r.request.headers
    assert mk(env)  # a normal body still goes through


def test_prune_runs_periodically(env, monkeypatch):
    import time

    import app.main as main
    monkeypatch.setattr(main, "PRUNE_EVERY_S", 0.05)
    db = env["db"]
    with TestClient(create_app(env["path"])):  # the periodic task lives as long as the app (lifespan)
        db.execute("INSERT INTO ping_limit (vehicle_id,last_at) VALUES ('old', 1.0)")
        db.commit()
        for _ in range(100):
            time.sleep(0.05)
            db.rollback()  # end this connection's snapshot so it sees the prune's commit
            if not db.execute("SELECT COUNT(*) FROM ping_limit WHERE vehicle_id='old'").fetchone()[0]:
                break
        else:
            raise AssertionError("ping_limit was not pruned while the app ran")

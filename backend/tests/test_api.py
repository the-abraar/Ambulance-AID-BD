import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import add_user, add_vehicle
from app.main import create_app


def iso(**kw):
    return (datetime.now(timezone.utc) + timedelta(**kw)).isoformat()


@pytest.fixture
def env(tmp_path):
    app = create_app(str(tmp_path / "t.db"), ping_min_interval_s=0)
    c = TestClient(app)
    # second connection to the same file just for seeding; commit makes it visible
    from app.db import connect
    db = connect(str(tmp_path / "t.db"))
    did, dt = add_user(db, "disp", "dispatcher")
    drv, vt = add_user(db, "drv1", "driver")
    drv2, vt2 = add_user(db, "drv2", "driver")
    veh = add_vehicle(db, "Op", "DHK-1")
    veh2 = add_vehicle(db, "Op", "DHK-2")
    h = lambda t: {"Authorization": f"Bearer {t}"}
    return dict(c=c, app=app, db=db, D=h(dt), V=h(vt), V2=h(vt2), drv=drv, veh=veh, veh2=veh2, path=str(tmp_path / "t.db"))


def mk(e, **kw):
    body = {"pickup_address": "Mirpur-10", "assigned_vehicle_id": e["veh"], "assigned_driver_id": e["drv"], **kw}
    r = e["c"].post("/missions", json=body, headers=e["D"])
    assert r.status_code == 201, r.text
    return r.json()["mission_id"]


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
    assert c.patch(p, json={"status": "EN_ROUTE_PICKUP"}, headers=D).status_code == 403
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
    env["db"].execute("UPDATE vehicles SET active=0 WHERE id=?", (env["veh2"],)); env["db"].commit()
    assert c.post("/missions", json={"pickup_address": "x", "assigned_vehicle_id": env["veh2"]}, headers=D).status_code == 422


def test_list_missions(env):
    c, D, V = env["c"], env["D"], env["V"]
    a, b = mk(env), mk(env)
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
    ({"lat": 23.8, "lng": 90.4, "ts": "STALE"}, 422),
    ({"lat": 23.8, "lng": 90.4, "ts": "FUTURE"}, 422),
])
def test_ping(env, body, code):
    mk(env)
    body = {**body, **({"ts": {"NOW": iso(), "STALE": iso(hours=-1), "FUTURE": iso(hours=1)}[body["ts"]]} if body.get("ts") in ("NOW", "STALE", "FUTURE") else {})}
    assert env["c"].post(f"/vehicles/{env['veh']}/pings", json=body, headers=env["V"]).status_code == code


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


def test_ping_rate_limit_and_position(env, tmp_path):
    app = create_app(env["path"], ping_min_interval_s=60)
    c = TestClient(app)
    mk(env)
    v = env["veh"]
    assert c.get(f"/vehicles/{v}/position", headers=env["D"]).status_code == 404
    assert c.post(f"/vehicles/{v}/pings", json={"lat": 1, "lng": 2, "ts": iso()}, headers=env["V"]).status_code == 201
    assert c.post(f"/vehicles/{v}/pings", json={"lat": 3, "lng": 4, "ts": iso()}, headers=env["V"]).status_code == 429
    r = c.get(f"/vehicles/{v}/position", headers=env["D"])
    assert r.status_code == 200 and (r.json()["lat"], r.json()["lng"]) == (1, 2)
    assert c.get(f"/vehicles/{v}/position", headers=env["V"]).status_code == 403


def test_stale_status_update_conflicts_without_audit(env):
    from fastapi import HTTPException
    mid = mk(env)
    assert env["c"].patch(f"/missions/{mid}/status", json={"status": "CANCELLED"}, headers=env["D"]).status_code == 200
    n = lambda: env["db"].execute("SELECT COUNT(*) FROM mission_audit WHERE mission_id=?", (mid,)).fetchone()[0]
    before = n()
    with pytest.raises(HTTPException) as ei:  # loser validated against the pre-cancel status
        env["app"].state.advance(mid, "u", "DISPATCHED", "EN_ROUTE_PICKUP")
    assert ei.value.status_code == 409
    assert n() == before
    assert env["c"].get(f"/missions/{mid}", headers=env["D"]).json()["status"] == "CANCELLED"


def test_terminal_state_not_overwritten(env):
    mid = mk(env)
    env["c"].patch(f"/missions/{mid}/status", json={"status": "CANCELLED"}, headers=env["D"])
    r = env["c"].patch(f"/missions/{mid}/status", json={"status": "EN_ROUTE_PICKUP"}, headers=env["V"])
    assert r.status_code == 409
    assert env["c"].get(f"/missions/{mid}", headers=env["D"]).json()["status"] == "CANCELLED"

import pytest

from tests.test_api import env, free, iso, mk  # noqa: F401

DISPATCHER_ONLY = [("get", "/vehicles"), ("get", "/drivers"), ("post", "/vehicles"), ("post", "/drivers"),
                   ("get", "/missions/00000000-0000-4000-8000-000000000000/audit")]
ALL = DISPATCHER_ONLY + [("get", "/me"), ("get", "/missions/current"), ("get", "/meta/transitions")]


@pytest.mark.parametrize("method,path", ALL)
def test_unauthenticated_401(env, method, path):
    assert env["c"].request(method.upper(), path, json={}).status_code == 401


@pytest.mark.parametrize("method,path", DISPATCHER_ONLY)
def test_driver_forbidden(env, method, path):
    assert env["c"].request(method.upper(), path, json={}, headers=env["V"]).status_code == 403


def test_me(env):
    c = env["c"]
    d = c.get("/me", headers=env["D"]).json()
    assert d["role"] == "dispatcher" and "driver_id" not in d and d["token_expires_at"] > "2026"
    v = c.get("/me", headers=env["V"]).json()
    assert v["role"] == "driver" and v["driver_id"] == env["drv"] and v["vehicle_id"] is None
    mk(env)
    assert c.get("/me", headers=env["V"]).json()["vehicle_id"] == env["veh"]


def test_current_mission(env):
    c = env["c"]
    assert c.get("/missions/current", headers=env["V"]).status_code == 404
    assert c.get("/missions/current", headers=env["D"]).status_code == 403
    m = mk(env)
    assert c.get("/missions/current", headers=env["V"]).json()["mission_id"] == m
    assert c.get("/missions/current", headers=env["V2"]).status_code == 404  # another driver's mission is invisible
    assert c.get(f"/missions/{m}", headers=env["V2"]).status_code == 403
    for s in ["EN_ROUTE_PICKUP", "AT_SCENE", "TRANSPORTING_PATIENT", "AT_HOSPITAL", "COMPLETED"]:
        c.patch(f"/missions/{m}/status", json={"status": s}, headers=env["V"])
    r = c.get("/missions/current", headers=env["V"])  # just ended: still shown, with its status (B15)
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED"
    assert c.get("/me", headers=env["V"]).json()["vehicle_id"] is None  # but no more pings
    env["db"].execute("UPDATE missions SET updated_at='2000-01-01T00:00:00+00:00'"); env["db"].commit()
    assert c.get("/missions/current", headers=env["V"]).status_code == 404  # ended long ago


def test_transitions_role_aware_and_match_patch(env):
    from app.state_machine import TRANSITIONS
    c = env["c"]
    drv = c.get("/meta/transitions", headers=env["V"]).json()
    dis = c.get("/meta/transitions", headers=env["D"]).json()
    assert set(drv) == set(dis) == {s.value for s in TRANSITIONS}
    assert drv["DISPATCHED"] == ["EN_ROUTE_PICKUP"] and dis["DISPATCHED"] == ["CANCELLED"]
    assert dis["TRANSPORTING_PATIENT"] == [] and drv["AT_SCENE"] == ["TRANSPORTING_PATIENT"] and drv["COMPLETED"] == []
    # every advertised edge is accepted by PATCH for that role (same rule, no drift)
    for hdr, tr in ((env["V"], drv), (env["D"], dis)):
        for src, dsts in tr.items():
            for dst in dsts:
                free(env)
                m = mk(env)
                env["db"].execute("UPDATE missions SET status=? WHERE id=?", (src, m)); env["db"].commit()
                assert c.patch(f"/missions/{m}/status", json={"status": dst}, headers=hdr).status_code == 200, (src, dst)


def test_vehicles(env):
    c = env["c"]
    r = c.post("/vehicles", json={"operator": "Op", "registration": "DHK-9"}, headers=env["D"])
    assert r.status_code == 201 and r.json()["active"] is True and r.json()["busy"] is False
    assert c.post("/vehicles", json={"operator": "Op", "registration": "DHK-9"}, headers=env["D"]).status_code == 409
    assert c.post("/vehicles", json={"operator": "", "registration": "x"}, headers=env["D"]).status_code == 422
    mk(env)
    c.post(f"/vehicles/{env['veh']}/pings", json={"lat": 1, "lng": 2, "ts": iso()}, headers=env["V"])
    by = {v["vehicle_id"]: v for v in c.get("/vehicles", headers=env["D"]).json()}
    assert len(by) == 3 and by[r.json()["vehicle_id"]]["last_position"] is None
    p = by[env["veh"]]["last_position"]
    assert (p["lat"], p["lng"], p["accuracy"], p["stale"]) == (1, 2, None, False) and p["ts"]
    assert by[env["veh"]]["busy"] is True and by[env["veh2"]]["busy"] is False


def test_drivers_token_once(env):
    c = env["c"]
    r = c.post("/drivers", json={"name": "newbie"}, headers=env["D"])
    assert r.status_code == 201
    tok = r.json()["token"]
    assert c.get("/me", headers={"Authorization": f"Bearer {tok}"}).json()["driver_id"] == r.json()["driver_id"]
    lst = c.get("/drivers", headers=env["D"]).json()
    assert r.json()["driver_id"] in [d["driver_id"] for d in lst] and all("token" not in d for d in lst)
    assert tok not in str([tuple(x) for x in env["db"].execute("SELECT * FROM users")])
    assert c.post("/drivers", json={"name": ""}, headers=env["D"]).status_code == 422


def test_audit(env):
    c = env["c"]
    m = mk(env)
    c.patch(f"/missions/{m}/status", json={"status": "EN_ROUTE_PICKUP"}, headers=env["V"])
    a = c.get(f"/missions/{m}/audit", headers=env["D"]).json()
    assert [(x["from_status"], x["to_status"]) for x in a] == [(None, "DISPATCHED"), ("DISPATCHED", "EN_ROUTE_PICKUP")]
    assert c.get("/missions/00000000-0000-4000-8000-000000000000/audit", headers=env["D"]).status_code == 404
    assert c.get("/missions/nope/audit", headers=env["D"]).status_code == 404


def test_static_mounts(env):
    # /console is served when web/dispatcher exists; /driver is tolerated if absent
    assert env["c"].get("/console/").status_code == 200


def test_pickup_coords(env):
    c = env["c"]
    r = c.post("/missions", json={"pickup_address": "x", "pickup_lat": 23.78, "pickup_lng": 90.41}, headers=env["D"])
    assert r.status_code == 201 and (r.json()["pickup_lat"], r.json()["pickup_lng"]) == (23.78, 90.41)
    assert c.get(f"/missions/{r.json()['mission_id']}", headers=env["D"]).json()["pickup_lat"] == 23.78
    assert mk(env) and c.get("/missions", headers=env["D"]).json()[0]["pickup_lat"] is None
    for bad in ({"pickup_lat": 91, "pickup_lng": 0}, {"pickup_lat": 0, "pickup_lng": -181}, {"pickup_lat": 1}):
        assert c.post("/missions", json={"pickup_address": "x", **bad}, headers=env["D"]).status_code == 422

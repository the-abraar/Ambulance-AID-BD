"""Critique 2026-10-15: free vehicles on the map (N2: on-shift pings between missions)."""
from datetime import datetime, timedelta, timezone

from app.main import IDLE_PING_S
from tests.test_api import DHAKA, env, iso, mk  # noqa: F401


def ping(e, hdr="V", veh="veh", **kw):
    return e["c"].post(f"/vehicles/{e[veh]}/pings", json={**DHAKA, "ts": iso(), **kw}, headers=e[hdr])


def pings(e, veh="veh"):
    return e["db"].execute("SELECT COUNT(*) FROM vehicle_pings WHERE vehicle_id=?", (e[veh],)).fetchone()[0]


def age_pings(e, s):
    t = (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat(timespec="microseconds")
    e["db"].execute("UPDATE vehicle_pings SET ts=?", (t,)); e["db"].commit()


def test_n2_paired_driver_on_shift_reports_a_free_vehicle(env):
    c, D = env["c"], env["D"]
    assert ping(env, on_shift=True).status_code == 403  # not paired with this vehicle: never tracked
    assert c.get("/me", headers=env["V"]).json()["paired_vehicle_id"] is None
    c.put(f"/vehicles/{env['veh']}/driver", json={"driver_id": env["drv"]}, headers=D)
    assert c.get("/me", headers=env["V"]).json()["paired_vehicle_id"] == env["veh"]
    assert ping(env).status_code == 403  # paired but off shift: the server keeps nothing
    r = ping(env, on_shift=True)
    assert r.status_code == 201 and r.json()["stored"] is True
    v = next(x for x in c.get("/vehicles", headers=D).json() if x["vehicle_id"] == env["veh"])
    assert not v["busy"] and not v["last_position"]["stale"]  # the map can now show it as a fresh free vehicle
    r = ping(env, on_shift=True, lat=DHAKA["lat"] + 0.001)
    assert r.status_code == 201 and r.json()["stored"] is False and pings(env) == 1  # thinned, not retried
    age_pings(env, IDLE_PING_S + 1)
    assert ping(env, on_shift=True).json()["stored"] is True and pings(env) == 2
    assert ping(env, hdr="V2", on_shift=True).status_code == 403  # another driver cannot report someone's vehicle


def test_n2_no_idle_pings_when_out_of_service_unpaired_or_busy(env):
    c, D = env["c"], env["D"]
    c.put(f"/vehicles/{env['veh']}/driver", json={"driver_id": env["drv"]}, headers=D)
    c.patch(f"/vehicles/{env['veh']}", json={"active": False}, headers=D)
    assert ping(env, on_shift=True).status_code == 403  # out of service
    assert c.get("/me", headers=env["V"]).json()["paired_vehicle_id"] is None
    c.patch(f"/vehicles/{env['veh']}", json={"active": True}, headers=D)
    mk(env, assigned_vehicle_id=env["veh2"], assigned_driver_id=env["drv"])  # he drives another vehicle on a mission
    assert ping(env, on_shift=True).status_code == 403  # so his paired vehicle's position would be wrong
    assert ping(env, veh="veh2", on_shift=True).status_code == 201  # the mission's vehicle is reported as before
    c.put(f"/vehicles/{env['veh']}/driver", json={"driver_id": None}, headers=D)
    assert c.get("/me", headers=env["V"]).json()["paired_vehicle_id"] is None


def test_n2_mission_pings_are_never_thinned(env):
    mk(env)
    assert [ping(env, on_shift=True).json()["stored"] for _ in range(3)] == [True] * 3
    assert pings(env) == 3

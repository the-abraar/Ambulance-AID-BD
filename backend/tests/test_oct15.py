"""Critique 2026-10-15: free vehicles on the map (N2: on-shift pings between missions) and the wrapper's shift mode."""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.main import IDLE_PING_S, TERMINAL
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


def test_wrapper_knows_the_terminal_states():
    """The Android shift poll tells an ended mission from a live one by status name; it must follow the state machine."""
    kt = Path(__file__).resolve().parents[2] / "android/app/src/main/kotlin/bd/ambulanceaid/driver/ShiftWatch.kt"
    assert set(re.findall(r'"([A-Z_]+)"', re.search(r"ENDED = setOf\(([^)]*)\)", kt.read_text())[1])) == set(TERMINAL)


def backfill(e, steps, at=-3, **kw):
    body = {"pickup_address": "Paper log 7", "assigned_vehicle_id": e["veh"], "assigned_driver_id": e["drv"],
            "dispatched_at": iso(hours=at),
            "steps": [{"status": s, "at": iso(hours=h) if h is not None else None} for s, h in steps], **kw}
    return e["c"].post("/missions", json=body, headers=e["D"])


FULL = [("EN_ROUTE_PICKUP", -2.9), ("AT_SCENE", -2.7), ("TRANSPORTING_PATIENT", None), ("AT_HOSPITAL", -2.2),
        ("COMPLETED", -2)]


def test_n6_backfill_records_a_finished_mission_on_a_busy_vehicle_without_alerting(env):
    live = mk(env)  # the vehicle and its driver are on a live job right now
    r = backfill(env, FULL)
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["status"] == "COMPLETED" and m["transporting_patient_at"] is None and m["acknowledged_at"] is None
    assert m["created_at"] < m["en_route_pickup_at"] < m["at_scene_at"] < m["at_hospital_at"] < m["completed_at"]
    assert env["c"].get("/missions/current", headers=env["V"]).json()["mission_id"] == live  # the driver never sees it
    assert [x["mission_id"] for x in env["c"].get("/missions?active=true", headers=env["D"]).json()] == [live]
    audit = env["c"].get(f"/missions/{m['mission_id']}/audit", headers=env["D"]).json()
    assert [(a["from_status"], a["to_status"]) for a in audit] == [(None, "DISPATCHED"), ("DISPATCHED", "EN_ROUTE_PICKUP"),
        ("EN_ROUTE_PICKUP", "AT_SCENE"), ("AT_SCENE", "TRANSPORTING_PATIENT"), ("TRANSPORTING_PATIENT", "AT_HOSPITAL"),
        ("AT_HOSPITAL", "COMPLETED")]
    assert all(a["reason"] == "back-fill" and a["user_id"] == env["did"] for a in audit)
    assert all(a["on_behalf_of"] == env["drv"] for a in audit[1:]) and audit[-1]["event_time"] == m["completed_at"]
    cancelled = backfill(env, [("EN_ROUTE_PICKUP", None), ("CANCELLED", -2.5)]).json()
    audit = env["c"].get(f"/missions/{cancelled['mission_id']}/audit", headers=env["D"]).json()
    assert cancelled["status"] == "CANCELLED" and audit[-1]["on_behalf_of"] is None  # the dispatcher's own move


def test_n6_backfill_refuses_impossible_timelines(env):
    assert backfill(env, FULL, at=-24 * 8).status_code == 422  # outside the 7-day window
    assert backfill(env, [("EN_ROUTE_PICKUP", -3.5), ("CANCELLED", -2)]).status_code == 422  # before the dispatch
    assert backfill(env, [("EN_ROUTE_PICKUP", -2), ("AT_SCENE", -2.5), ("CANCELLED", -1)]).status_code == 422  # backwards
    assert backfill(env, [("CANCELLED", 1)]).status_code == 422  # in the future
    assert backfill(env, [("AT_SCENE", -2), ("CANCELLED", -1)]).status_code == 422  # skips a step
    assert backfill(env, [("EN_ROUTE_PICKUP", -2)]).status_code == 422  # not over
    assert backfill(env, [("EN_ROUTE_PICKUP", -2), ("CANCELLED", None)]).status_code == 422  # no end time
    r = env["c"].post("/missions", json={"pickup_address": "x", "assigned_vehicle_id": env["veh"], "dispatched_at": iso()},
                      headers=env["D"])
    assert r.status_code == 422  # a back-fill without its steps would be a live dispatch with an old time
    assert env["c"].get("/missions", headers=env["D"]).json() == []

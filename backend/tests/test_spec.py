from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from tests.test_api import env, mk  # noqa: F401

SPEC = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs/api-spec/openapi.yaml").read_text())


def check(name, body):
    v = Draft202012Validator({"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]},
                             format_checker=FormatChecker())
    errs = list(v.iter_errors(body))
    assert not errs, errs


def test_responses_match_spec(env):  # noqa: F811
    c = env["c"]
    m = mk(env)
    check("Mission", c.get(f"/missions/{m}", headers=env["D"]).json())
    check("Mission", c.patch(f"/missions/{m}/status", json={"status": "EN_ROUTE_PICKUP"}, headers=env["V"]).json())
    for x in c.get("/missions", headers=env["D"]).json():
        check("Mission", x)
    bare = c.post("/missions", json={"pickup_address": "x"}, headers=env["D"])
    check("Mission", bare.json())  # null vehicle/driver must be allowed
    assert bare.json()["pickup_lat"] is None
    withc = c.post("/missions", json={"pickup_address": "x", "pickup_lat": 1.5, "pickup_lng": 2.5}, headers=env["D"])
    check("Mission", withc.json())
    check("MissionCreateRequest", {"pickup_address": "x", "pickup_lat": 1.5, "pickup_lng": 2.5})
    with pytest.raises(AssertionError):
        check("MissionCreateRequest", {"pickup_address": "x", "pickup_lat": 100, "pickup_lng": 2.5})
    from tests.test_api import iso
    check("PingRequest", {"lat": 1, "lng": 2, "ts": iso(), "sent_at": iso(), "accuracy": 12.5})
    check("PingResult", c.post(f"/vehicles/{env['veh']}/pings", json={"lat": 1, "lng": 2, "ts": iso(), "accuracy": 8},
                               headers=env["V"]).json())
    check("VehiclePosition", c.get(f"/vehicles/{env['veh']}/position", headers=env["D"]).json())
    check("Mission", c.post(f"/missions/{m}/ack", headers=env["V"]).json())
    check("MissionStatusUpdate", {"status": "AT_SCENE", "reason": "driver phone dead", "event_time": iso()})
    with pytest.raises(AssertionError):
        check("MissionStatusUpdate", {"status": "AT_SCENE", "notes": "x"})
    check("Mission", c.patch(f"/missions/{m}/status", json={"status": "AT_SCENE", "reason": "radio call"},
                             headers=env["D"]).json())
    check("Transitions", c.get("/meta/transitions?on_behalf=true", headers=env["D"]).json())
    check("VehicleSummary", c.put(f"/vehicles/{env['veh2']}/driver", json={"driver_id": env["drv2"]}, headers=env["D"]).json())
    check("VehicleSummary", c.patch(f"/vehicles/{env['veh2']}", json={"active": True}, headers=env["D"]).json())
    check("DriverSummary", c.patch(f"/drivers/{env['drv2']}", json={"phone": "01711234567"}, headers=env["D"]).json())
    code = c.post(f"/drivers/{env['drv2']}/pairing-code", headers=env["D"]).json()
    check("PairingCode", code)
    check("PairResult", c.post("/pair", json={"code": code["code"]}).json())
    check("UserCreated", c.post("/users", json={"name": "d2"}, headers=env["D"]).json())
    for x in c.get("/users", headers=env["D"]).json():
        check("UserSummary", x)
    check("TokenRotated", c.post("/me/token/rotate", headers=env["P"]).json())
    check("Health", c.get("/healthz").json())
    for v in c.get("/vehicles", headers=env["D"]).json():
        check("VehicleSummary", v)
    check("VehicleSummary", c.post("/vehicles", json={"operator": "o", "registration": "R-1"}, headers=env["D"]).json())
    for d in c.get("/drivers", headers=env["D"]).json():
        check("DriverSummary", d)
    check("DriverCreated", c.post("/drivers", json={"name": "n"}, headers=env["D"]).json())
    check("DriverCreated", c.post("/drivers", json={"name": "p", "phone": "+8801911234567"}, headers=env["D"]).json())
    check("Mission", c.get("/missions/current", headers=env["V"]).json())
    check("Me", c.get("/me", headers=env["D"]).json())
    check("Me", c.get("/me", headers=env["V"]).json())
    for a in c.get(f"/missions/{m}/audit", headers=env["D"]).json():
        check("AuditEntry", a)
    check("Transitions", c.get("/meta/transitions", headers=env["D"]).json())
    # the schema must actually bite
    with pytest.raises(AssertionError):
        check("Mission", {"id": m, "status": "DISPATCHED"})


def test_token_endpoints_in_spec():
    for path in ("/me/token/rotate", "/drivers/{driverId}/token/rotate", "/drivers/{driverId}/token/revoke"):
        assert "post" in SPEC["paths"][path]


def test_every_route_in_spec_and_back(env):  # noqa: F811
    import re
    from fastapi.routing import APIRoute
    norm = lambda p: re.sub(r"\{[^}]+\}", "{}", p)  # path parameter names differ ({mid} vs {missionId})
    app_ops = {(norm(r.path), m.lower()) for r in env["app"].routes if isinstance(r, APIRoute) for m in r.methods}
    spec_ops = {(norm(p), m) for p, ops in SPEC["paths"].items() for m in ops if m in ("get", "post", "put", "patch", "delete")}
    assert app_ops == spec_ops

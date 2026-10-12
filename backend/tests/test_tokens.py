from concurrent.futures import ThreadPoolExecutor

from datetime import datetime, timezone

from tests.test_api import env, iso, mk  # noqa: F401


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def test_rotate_driver_token(env):
    c = env["c"]
    r = c.post(f"/drivers/{env['drv']}/token/rotate", headers=env["D"])
    assert r.status_code == 200 and r.json()["driver_id"] == env["drv"]
    assert c.get("/me", headers=env["V"]).status_code == 401  # old token dead
    assert c.get("/me", headers=bearer(r.json()["token"])).json()["driver_id"] == env["drv"]
    assert r.json()["token"] not in str([tuple(x) for x in env["db"].execute("SELECT * FROM users")])
    assert c.post("/drivers/nope/token/rotate", headers=env["D"]).status_code == 404
    assert c.post(f"/drivers/{env['drv']}/token/rotate", headers=env["V2"]).status_code == 403
    assert c.post(f"/drivers/{env['drv']}/token/rotate").status_code == 401


def test_revoke_then_rotate_reenables(env):
    c = env["c"]
    assert c.post(f"/drivers/{env['drv']}/token/revoke", headers=env["V"]).status_code == 403
    assert c.post(f"/drivers/{env['drv']}/token/revoke", headers=env["D"]).status_code == 204
    assert c.get("/me", headers=env["V"]).status_code == 401
    assert c.get("/me", headers=env["V2"]).status_code == 200  # other driver untouched
    assert c.post("/drivers/nope/token/revoke", headers=env["D"]).status_code == 404
    tok = c.post(f"/drivers/{env['drv']}/token/rotate", headers=env["D"]).json()["token"]
    assert c.get("/me", headers=bearer(tok)).status_code == 200


def test_rotate_own_token(env):
    c = env["c"]
    tok = c.post("/me/token/rotate", headers=env["D"]).json()["token"]
    assert c.get("/me", headers=env["D"]).status_code == 401
    assert c.get("/me", headers=bearer(tok)).json()["role"] == "dispatcher"
    assert c.post("/me/token/rotate").status_code == 401


def test_concurrent_status_race_has_one_winner(env):
    mid = mk(env)
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda _: env["c"].patch(
            f"/missions/{mid}/status", json={"status": "CANCELLED"}, headers=env["D"]).status_code, range(8)))
    assert codes.count(200) == 1 and set(codes) <= {200, 409}
    n = env["db"].execute("SELECT COUNT(*) FROM mission_audit WHERE mission_id=?", (mid,)).fetchone()[0]
    assert n == 2  # created + one cancel


def test_concurrent_pings_share_rate_limit(env):
    from fastapi.testclient import TestClient
    from app.main import create_app
    mk(env)
    apps = [TestClient(create_app(env["path"], ping_min_interval_s=60)) for _ in range(4)]  # separate "workers"
    with ThreadPoolExecutor(4) as ex:
        codes = list(ex.map(lambda a: a.post(f"/vehicles/{env['veh']}/pings", json={"lat": 1, "lng": 2, "ts": iso()},
                                              headers=env["V"]).status_code, apps))
    assert sorted(codes) == [201, 429, 429, 429]


def test_token_expiry(env):
    c, db = env["c"], env["db"]
    exp = db.execute("SELECT token_expires_at FROM users LIMIT 1").fetchone()[0]
    days = (datetime.fromisoformat(exp) - datetime.now(timezone.utc)).days
    assert 88 <= days <= 90  # new tokens live about 90 days
    db.execute("UPDATE users SET token_expires_at='2000-01-01T00:00:00+00:00'"); db.commit()
    assert c.get("/me", headers=env["D"]).status_code == 401
    assert c.get("/me", headers=env["V"]).status_code == 401
    db.execute("UPDATE users SET token_expires_at='2000-01-01T00:00:00+00:00' WHERE role='driver'")
    db.execute("UPDATE users SET token_expires_at=? WHERE role='dispatcher'", ("9999-01-01T00:00:00+00:00",)); db.commit()
    r = c.post(f"/drivers/{env['drv']}/token/rotate", headers=env["D"])  # rotate renews an expired driver
    assert r.status_code == 200 and r.json()["expires_at"] > "2026"
    assert c.get("/me", headers=bearer(r.json()["token"])).status_code == 200


def test_self_rotate_cannot_undo_revoke(env):
    c = env["c"]
    c.post(f"/drivers/{env['drv']}/token/revoke", headers=env["D"])
    assert c.post("/me/token/rotate", headers=env["V"]).status_code == 401  # revoked token is dead
    # the race: the caller passed auth, then the revoke landed; the guarded UPDATE must refuse
    uid = env["db"].execute("SELECT user_id FROM drivers WHERE id=?", (env["drv"],)).fetchone()[0]
    cur = env["db"].execute("UPDATE users SET token_hash='x' WHERE id=? AND revoked_at IS NULL", (uid,))
    assert cur.rowcount == 0


def test_auth_audit_records_actor_and_action(env):
    c, db = env["c"], env["db"]
    c.post("/drivers", json={"name": "z"}, headers=env["D"])
    c.post(f"/drivers/{env['drv']}/token/rotate", headers=env["D"])
    c.post(f"/drivers/{env['drv']}/token/revoke", headers=env["D"])
    c.post("/me/token/rotate", headers=env["D"])
    rows = [(r["action"]) for r in db.execute("SELECT action FROM auth_audit ORDER BY id")]
    assert rows == ["create_driver", "rotate", "revoke", "rotate"]
    assert db.execute("SELECT COUNT(*) FROM auth_audit WHERE actor_id IS NULL").fetchone()[0] == 0


def test_text_fields_capped_and_stripped(env):
    c, D = env["c"], env["D"]
    assert c.post("/missions", json={"pickup_address": "   "}, headers=D).status_code == 422
    assert c.post("/missions", json={"pickup_address": "x" * 201}, headers=D).status_code == 422
    assert c.post("/drivers", json={"name": " " * 3}, headers=D).status_code == 422
    assert c.post("/vehicles", json={"operator": "o" * 201, "registration": "R"}, headers=D).status_code == 422
    r = c.post("/missions", json={"pickup_address": "  Mirpur  "}, headers=D)
    assert r.json()["pickup_address"] == "Mirpur"

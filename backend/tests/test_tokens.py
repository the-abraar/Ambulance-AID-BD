from concurrent.futures import ThreadPoolExecutor

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import PAIR_CLIENT_FAILS, PAIR_CODE_TTL, PAIR_CODE_FAILS, PAIR_WINDOW_S
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


def test_s2_admin_split(env):
    c, P, D = env["c"], env["P"], env["D"]
    assert c.get("/me", headers=P).json()["admin"] is False and c.get("/me", headers=D).json()["admin"] is True
    for method, path in (("post", "/drivers"), ("post", f"/drivers/{env['drv']}/token/rotate"),
                         ("post", f"/drivers/{env['drv']}/token/revoke"), ("post", f"/drivers/{env['drv']}/pairing-code"),
                         ("get", "/users"), ("post", "/users"), ("post", f"/users/{env['did']}/token/revoke")):
        r = c.request(method.upper(), path, json={"name": "x"}, headers=P)
        assert r.status_code == 403 and r.json()["detail"] == "admin only", path
    # a plain dispatcher still dispatches
    assert c.post("/missions", json={"pickup_address": "x"}, headers=P).status_code == 201
    assert c.get("/drivers", headers=P).status_code == 200 and c.get("/vehicles", headers=P).status_code == 200
    r = c.post("/users", json={"name": "night shift"}, headers=D)
    assert r.status_code == 201 and r.json()["admin"] is False and r.json()["role"] == "dispatcher"
    assert c.get("/me", headers=bearer(r.json()["token"])).json()["admin"] is False
    assert {u["name"] for u in c.get("/users", headers=D).json()} >= {"disp", "plain", "drv1", "night shift"}


def test_b6_admin_revokes_any_user(env):
    c, D, P = env["c"], env["D"], env["P"]
    assert c.post(f"/users/{env['pid']}/token/revoke", headers=D).status_code == 204
    assert c.get("/me", headers=P).status_code == 401
    assert c.post("/me/token/rotate", headers=P).status_code == 401  # the thief cannot rotate his way back
    assert c.post("/users/nope/token/revoke", headers=D).status_code == 404
    assert c.post(f"/users/{env['did']}/token/revoke", headers=env["V"]).status_code == 403
    by = {u["user_id"]: u for u in c.get("/users", headers=D).json()}
    assert by[env["pid"]]["revoked"] is True and by[env["did"]]["revoked"] is False


def test_b6_cli_revoke(env):
    import os
    import subprocess
    import sys
    from pathlib import Path
    run = lambda *a: subprocess.run([sys.executable, "-m", "app.bootstrap", *a], cwd=Path(__file__).resolve().parents[1],
                                    env={**os.environ, "AMBULANCE_DB_PATH": env["path"]}, capture_output=True, text=True)
    assert run("revoke", env["did"]).returncode == 0
    assert env["c"].get("/me", headers=env["D"]).status_code == 401  # even an admin
    row = env["db"].execute("SELECT actor_id, action FROM auth_audit ORDER BY id DESC").fetchone()
    assert (row["actor_id"], row["action"]) == ("cli", "revoke")
    assert run("revoke", "nope").returncode != 0
    out = run("admin", "rescue")
    assert out.returncode == 0
    tok = out.stdout.split("token=")[1].strip()
    assert env["c"].get("/me", headers=bearer(tok)).json()["admin"] is True


def test_b8_sliding_expiry(env):
    c, db = env["c"], env["db"]
    exp = lambda: db.execute("SELECT token_expires_at FROM users WHERE name='drv1'").fetchone()[0]
    db.execute("UPDATE users SET token_expires_at=? WHERE name='drv1'", ("2099-01-01T00:00:00+00:00",)); db.commit()
    c.get("/me", headers=env["V"])
    assert exp() == "2099-01-01T00:00:00+00:00"  # far from due: no write
    from app.db import token_expiry
    db.execute("UPDATE users SET token_expires_at=? WHERE name='drv1'", (token_expiry(10),)); db.commit()
    assert c.get("/me", headers=env["V"]).json()["token_expires_at"] > token_expiry(89)
    assert exp() > token_expiry(89)
    db.execute("UPDATE users SET token_expires_at=? WHERE name='drv1'", (token_expiry(89.5),)); db.commit()
    before = exp()
    c.get("/me", headers=env["V"])
    assert exp() == before  # extended less than a day ago: no write


def test_pairing_code_flow(env):
    c, D, db = env["c"], env["D"], env["db"]
    r = c.post(f"/drivers/{env['drv']}/pairing-code", headers=D)
    assert r.status_code == 200
    code = r.json()["code"]
    assert len(code) == 6 and code.isdigit() and r.json()["expires_at"] < iso(minutes=11)
    assert code not in str([tuple(x) for x in db.execute("SELECT * FROM pairing_codes")])  # stored hashed
    bn = code.translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))
    p = c.post("/pair", json={"code": bn})  # typed on a Bangla keyboard
    assert p.status_code == 200, p.text
    assert p.json()["user"]["driver_id"] == env["drv"] and p.json()["user"]["role"] == "driver"
    assert c.get("/me", headers=bearer(p.json()["token"])).json()["driver_id"] == env["drv"]
    assert c.get("/me", headers=env["V"]).status_code == 401  # old token rotated away
    assert c.post("/pair", json={"code": code}).status_code == 401  # single use
    assert c.post("/pair", json={"code": "12345"}).status_code == 422
    assert c.post("/drivers/nope/pairing-code", headers=D).status_code == 404
    actions = [r["action"] for r in db.execute("SELECT action FROM auth_audit ORDER BY id")]
    assert actions[-2:] == ["pairing_code", "pair"]


def test_pairing_code_expires_and_revoke_kills_it(env):
    c, D, db = env["c"], env["D"], env["db"]
    code = c.post(f"/drivers/{env['drv']}/pairing-code", headers=D).json()["code"]
    db.execute("UPDATE pairing_codes SET expires_at='2000-01-01T00:00:00+00:00'"); db.commit()
    assert c.post("/pair", json={"code": code}).status_code == 401
    code = c.post(f"/drivers/{env['drv']}/pairing-code", headers=D).json()["code"]
    c.post(f"/drivers/{env['drv']}/token/revoke", headers=D)
    assert c.post("/pair", json={"code": code}).status_code == 401
    code = c.post(f"/drivers/{env['drv']}/pairing-code", headers=D).json()["code"]  # re-issuing re-enables on pairing
    assert c.post("/pair", json={"code": code}).status_code == 200


def phone(env, ip):
    """A client at its own IP address (the per-client limit keys on it)."""
    return TestClient(env["app"], client=(ip, 50000))


def code_for(env, did):
    return env["c"].post(f"/drivers/{did}/pairing-code", headers=env["D"]).json()["code"]


def wrong_codes(n, *live):
    return [c for c in (f"{i:06d}" for i in range(n + len(live))) if c not in live][:n]


def test_n4_wrong_codes_never_kill_other_drivers_codes(env):
    a, b = code_for(env, env["drv"]), code_for(env, env["drv2"])
    bad = phone(env, "198.51.100.7")
    tries = [bad.post("/pair", json={"code": w}).status_code for w in wrong_codes(PAIR_CLIENT_FAILS + 1, a, b)]
    assert tries == [401] * PAIR_CLIENT_FAILS + [429]  # that client is blocked for a while ...
    assert bad.post("/pair", json={"code": a}).status_code == 429  # ... even with a good code
    assert phone(env, "203.0.113.9").post("/pair", json={"code": a}).status_code == 200  # everyone else's codes live on
    assert phone(env, "203.0.113.10").post("/pair", json={"code": b}).status_code == 200


def test_n4_one_office_ip_survives_onboarding_day_typos(env):
    office = phone(env, "203.0.113.5")
    for i in range(15):  # 15 drivers on the office Wi-Fi; each mistypes once, then gets it right
        did = env["c"].post("/drivers", json={"name": f"d{i}"}, headers=env["D"]).json()["driver_id"]
        code = code_for(env, did)
        assert office.post("/pair", json={"code": wrong_codes(1, code)[0]}).status_code == 401
        assert office.post("/pair", json={"code": code}).status_code == 200, i
    code = code_for(env, env["drv"])  # a success clears the office's count: 19 typos in a row still leave a try
    assert [office.post("/pair", json={"code": w}).status_code for w in wrong_codes(19, code)] == [401] * 19
    assert office.post("/pair", json={"code": code}).status_code == 200


def test_n4_per_code_cap_keeps_guessing_infeasible(env):
    code, other = code_for(env, env["drv"]), code_for(env, env["drv2"])
    for i, w in enumerate(wrong_codes(PAIR_CODE_FAILS, code, other)):  # a distributed guesser: one try per address
        assert phone(env, f"192.0.2.{i}").post("/pair", json={"code": w}).status_code == 401
    # Both live codes took PAIR_CODE_FAILS wrong guesses and are dead, even when right; pairing itself is not paused.
    assert phone(env, "192.0.2.250").post("/pair", json={"code": code}).status_code == 401
    assert phone(env, "192.0.2.250").post("/pair", json={"code": other}).status_code == 401
    fresh = code_for(env, env["drv"])
    assert phone(env, "192.0.2.251").post("/pair", json={"code": fresh}).status_code == 200  # a new code works at once
    # One short of the cap leaves a code alive.
    c3 = code_for(env, env["drv2"])
    for i, w in enumerate(wrong_codes(PAIR_CODE_FAILS - 1, c3)):
        phone(env, f"198.18.0.{i}").post("/pair", json={"code": w})
    assert phone(env, "198.18.1.1").post("/pair", json={"code": c3}).status_code == 200
    # The numbers: a code lives no longer than one window and takes at most PAIR_CODE_FAILS guesses.
    assert PAIR_CODE_TTL.total_seconds() <= PAIR_WINDOW_S
    assert PAIR_CODE_FAILS / 10 ** 6 <= 1 / 20_000  # chance that a guesser takes over a given code
    assert PAIR_CLIENT_FAILS >= 15  # an onboarding room gets more typos than it has drivers


def test_auth_audit_view_is_admin_only_and_read_only(env):
    c, D = env["c"], env["D"]
    for hdr in (env["P"], env["V"]):  # plain dispatcher, driver
        assert c.get("/auth-audit", headers=hdr).status_code == 403
    assert c.get("/auth-audit").status_code == 401
    code_for(env, env["drv"])
    c.patch(f"/drivers/{env['drv']}", json={"phone": "01811234567"}, headers=D)
    rows = c.get("/auth-audit", headers=D).json()
    assert [r["action"] for r in rows[:2]] == ["update_phone:none->018****567", "pairing_code"]  # newest first
    assert rows[0]["actor_name"] == "disp" and rows[0]["target_name"] == "drv1"
    assert len(c.get("/auth-audit?limit=1&offset=1", headers=D).json()) == 1
    assert c.get("/auth-audit?limit=501", headers=D).status_code == 422
    assert c.post("/auth-audit", headers=D).status_code == 405 and c.delete("/auth-audit", headers=D).status_code == 405

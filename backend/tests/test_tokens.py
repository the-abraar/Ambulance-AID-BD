from concurrent.futures import ThreadPoolExecutor

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import PAIR_CLIENT_FAILS, PAIR_CODE_TTL, PAIR_CODE_FAILS, PAIR_TYPED_FAILS, PAIR_WINDOW_S
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


def test_sign_out_ends_the_token_on_the_server(env):
    c, db = env["c"], env["db"]
    mk(env)
    assert c.get("/missions/current", headers=env["V"]).status_code == 200
    assert c.post("/me/token/revoke").status_code == 401
    assert c.post("/me/token/revoke", headers=env["V"]).status_code == 204
    ping = {"lat": 23.81, "lng": 90.41, "ts": iso()}
    assert c.get("/me", headers=env["V"]).status_code == 401
    assert c.post(f"/vehicles/{env['veh']}/pings", json=ping, headers=env["V"]).status_code == 401
    assert c.get("/missions/current", headers=env["V"]).status_code == 401
    assert c.post("/me/token/revoke", headers=env["V"]).status_code == 401  # already over
    assert c.get("/me", headers=env["V2"]).status_code == 200  # nobody else is touched
    row = db.execute("SELECT actor_id, target_user_id, action FROM auth_audit ORDER BY id DESC LIMIT 1").fetchone()
    uid = db.execute("SELECT user_id FROM drivers WHERE id=?", (env["drv"],)).fetchone()[0]
    assert tuple(row) == (uid, uid, "signout")
    # a dispatcher's sign-out ends that token too; a pairing code brings a driver back
    assert c.post("/me/token/revoke", headers=env["P"]).status_code == 204
    assert c.get("/me", headers=env["P"]).status_code == 401
    code = c.post(f"/drivers/{env['drv']}/pairing-code", headers=env["D"]).json()["code"]
    assert c.post("/pair", json={"driver_id": env["drv"], "code": code}).status_code == 200


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
    code = c.post(f"/drivers/{env['drv']}/pairing-code", headers=D).json()["code"]  # the QR link names the driver
    assert c.post("/pair", json={"driver_id": env["drv2"], "code": code}).status_code == 401  # someone else's code
    assert c.post("/pair", json={"driver_id": env["drv"], "code": code}).json()["user"]["driver_id"] == env["drv"]
    assert c.post("/pair", json={"code": "12345"}).status_code == 422
    assert c.post("/drivers/nope/pairing-code", headers=D).status_code == 404
    actions = [r["action"] for r in db.execute("SELECT action FROM auth_audit ORDER BY id")]
    assert actions[-4:] == ["pairing_code", "pair", "pairing_code", "pair"]


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


def pair_as(env, ip, did, code):
    return phone(env, ip).post("/pair", json={"driver_id": did, "code": code}).status_code


def test_n4_guesses_at_one_driver_never_touch_another_drivers_code(env):
    a, b = code_for(env, env["drv"]), code_for(env, env["drv2"])
    for i, w in enumerate(wrong_codes(PAIR_CODE_FAILS, a, b)):  # a guesser at driver A's code from 3 addresses
        assert pair_as(env, f"192.0.2.{i % 3}", env["drv"], w) == 401
    assert pair_as(env, "192.0.2.250", env["drv"], a) == 401  # A's code took PAIR_CODE_FAILS wrong guesses: dead
    assert pair_as(env, "192.0.2.250", env["drv2"], b) == 200  # B's code lives on
    assert pair_as(env, "192.0.2.251", env["drv"], code_for(env, env["drv"])) == 200  # a new code for A works at once
    # One short of the cap leaves a code alive; an unknown driver id is just a wrong guess.
    c3 = code_for(env, env["drv2"])
    for i, w in enumerate(wrong_codes(PAIR_CODE_FAILS - 1, c3)):
        pair_as(env, f"198.18.0.{i}", env["drv2"], w)
    assert pair_as(env, "198.18.1.2", "no-such-driver", c3) == 401
    assert pair_as(env, "198.18.1.1", env["drv2"], c3) == 200
    assert phone(env, "198.18.1.3").post("/pair", json={"driver_id": "x" * 65, "code": c3}).status_code == 422


def test_n4_typed_codes_share_a_budget_and_never_burn_codes(env):
    a, b = code_for(env, env["drv"]), code_for(env, env["drv2"])
    for i, w in enumerate(wrong_codes(PAIR_TYPED_FAILS, a, b)):  # typed guesses (no driver id), one per address
        assert phone(env, f"192.0.2.{i}").post("/pair", json={"code": w}).status_code == 401
    # Typing pauses for everyone until the window passes; the codes stay alive and the QR link still pairs.
    assert phone(env, "192.0.2.250").post("/pair", json={"code": a}).status_code == 429
    assert env["db"].execute("SELECT MAX(failures) FROM pairing_codes").fetchone()[0] == 0
    assert pair_as(env, "192.0.2.251", env["drv"], a) == 200
    assert pair_as(env, "192.0.2.252", env["drv2"], b) == 200
    # The numbers: a code lives no longer than one window, and each way in takes at most 50 guesses at it.
    assert PAIR_CODE_TTL.total_seconds() <= PAIR_WINDOW_S
    assert max(PAIR_CODE_FAILS, PAIR_TYPED_FAILS) / 10 ** 6 <= 1 / 20_000
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


def test_vehicle_pairing_and_service_changes_are_audited(env):
    c, D, P, veh = env["c"], env["D"], env["P"], env["veh"]
    assert c.put(f"/vehicles/{veh}/driver", json={"driver_id": env["drv"]}, headers=P).status_code == 200
    assert c.put(f"/vehicles/{veh}/driver", json={"driver_id": None}, headers=P).status_code == 200
    assert c.patch(f"/vehicles/{veh}", json={"active": False}, headers=P).status_code == 200
    assert c.patch("/vehicles/nope", json={"active": True}, headers=P).status_code == 404  # no row for a failed change
    assert c.put("/vehicles/nope/driver", json={"driver_id": None}, headers=P).status_code == 404
    rows = c.get("/auth-audit", headers=D).json()[:3]
    assert [r["action"] for r in rows] == ["vehicle_active:false", f"pair_vehicle:{veh}:none", f"pair_vehicle:{veh}"]
    assert all(r["actor_name"] == "plain" for r in rows)
    assert rows[2]["target_name"] == "drv1" and rows[0]["target_user_id"] == veh


def test_user_creation_has_a_daily_cap(env):
    from app.main import USER_CREATES_PER_DAY
    c, D = env["c"], env["D"]
    toks = []
    for i in range(USER_CREATES_PER_DAY):
        r = c.post("/users", json={"name": f"u{i}", "admin": i == 0}, headers=D)
        assert r.status_code == 201
        toks.append(r.json()["token"])
    assert c.post("/users", json={"name": "x"}, headers=D).status_code == 429
    new_admin = {"Authorization": f"Bearer {toks[0]}"}  # a freshly minted admin shares the same cap
    assert c.post("/users", json={"name": "x"}, headers=new_admin).status_code == 429

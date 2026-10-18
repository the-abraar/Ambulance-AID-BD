import asyncio
import logging
import math
import os
import re
import secrets
import time
from contextlib import asynccontextmanager, closing
import uuid
from datetime import date, datetime, timedelta, timezone

from pathlib import Path

import csv
import io

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from . import sms
from .bootstrap import add_user, add_vehicle, auth_audit, revoke_user
from .db import (TOKEN_TTL_DAYS, Conn, IntegrityError, close_pools, db_target, hash_token, migrate, now, open_db,
                 token_expiry)
from .state_machine import INITIAL, TRANSITIONS, InvalidTransition, State, on_behalf, required_role, transition

MAX_BODY = 64 * 1024  # keep equal to request_body max_size in Caddyfile
PING_LIMIT_KEEP_S = 86400
PRUNE_EVERY_S = 86400  # besides the prune at startup, so a server that runs for months keeps these tables small
TERMINAL = [s.value for s in State if not TRANSITIONS[s]]
ACTIVE_SQL = f"status NOT IN ({','.join('?' * len(TERMINAL))})"  # bind *TERMINAL after it
STALE_S = 120  # a position older than this is shown as stale (same as the console's STALE_MS)
IDLE_PING_S = 30  # between missions a vehicle keeps at most one position per 30 s (the wrapper sends one a minute)
RECENT_TERMINAL_S = 600  # /missions/current keeps showing a just-ended mission this long, so the driver sees why
BACKFILL_WINDOW = timedelta(days=7)  # how far back a paper-log back-fill or an on-behalf event_time may go
PAIR_CODE_TTL = timedelta(minutes=10)
# Wrong /pair codes in a sliding 10-minute window. Per client, so one room's typos never block another (and a success
# clears that client's count); globally, so at most 50 guesses fall in a code's 10-minute life: 1 in 20,000 for a
# 6-digit code. A wrong code never kills anyone's live code.
PAIR_WINDOW_S, PAIR_CLIENT_FAILS, PAIR_GLOBAL_FAILS = 600, 20, 50
MAX_SPEED_MPS = 70  # 250 km/h: faster than any ambulance on Bangladesh roads
JUMP_SLACK_M = 1000  # GPS and cell-fix noise on top of the reported accuracies
JUMP_WINDOW_S = 600  # only compare with a recent fix, so one bad accepted fix cannot block real ones for long
BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
ANDROID_PACKAGE = "bd.ambulanceaid.driver"  # android/app/build.gradle.kts applicationId


def bd_phone(v: str) -> str:
    """Bangladesh mobile number to +8801XXXXXXXXX; accepts 01..., 8801..., +8801..., Bangla digits, spaces, hyphens."""
    m = re.fullmatch(r"(?:\+?88)?(01[3-9]\d{8})", re.sub(r"[\s-]", "", v.translate(BN_DIGITS)))
    if not m:
        raise ValueError("phone must be a Bangladesh mobile number: 01XXXXXXXXX or +8801XXXXXXXXX")
    return "+88" + m[1]


def pair_code(v: str) -> str:
    v = v.strip().translate(BN_DIGITS)
    if not re.fullmatch(r"\d{6}", v):
        raise ValueError("code must be 6 digits")
    return v


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 12_742_000 * math.asin(math.sqrt(a))  # haversine, Earth diameter in metres


class BodyCap:
    """413 for a body over MAX_BODY: by Content-Length up front, and by counting while it is read (chunked bodies)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if int(Headers(scope=scope).get("content-length") or 0) > MAX_BODY:
            return await JSONResponse({"detail": "request body too large"}, status_code=413)(scope, receive, send)
        seen = 0

        async def capped():
            nonlocal seen
            msg = await receive()
            seen += len(msg.get("body", b""))
            if seen > MAX_BODY:  # raised inside the route's body read; FastAPI re-raises HTTPException as the response
                raise HTTPException(413, "request body too large")
            return msg

        await self.app(scope, capped, send)


def create_app(db_path: str | None = None, ping_max_age_s: float = 300, ping_min_interval_s: float = 1.0,
               create_per_min: int = 30) -> FastAPI:
    path = db_path or db_target()
    retention_days = int(os.environ.get("AMBULANCE_PING_RETENTION_DAYS", "90"))
    if retention_days < 1:
        raise RuntimeError("AMBULANCE_PING_RETENTION_DAYS must be at least 1")
    dev = os.environ.get("AMBULANCE_DEV") == "1"
    # The Android app's signing-key SHA-256 (comma-separated), so the console's pairing QR opens the app (App Link).
    android_certs = [c.strip().upper() for c in os.environ.get("AMBULANCE_ANDROID_CERT_SHA256", "").split(",") if c.strip()]
    if not all(re.fullmatch(r"([0-9A-F]{2}:){31}[0-9A-F]{2}", c) for c in android_certs):
        raise RuntimeError("AMBULANCE_ANDROID_CERT_SHA256 must be colon-separated SHA-256 fingerprints (AB:CD:...)")

    def prune():
        with closing(open_db(path)) as db:
            db.execute("DELETE FROM ping_limit WHERE last_at<?", (time.time() - PING_LIMIT_KEEP_S,))
            db.execute("DELETE FROM rate_events WHERE at<?", (time.time() - PING_LIMIT_KEEP_S,))
            db.execute("DELETE FROM pairing_codes WHERE expires_at<?", (now(),))
            db.execute("DELETE FROM vehicle_pings WHERE ts<?", (now(timedelta(days=-retention_days)),))
            db.commit()

    @asynccontextmanager
    async def lifespan(_):
        async def daily():
            while True:
                await asyncio.sleep(PRUNE_EVERY_S)
                try:
                    await asyncio.to_thread(prune)
                except Exception:  # a DB blip must not stop tomorrow's prune
                    logging.exception("daily prune failed")
        task = asyncio.create_task(daily())
        yield
        task.cancel()
        close_pools()

    # The interactive docs map the whole API, so they exist only in dev.
    app = FastAPI(title="Ambulance-AID MVP", lifespan=lifespan,
                  **({} if dev else {"docs_url": None, "redoc_url": None, "openapi_url": None}))
    migrate(path)
    prune()

    app.add_middleware(BodyCap)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, exc: RequestValidationError):
        # Never echo the input back: NaN is not JSON-encodable (it was a 500), and input does not belong in responses.
        return JSONResponse({"detail": [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]},
                            status_code=422)

    def get_db():
        # One connection per request; anything left uncommitted is rolled back.
        db = open_db(path)
        try:
            yield db
        finally:
            try:
                db.rollback()
            finally:
                db.close()  # always return the connection, even if the rollback fails

    def user(authorization: str | None = Header(None), db: Conn = Depends(get_db)) -> dict:
        if authorization and authorization.startswith("Bearer "):
            row = db.execute(
                "SELECT u.id, u.role, u.admin, u.token_expires_at, d.id AS driver_id FROM users u "
                "LEFT JOIN drivers d ON d.user_id=u.id "
                "WHERE u.token_hash=? AND u.revoked_at IS NULL AND u.token_expires_at > ?",
                (hash_token(authorization[7:]), now())).fetchone()
            if row:
                u = {**dict(row), "admin": bool(row["admin"])}
                if u["token_expires_at"] < token_expiry(TOKEN_TTL_DAYS - 1):  # sliding expiry, written at most once a day
                    u["token_expires_at"] = token_expiry()
                    db.execute("UPDATE users SET token_expires_at=? WHERE id=? AND revoked_at IS NULL",
                               (u["token_expires_at"], u["id"]))
                    db.commit()
                return u
        raise HTTPException(401, "invalid or missing bearer token")

    def dispatcher_only(u: dict = Depends(user)) -> dict:
        if u["role"] != "dispatcher":
            raise HTTPException(403, "dispatcher only")
        return u

    def admin_only(u: dict = Depends(dispatcher_only)) -> dict:
        # Admins create users and mint, rotate and revoke tokens; plain dispatchers only dispatch.
        if not u["admin"]:
            raise HTTPException(403, "admin only")
        return u

    def driver_only(u: dict = Depends(user)) -> dict:
        if u["role"] != "driver":
            raise HTTPException(403, "driver only")
        return u

    def rate_over(db: Conn, bucket: str, n: int, window_s: float) -> bool:
        return db.execute("SELECT COUNT(*) FROM rate_events WHERE bucket=? AND at>?",
                          (bucket, time.time() - window_s)).fetchone()[0] >= n

    def rate_hit(db: Conn, bucket: str):
        db.execute("INSERT INTO rate_events (bucket,at) VALUES (?,?)", (bucket, time.time()))

    def create_limit(db: Conn, u: dict):
        # shortcut: count-then-insert can let a burst of parallel requests past by a few; fine for a coarse cap.
        if rate_over(db, f"create:{u['id']}", create_per_min, 60):
            raise HTTPException(429, "too many creates, slow down")
        rate_hit(db, f"create:{u['id']}")

    Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    Phone = Annotated[str, StringConstraints(max_length=30), AfterValidator(bd_phone)]

    class StepIn(BaseModel):
        model_config = ConfigDict(extra="forbid")
        status: State
        at: AwareDatetime | None = None  # null: the paper log has no time for this step

    class MissionIn(BaseModel):
        pickup_address: Text
        assigned_vehicle_id: str | None = None
        assigned_driver_id: str | None = None  # omitted: taken from the vehicle's paired driver
        pickup_lat: float | None = Field(None, ge=-90, le=90)
        pickup_lng: float | None = Field(None, ge=-180, le=180)
        # Paper-log back-fill: the real dispatch time and every later step, so the mission is recorded already over.
        dispatched_at: AwareDatetime | None = None
        steps: list[StepIn] | None = Field(None, min_length=1, max_length=len(State))

        @model_validator(mode="after")
        def both_or_neither(self):
            if (self.pickup_lat is None) != (self.pickup_lng is None):
                raise ValueError("pickup_lat and pickup_lng must be given together")
            if (self.dispatched_at is None) != (self.steps is None):
                raise ValueError("dispatched_at and steps must be given together (paper-log back-fill)")
            return self

    class StatusIn(BaseModel):
        model_config = ConfigDict(extra="forbid")  # unknown fields (the old `notes`) are refused, never silently dropped
        status: State
        reason: Text | None = None
        event_time: AwareDatetime | None = None

    class PingIn(BaseModel):
        lat: float = Field(ge=-90, le=90)
        lng: float = Field(ge=-180, le=180)
        ts: AwareDatetime
        sent_at: AwareDatetime | None = None  # phone clock at send time; with ts it gives the fix's age, whatever the skew
        accuracy: float | None = Field(None, ge=0, le=100_000)
        on_shift: bool = False  # the wrapper's shift mode: between missions the paired driver still reports the vehicle

    def out(row) -> dict:
        d = dict(row)
        d["mission_id"] = d.pop("id")
        return d

    def audit(db: Conn, mid: str, uid: str, src: str | None, dst: str, t: str, behalf_of: str | None = None,
              reason: str | None = None, event_time: str | None = None):
        db.execute("INSERT INTO mission_audit (mission_id,user_id,from_status,to_status,ts,on_behalf_of,reason,event_time) "
                   "VALUES (?,?,?,?,?,?,?,?)", (mid, uid, src, dst, t, behalf_of, reason, event_time))

    def assignable(db: Conn, did: str):
        r = db.execute("SELECT u.revoked_at, u.token_expires_at FROM drivers d JOIN users u ON u.id=d.user_id WHERE d.id=?",
                       (did,)).fetchone()
        if not r:
            raise HTTPException(422, "unknown driver")
        if r["revoked_at"] or r["token_expires_at"] <= now():
            raise HTTPException(422, "driver is revoked or expired; issue a pairing code first")

    def notify_driver(mid: str, event: str):
        # Runs after the response is sent (BackgroundTasks) on its own connection, so SMS never delays or fails dispatch.
        if not sms.configured():
            return
        with closing(open_db(path)) as db:
            m = db.execute("SELECT m.pickup_address, m.pickup_lat, m.pickup_lng, d.id AS did, d.phone FROM missions m "
                           "JOIN drivers d ON d.id=m.assigned_driver_id WHERE m.id=?", (mid,)).fetchone()
            if not m or not m["phone"]:
                return
            link = f" https://maps.google.com/?q={m['pickup_lat']},{m['pickup_lng']}" if m["pickup_lat"] is not None else ""
            head = "CANCELLED ambulance mission" if event == "cancel" else "New ambulance mission"
            result = sms.send_sms(m["phone"], f"{head} {mid[:8]}: {m['pickup_address'][:80]}{link}")
            db.execute("INSERT INTO sms_audit (mission_id,driver_id,event,result,ts) VALUES (?,?,?,?,?)",
                       (mid, m["did"], event, result, now()))
            db.commit()

    @app.get("/healthz")
    def healthz():
        # No auth on purpose: uptime checks and the proxy probe it, and it reveals only up or down.
        try:
            with closing(open_db(path)) as db:
                db.execute("SELECT version_num FROM alembic_version").fetchone()  # a real table, not just a live socket
        except Exception:  # any DB failure means "not ready"
            return JSONResponse({"ok": False}, status_code=503)
        return {"ok": True}

    @app.get("/.well-known/assetlinks.json")
    def assetlinks():
        # No auth on purpose: Android fetches it to verify that the driver app may open this host's /driver/ links.
        if not android_certs:
            raise HTTPException(404, "not configured")
        return [{"relation": ["delegate_permission/common.handle_all_urls"],
                 "target": {"namespace": "android_app", "package_name": ANDROID_PACKAGE,
                            "sha256_cert_fingerprints": android_certs}}]

    @app.post("/missions", status_code=201)
    def create_mission(body: MissionIn, bg: BackgroundTasks, u: dict = Depends(dispatcher_only),
                       db: Conn = Depends(get_db)):
        create_limit(db, u)
        vid, did = body.assigned_vehicle_id, body.assigned_driver_id
        if vid:
            v = db.execute("SELECT driver_id FROM vehicles WHERE id=? AND active", (vid,)).fetchone()
            if not v:
                raise HTTPException(422, "unknown or inactive vehicle")
            if "assigned_driver_id" not in body.model_fields_set:
                did = v["driver_id"]
        elif did:  # a driver needs a vehicle, or his pings have nowhere to go
            v = db.execute("SELECT id FROM vehicles WHERE driver_id=? AND active", (did,)).fetchone()
            if not v:
                raise HTTPException(422, "driver has no vehicle: pair one (PUT /vehicles/{id}/driver) or pass assigned_vehicle_id")
            vid = v["id"]
        if body.steps:
            return backfill(db, u, body, vid, did)
        if did:
            assignable(db, did)
        if db.execute(f"SELECT 1 FROM missions WHERE {ACTIVE_SQL} AND (assigned_vehicle_id=? OR assigned_driver_id=?)",
                      (*TERMINAL, vid, did)).fetchone():
            raise HTTPException(409, "vehicle or driver already has an active mission")
        mid, t = str(uuid.uuid4()), now()
        try:  # the partial unique indexes (migration 0006) stop two dispatchers racing past the check above
            db.execute("INSERT INTO missions (id,status,pickup_address,assigned_vehicle_id,assigned_driver_id,created_at,"
                       "updated_at,pickup_lat,pickup_lng) VALUES (?,?,?,?,?,?,?,?,?)",
                       (mid, INITIAL.value, body.pickup_address, vid, did, t, t, body.pickup_lat, body.pickup_lng))
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "vehicle or driver already has an active mission")
        audit(db, mid, u["id"], None, INITIAL.value, t)
        db.commit()
        if did:
            bg.add_task(notify_driver, mid, "create")
        return out(db.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone())

    def backfill(db: Conn, u: dict, body: MissionIn, vid: str | None, did: str | None) -> dict:
        # A paper-log mission is written in one go, already over: it is never active, so it needs no free vehicle, never
        # alerts the driver (no SMS, no app alarm) and never raises the ack alarm. Each step is audited with its time.
        t, utc = now(), lambda d: d and d.astimezone(timezone.utc).isoformat(timespec="microseconds")
        state, prev, steps = INITIAL, utc(body.dispatched_at), []
        if not now(-BACKFILL_WINDOW) <= prev <= t:
            raise HTTPException(422, "dispatched_at must lie within the last 7 days and not in the future")
        for st in body.steps:
            try:
                state = transition(state, st.status)
            except InvalidTransition as e:
                raise HTTPException(422, f"back-fill steps: {e}")
            at = utc(st.at)
            if at and not prev <= at <= t:  # step times only move forward, or response-time figures come out negative
                raise HTTPException(422, "back-fill step times must not precede the previous step or lie in the future")
            prev = at or prev
            steps.append((state, at))
        if state.value not in TERMINAL or not steps[-1][1]:
            raise HTTPException(422, "back-fill steps must end in COMPLETED or CANCELLED, with its time")
        mid, cols = str(uuid.uuid4()), "".join(f",{s.value.lower()}_at" for s, _ in steps)  # names from the State enum
        db.execute(f"INSERT INTO missions (id,status,pickup_address,assigned_vehicle_id,assigned_driver_id,created_at,"
                   f"updated_at,pickup_lat,pickup_lng{cols}) VALUES ({','.join('?' * (9 + len(steps)))})",
                   (mid, state.value, body.pickup_address, vid, did, utc(body.dispatched_at), prev, body.pickup_lat,
                    body.pickup_lng, *(a for _, a in steps)))
        audit(db, mid, u["id"], None, INITIAL.value, t, reason="back-fill", event_time=utc(body.dispatched_at))
        src = INITIAL
        for s, a in steps:
            audit(db, mid, u["id"], src.value, s.value, t, did if on_behalf(u["role"], s) else None, "back-fill", a)
            src = s
        db.commit()
        return out(db.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone())

    @app.get("/missions")
    def list_missions(status: State | None = None, active: bool = False, limit: int = Query(200, ge=1, le=500),
                      offset: int = Query(0, ge=0), u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        # Newest first. active=true: every non-terminal mission, unpaged (a fleet never has hundreds in flight).
        sql, args = "SELECT * FROM missions WHERE (CAST(? AS TEXT) IS NULL OR status=?)", [status.value if status else None] * 2
        if active:
            sql, args = sql + f" AND {ACTIVE_SQL}", args + TERMINAL
        sql += " ORDER BY created_at DESC, id DESC"
        if not active:
            sql, args = sql + " LIMIT ? OFFSET ?", args + [limit, offset]
        return [out(r) for r in db.execute(sql, args).fetchall()]

    def load(db: Conn, mid: str):
        try:
            uuid.UUID(mid)
        except ValueError:
            raise HTTPException(404, "not found")
        row = db.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone()
        if not row:
            raise HTTPException(404, "not found")
        return row

    @app.get("/me")
    def me(u: dict = Depends(user), db: Conn = Depends(get_db)):
        r = {"role": u["role"], "user_id": u["id"], "admin": u["admin"], "token_expires_at": u["token_expires_at"]}
        if u["role"] == "driver":
            r["driver_id"] = u["driver_id"]
            m = current_row(db, u["driver_id"])
            r["vehicle_id"] = m["assigned_vehicle_id"] if m else None
            v = db.execute("SELECT id FROM vehicles WHERE driver_id=? AND active", (u["driver_id"],)).fetchone()
            r["paired_vehicle_id"] = v["id"] if v else None  # what an on-shift wrapper reports between missions
        return r

    def current_row(db: Conn, did: str, recent_s: float = 0):
        row = db.execute(f"SELECT * FROM missions WHERE assigned_driver_id=? AND {ACTIVE_SQL} "
                         "ORDER BY created_at DESC LIMIT 1", (did, *TERMINAL)).fetchone()
        if row or not recent_s:
            return row
        return db.execute("SELECT * FROM missions WHERE assigned_driver_id=? AND updated_at>? ORDER BY updated_at DESC LIMIT 1",
                          (did, now(timedelta(seconds=-recent_s)))).fetchone()

    @app.get("/missions/current")
    def current_mission(u: dict = Depends(driver_only), db: Conn = Depends(get_db)):
        # The active mission, else one that ended in the last 10 minutes (its status says why it is gone).
        m = current_row(db, u["driver_id"], RECENT_TERMINAL_S)
        if not m:
            raise HTTPException(404, "no active mission")
        return out(m)

    @app.get("/meta/transitions")
    def transitions(behalf: bool = Query(False, alias="on_behalf"), u: dict = Depends(user)):
        # on_behalf=true: the driver's moves a dispatcher may make for them (PATCH then needs a reason).
        ok = (lambda n: on_behalf(u["role"], n)) if behalf else (lambda n: required_role(n) == u["role"])
        return {s.value: sorted(n.value for n in nxt if ok(n)) for s, nxt in TRANSITIONS.items()}

    class VehicleIn(BaseModel):
        operator: Text
        registration: Text

    class VehiclePatch(BaseModel):
        active: bool

    class DriverRef(BaseModel):
        driver_id: str | None

    class DriverIn(BaseModel):
        name: Text
        phone: Phone | None = None

    class DriverPatch(BaseModel):
        phone: Phone | None

    class UserIn(BaseModel):
        name: Text
        admin: bool = False

    class PairIn(BaseModel):
        code: Annotated[str, StringConstraints(max_length=20), AfterValidator(pair_code)]

    def vehicles(db: Conn, vid: str | None = None) -> list[dict]:
        rows = db.execute(
            "SELECT v.id, v.operator, v.registration, v.active, v.driver_id, p.lat, p.lng, p.accuracy, p.ts, "
            f"EXISTS (SELECT 1 FROM missions m WHERE m.assigned_vehicle_id=v.id AND m.{ACTIVE_SQL}) AS busy FROM vehicles v "
            "LEFT JOIN vehicle_pings p ON p.id=(SELECT id FROM vehicle_pings WHERE vehicle_id=v.id ORDER BY ts DESC LIMIT 1) "
            "WHERE (CAST(? AS TEXT) IS NULL OR v.id=?) ORDER BY v.registration", (*TERMINAL, vid, vid)).fetchall()
        stale_before = now(timedelta(seconds=-STALE_S))
        return [{"vehicle_id": r["id"], "operator": r["operator"], "registration": r["registration"],
                 "active": bool(r["active"]), "driver_id": r["driver_id"], "busy": bool(r["busy"]),
                 "last_position": {"lat": r["lat"], "lng": r["lng"], "accuracy": r["accuracy"], "ts": r["ts"],
                                   "stale": r["ts"] < stale_before} if r["ts"] else None}
                for r in rows]

    @app.get("/vehicles")
    def list_vehicles(u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        return vehicles(db)

    @app.post("/vehicles", status_code=201)
    def create_vehicle(body: VehicleIn, u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        try:
            vid = add_vehicle(db, body.operator, body.registration)
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "registration already exists")
        auth_audit(db, u["id"], vid, "create_vehicle")
        db.commit()
        return vehicles(db, vid)[0]

    @app.patch("/vehicles/{vid}")
    def set_vehicle_active(vid: str, body: VehiclePatch, u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        # Inactive vehicles (workshop, off shift) cannot be dispatched; a running mission is left alone.
        if db.execute("UPDATE vehicles SET active=? WHERE id=?", (body.active, vid)).rowcount != 1:
            raise HTTPException(404, "unknown vehicle")
        db.commit()
        return vehicles(db, vid)[0]

    @app.put("/vehicles/{vid}/driver")
    def pair_vehicle_driver(vid: str, body: DriverRef, u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        if not db.execute("SELECT 1 FROM vehicles WHERE id=?", (vid,)).fetchone():
            raise HTTPException(404, "unknown vehicle")
        if body.driver_id:
            assignable(db, body.driver_id)
            db.execute("UPDATE vehicles SET driver_id=NULL WHERE driver_id=? AND id<>?", (body.driver_id, vid))  # one seat
        try:
            db.execute("UPDATE vehicles SET driver_id=? WHERE id=?", (body.driver_id, vid))
        except IntegrityError:  # another dispatcher paired the same driver at the same moment
            db.rollback()
            raise HTTPException(409, "driver was just paired elsewhere, retry")
        db.commit()
        return vehicles(db, vid)[0]

    def drivers(db: Conn, did: str | None = None) -> list[dict]:
        rows = db.execute("SELECT d.id, d.name, d.phone, u.revoked_at, u.token_expires_at FROM drivers d "
                          "JOIN users u ON u.id=d.user_id WHERE (CAST(? AS TEXT) IS NULL OR d.id=?) ORDER BY d.name",
                          (did, did)).fetchall()
        return [{"driver_id": r["id"], "name": r["name"], "phone": r["phone"], "revoked": r["revoked_at"] is not None,
                 "expires_at": r["token_expires_at"]} for r in rows]

    @app.get("/drivers")
    def list_drivers(u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        return drivers(db)

    @app.post("/drivers", status_code=201)
    def create_driver(body: DriverIn, u: dict = Depends(admin_only), db: Conn = Depends(get_db)):
        create_limit(db, u)
        did, tok = add_user(db, body.name, "driver", phone=body.phone)
        auth_audit(db, u["id"], driver_user(db, did), "create_driver")
        db.commit()
        return {"driver_id": did, "name": body.name, "phone": body.phone, "token": tok}  # token shown once; hash stored

    @app.patch("/drivers/{did}")
    def update_driver(did: str, body: DriverPatch, u: dict = Depends(admin_only), db: Conn = Depends(get_db)):
        # Admin only and audited: the phone receives every mission SMS (pickup address and map link).
        uid = driver_user(db, did)
        row = db.execute("SELECT phone FROM drivers WHERE id=?", (did,)).fetchone()
        old_phone = row["phone"] if row else None
        db.execute("UPDATE drivers SET phone=? WHERE id=?", (body.phone, did))
        tail = lambda p: f"***{p[-3:]}" if p else "none"  # auth_audit is never pruned: keep only the last 3 digits
        auth_audit(db, u["id"], uid, f"update_phone:{tail(old_phone)}->{tail(body.phone)}")
        db.commit()
        return drivers(db, did)[0]

    @app.get("/missions/{mid}/audit")
    def mission_audit(mid: str, u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        load(db, mid)
        return [dict(r) for r in db.execute(
            "SELECT user_id, from_status, to_status, ts, on_behalf_of, reason, event_time FROM mission_audit "
            "WHERE mission_id=? ORDER BY id", (mid,))]

    @app.get("/missions/{mid}")
    def get_mission(mid: str, u: dict = Depends(user), db: Conn = Depends(get_db)):
        row = load(db, mid)
        if u["role"] != "dispatcher" and row["assigned_driver_id"] != u["driver_id"]:
            raise HTTPException(403, "not your mission")
        return out(row)

    def advance(db: Conn, mid: str, uid: str, expected: str, new: str, behalf_of: str | None = None,
                reason: str | None = None, event_time: str | None = None):
        # Compare-and-set on the status we validated against; audit row in the same transaction.
        # The <status>_at column name comes from the State enum, never from input.
        t = now()
        cur = db.execute(f"UPDATE missions SET status=?, updated_at=?, {new.lower()}_at=? WHERE id=? AND status=?",
                         (new, t, event_time or t, mid, expected))
        if cur.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "mission status changed concurrently")
        audit(db, mid, uid, expected, new, t, behalf_of, reason, event_time)
        db.commit()

    app.state.advance = advance

    @app.patch("/missions/{mid}/status")
    def set_status(mid: str, body: StatusIn, bg: BackgroundTasks, u: dict = Depends(user), db: Conn = Depends(get_db)):
        need, behalf = required_role(body.status), on_behalf(u["role"], body.status)
        if u["role"] != need and not behalf:
            raise HTTPException(403, f"{need} only for {body.status.value}")
        if u["role"] == "driver" and (body.reason or body.event_time):
            raise HTTPException(422, "reason and event_time are for dispatchers")
        if behalf and not body.reason:
            raise HTTPException(422, "reason required when acting for the driver")
        row = load(db, mid)
        if need == "driver" and not behalf and row["assigned_driver_id"] != u["driver_id"]:
            raise HTTPException(403, "not the assigned driver")
        at = body.event_time and body.event_time.astimezone(timezone.utc).isoformat(timespec="microseconds")
        if at and not now(-BACKFILL_WINDOW) <= at <= now():
            raise HTTPException(422, "event_time must lie within the last 7 days and not in the future")
        prev = row["created_at"] if row["status"] == INITIAL.value else row[f"{row['status'].lower()}_at"] or row["created_at"]
        if at and at < prev:  # step times only move forward, or response-time figures come out negative
            raise HTTPException(422, "event_time is before the mission's previous step")
        try:
            new = transition(State(row["status"]), body.status)
        except InvalidTransition as e:
            raise HTTPException(409, str(e))
        advance(db, mid, u["id"], row["status"], new.value, row["assigned_driver_id"] if behalf else None, body.reason, at)
        if new is State.CANCELLED and row["assigned_driver_id"]:
            bg.add_task(notify_driver, mid, "cancel")
        return out(load(db, mid))

    @app.post("/missions/{mid}/ack")
    def ack_mission(mid: str, u: dict = Depends(driver_only), db: Conn = Depends(get_db)):
        # Not a status change (so not in required_role): records once that the assigned driver has seen the mission.
        row = load(db, mid)
        if row["assigned_driver_id"] != u["driver_id"]:
            raise HTTPException(403, "not the assigned driver")
        if row["status"] in TERMINAL:
            raise HTTPException(409, "mission already ended")
        db.execute("UPDATE missions SET acknowledged_at=? WHERE id=? AND acknowledged_at IS NULL", (now(), mid))
        db.commit()
        return out(load(db, mid))

    @app.post("/vehicles/{vid}/pings", status_code=201)
    def ping(vid: str, body: PingIn, u: dict = Depends(driver_only), db: Conn = Depends(get_db)):
        mission = db.execute(f"SELECT 1 FROM missions WHERE assigned_driver_id=? AND assigned_vehicle_id=? AND {ACTIVE_SQL}",
                             (u["driver_id"], vid, *TERMINAL)).fetchone()
        # Between missions only the driver paired with an in-service, free vehicle reports it, and only on shift: never
        # when unpaired, signed out or off shift (the consent draft promises this), and never two drivers for one vehicle.
        if not mission and not (body.on_shift and db.execute(
                f"SELECT 1 FROM vehicles v WHERE v.id=? AND v.driver_id=? AND v.active AND NOT EXISTS (SELECT 1 FROM "
                f"missions m WHERE m.{ACTIVE_SQL} AND (m.assigned_vehicle_id=v.id OR m.assigned_driver_id=?))",
                (vid, u["driver_id"], *TERMINAL, u["driver_id"])).fetchone()):
            raise HTTPException(403, "no active mission for this driver and vehicle, and not on shift in it")
        # The phone clock may be wrong (manual time, dead RTC): store the server receive time, minus the fix's age when
        # the phone says how old it is (queued offline), and return the skew so the app can warn the driver.
        n = datetime.now(timezone.utc)
        age = max((body.sent_at - body.ts).total_seconds(), 0) if body.sent_at else 0
        if age > ping_max_age_s:
            raise HTTPException(422, f"fix older than {ping_max_age_s:.0f} s")
        if abs(body.lat) < 1e-3 and abs(body.lng) < 1e-3:
            raise HTTPException(422, "(0, 0) is not a real position")
        ts = n - timedelta(seconds=age)
        last = db.execute("SELECT lat,lng,accuracy,ts FROM vehicle_pings WHERE vehicle_id=? ORDER BY ts DESC LIMIT 1",
                          (vid,)).fetchone()
        if last:
            dt = abs((ts - datetime.fromisoformat(last["ts"])).total_seconds())
            slack = JUMP_SLACK_M + (body.accuracy or 0) + (last["accuracy"] or 0) + MAX_SPEED_MPS * dt
            if dt <= JUMP_WINDOW_S and distance_m(last["lat"], last["lng"], body.lat, body.lng) > slack:
                raise HTTPException(422, "position jump is physically impossible")
        # Rate limit in the DB so it holds across workers: the UPDATE wins if the last ping is old enough;
        # otherwise the INSERT collides on the primary key (row exists and is too recent) and we answer 429.
        wall = time.time()
        if db.execute("UPDATE ping_limit SET last_at=? WHERE vehicle_id=? AND last_at<=?",
                      (wall, vid, wall - ping_min_interval_s)).rowcount != 1:
            try:
                db.execute("INSERT INTO ping_limit (vehicle_id,last_at) VALUES (?,?)", (vid, wall))
            except IntegrityError:
                db.rollback()
                raise HTTPException(429, "ping rate limit")
        # Between missions keep one position per IDLE_PING_S and answer 201 anyway, so the phone moves on (no retries).
        stored = bool(mission) or not last or (ts - datetime.fromisoformat(last["ts"])).total_seconds() >= IDLE_PING_S
        if stored:
            db.execute("INSERT INTO vehicle_pings (vehicle_id,lat,lng,ts,accuracy) VALUES (?,?,?,?,?)",
                       (vid, body.lat, body.lng, ts.isoformat(timespec="microseconds"), body.accuracy))
        db.commit()
        return {"ok": True, "stored": stored, "clock_skew_s": round(((body.sent_at or body.ts) - n).total_seconds(), 1)}

    @app.get("/vehicles/{vid}/position")
    def position(vid: str, u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        row = db.execute("SELECT lat,lng,accuracy,ts FROM vehicle_pings WHERE vehicle_id=? ORDER BY ts DESC LIMIT 1",
                         (vid,)).fetchone()
        if not row:
            raise HTTPException(404, "no position")
        return {"vehicle_id": vid, **dict(row)}

    def new_token(db: Conn, actor: str, user_id: str, reenable: bool, action: str = "rotate") -> dict:
        # Self-rotation (reenable=False) must not undo a revoke that landed after the caller authenticated.
        tok, exp = secrets.token_urlsafe(32), token_expiry()
        cur = db.execute("UPDATE users SET token_hash=?, revoked_at=NULL, token_expires_at=? "
                         "WHERE id=?" + ("" if reenable else " AND revoked_at IS NULL"), (hash_token(tok), exp, user_id))
        if cur.rowcount != 1:
            db.rollback()
            raise HTTPException(401, "invalid or missing bearer token")
        auth_audit(db, actor, user_id, action)
        db.commit()
        return {"token": tok, "expires_at": exp}

    def driver_user(db: Conn, did: str) -> str:
        row = db.execute("SELECT user_id FROM drivers WHERE id=?", (did,)).fetchone()
        if not row:
            raise HTTPException(404, "unknown driver")
        return row["user_id"]

    @app.post("/me/token/rotate")
    def rotate_own_token(u: dict = Depends(user), db: Conn = Depends(get_db)):
        return new_token(db, u["id"], u["id"], reenable=False)  # old token stops working at once; new one shown once

    @app.post("/drivers/{did}/token/rotate")
    def rotate_driver_token(did: str, u: dict = Depends(admin_only), db: Conn = Depends(get_db)):
        return {"driver_id": did, **new_token(db, u["id"], driver_user(db, did), reenable=True)}  # also re-enables a revoked driver

    @app.post("/drivers/{did}/token/revoke", status_code=204)
    def revoke_driver_token(did: str, u: dict = Depends(admin_only), db: Conn = Depends(get_db)):
        revoke_user(db, u["id"], driver_user(db, did))
        db.commit()

    @app.get("/users")
    def list_users(u: dict = Depends(admin_only), db: Conn = Depends(get_db)):
        return [{"user_id": r["id"], "name": r["name"], "role": r["role"], "admin": bool(r["admin"]),
                 "revoked": r["revoked_at"] is not None, "expires_at": r["token_expires_at"]}
                for r in db.execute("SELECT id, name, role, admin, revoked_at, token_expires_at FROM users ORDER BY name")]

    @app.post("/users", status_code=201)
    def create_user(body: UserIn, u: dict = Depends(admin_only), db: Conn = Depends(get_db)):
        # Dispatchers and admins only; drivers come from POST /drivers because they need a driver record.
        create_limit(db, u)
        uid, tok = add_user(db, body.name, "dispatcher", admin=body.admin)
        auth_audit(db, u["id"], uid, "create_user")
        db.commit()
        return {"user_id": uid, "name": body.name, "role": "dispatcher", "admin": body.admin, "token": tok}

    @app.post("/users/{uid}/token/revoke", status_code=204)
    def revoke_any_token(uid: str, u: dict = Depends(admin_only), db: Conn = Depends(get_db)):
        if not revoke_user(db, u["id"], uid):
            raise HTTPException(404, "unknown user")
        db.commit()

    @app.post("/drivers/{did}/pairing-code")
    def issue_pairing_code(did: str, u: dict = Depends(admin_only), db: Conn = Depends(get_db)):
        # 6 digits a driver can type (or read out on the phone) instead of a 43-character token. One live code per driver.
        uid, exp = driver_user(db, did), now(PAIR_CODE_TTL)
        db.execute("DELETE FROM pairing_codes WHERE user_id=? OR expires_at<?", (uid, now()))
        while True:
            code = f"{secrets.randbelow(10 ** 6):06d}"
            if not db.execute("SELECT 1 FROM pairing_codes WHERE code_hash=?", (hash_token(code),)).fetchone():
                break
        db.execute("INSERT INTO pairing_codes (user_id,code_hash,expires_at) VALUES (?,?,?)",  # `failures` is unused
                   (uid, hash_token(code), exp))
        auth_audit(db, u["id"], uid, "pairing_code")
        db.commit()
        return {"driver_id": did, "code": code, "expires_at": exp}

    @app.post("/pair")
    def pair(body: PairIn, request: Request, db: Conn = Depends(get_db)):
        # No auth on purpose: the one-time code is the credential. Guessing is capped per client and globally (above).
        client = f"pair:{request.client.host if request.client else '-'}"
        if rate_over(db, client, PAIR_CLIENT_FAILS, PAIR_WINDOW_S):
            raise HTTPException(429, "too many wrong codes from here, wait 10 minutes")
        if rate_over(db, "pair-all", PAIR_GLOBAL_FAILS, PAIR_WINDOW_S):
            raise HTTPException(429, "too many wrong codes, pairing paused for up to 10 minutes")
        t, h = now(), hash_token(body.code)
        row = db.execute("SELECT user_id FROM pairing_codes WHERE code_hash=? AND expires_at>?", (h, t)).fetchone()
        # shortcut: unsalted sha256 of a 6-digit code is reversible from a DB dump; fine while codes live 10 minutes.
        if not row or db.execute("DELETE FROM pairing_codes WHERE code_hash=?", (h,)).rowcount != 1:
            db.rollback()
            rate_hit(db, client)
            rate_hit(db, "pair-all")
            db.commit()
            if rate_over(db, "pair-all", PAIR_GLOBAL_FAILS, PAIR_WINDOW_S):
                logging.warning("pairing paused: %d wrong codes in 10 minutes from all clients", PAIR_GLOBAL_FAILS)
            raise HTTPException(401, "invalid or expired code")
        db.execute("DELETE FROM rate_events WHERE bucket=?", (client,))  # committed with the token below
        tok = new_token(db, row["user_id"], row["user_id"], reenable=True, action="pair")  # commits the DELETE too
        u = db.execute("SELECT u.id, u.name, u.role, d.id AS driver_id FROM users u JOIN drivers d ON d.user_id=u.id "
                       "WHERE u.id=?", (row["user_id"],)).fetchone()
        return {"token": tok["token"], "user": {"user_id": u["id"], "name": u["name"], "role": u["role"],
                                                "driver_id": u["driver_id"], "token_expires_at": tok["expires_at"]}}

    @app.get("/reports/response-times")
    def response_time_report(start_date: date | None = None, end_date: date | None = None,
                             vehicle_id: str | None = None, format: str = "json",
                             u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        sql = ("SELECT m.id, m.status, m.assigned_vehicle_id, v.registration, v.operator, m.created_at, "
               "m.acknowledged_at, m.en_route_pickup_at, m.at_scene_at, m.at_hospital_at, m.completed_at "
               "FROM missions m LEFT JOIN vehicles v ON v.id=m.assigned_vehicle_id WHERE m.status <> ?")
        params = [State.CANCELLED.value]  # a cancelled mission has no response to time
        # created_at is ISO text in UTC; end_date includes its whole (UTC) day, so compare against the next day.
        if start_date:
            sql += " AND m.created_at >= ?"
            params.append(start_date.isoformat())
        if end_date:
            sql += " AND m.created_at < ?"
            params.append((end_date + timedelta(days=1)).isoformat())
        if vehicle_id:
            sql += " AND m.assigned_vehicle_id = ?"
            params.append(vehicle_id)
        sql += " ORDER BY m.created_at ASC"

        rows = db.execute(sql, tuple(params)).fetchall()

        def parse_iso(ts):
            if not ts:
                return None
            try:
                return datetime.fromisoformat(ts)
            except Exception:
                return None

        def calc_stats(numbers, round_to=1):
            if not numbers:
                return {"count": 0, "median": None, "p90": None, "min": None, "max": None}
            s = sorted(numbers)
            n = len(s)
            med = s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2.0
            p90 = s[min(int(n * 0.90), n - 1)]
            return {
                "count": n,
                "median": round(med, round_to),
                "p90": round(p90, round_to),
                "min": round(s[0], round_to),
                "max": round(s[-1], round_to),
            }

        all_ack_s, all_scene_m, all_hosp_m, all_total_m = [], [], [], []
        days_map = {}
        vehicles_map = {}

        for r in rows:
            t_created = parse_iso(r["created_at"])
            t_ack = parse_iso(r["acknowledged_at"]) or parse_iso(r["en_route_pickup_at"])
            t_scene = parse_iso(r["at_scene_at"])
            t_hosp = parse_iso(r["at_hospital_at"])
            t_comp = parse_iso(r["completed_at"])

            ack_s = (t_ack - t_created).total_seconds() if t_ack and t_created and t_ack >= t_created else None
            scene_m = (t_scene - t_ack).total_seconds() / 60.0 if t_scene and t_ack and t_scene >= t_ack else None
            hosp_m = (t_hosp - t_scene).total_seconds() / 60.0 if t_hosp and t_scene and t_hosp >= t_scene else None
            t_end = t_comp or t_hosp
            total_m = (t_end - t_created).total_seconds() / 60.0 if t_end and t_created and t_end >= t_created else None

            if ack_s is not None:
                all_ack_s.append(ack_s)
            if scene_m is not None:
                all_scene_m.append(scene_m)
            if hosp_m is not None:
                all_hosp_m.append(hosp_m)
            if total_m is not None:
                all_total_m.append(total_m)

            day = r["created_at"][:10] if r["created_at"] else "unknown"
            if day not in days_map:
                days_map[day] = {"ack_s": [], "scene_m": [], "hosp_m": [], "total_m": [], "count": 0}
            days_map[day]["count"] += 1
            if ack_s is not None: days_map[day]["ack_s"].append(ack_s)
            if scene_m is not None: days_map[day]["scene_m"].append(scene_m)
            if hosp_m is not None: days_map[day]["hosp_m"].append(hosp_m)
            if total_m is not None: days_map[day]["total_m"].append(total_m)

            v_id = r["assigned_vehicle_id"] or "unassigned"
            if v_id not in vehicles_map:
                vehicles_map[v_id] = {
                    "vehicle_id": v_id,
                    "registration": r["registration"] or "Unknown",
                    "operator": r["operator"] or "Unknown",
                    "ack_s": [], "scene_m": [], "hosp_m": [], "total_m": [], "count": 0
                }
            vehicles_map[v_id]["count"] += 1
            if ack_s is not None: vehicles_map[v_id]["ack_s"].append(ack_s)
            if scene_m is not None: vehicles_map[v_id]["scene_m"].append(scene_m)
            if hosp_m is not None: vehicles_map[v_id]["hosp_m"].append(hosp_m)
            if total_m is not None: vehicles_map[v_id]["total_m"].append(total_m)

        summary = {
            "total_missions": len(rows),
            "dispatch_to_ack_s": calc_stats(all_ack_s, 1),
            "ack_to_scene_m": calc_stats(all_scene_m, 1),
            "scene_to_hospital_m": calc_stats(all_hosp_m, 1),
            "total_turnaround_m": calc_stats(all_total_m, 1),
        }

        by_day = [
            {
                "day": d,
                "missions_count": data["count"],
                "dispatch_to_ack_s": calc_stats(data["ack_s"], 1),
                "ack_to_scene_m": calc_stats(data["scene_m"], 1),
                "scene_to_hospital_m": calc_stats(data["hosp_m"], 1),
                "total_turnaround_m": calc_stats(data["total_m"], 1),
            }
            for d, data in sorted(days_map.items())
        ]

        by_vehicle = [
            {
                "vehicle_id": v_id,
                "registration": data["registration"],
                "operator": data["operator"],
                "missions_count": data["count"],
                "dispatch_to_ack_s": calc_stats(data["ack_s"], 1),
                "ack_to_scene_m": calc_stats(data["scene_m"], 1),
                "scene_to_hospital_m": calc_stats(data["hosp_m"], 1),
                "total_turnaround_m": calc_stats(data["total_m"], 1),
            }
            for v_id, data in sorted(vehicles_map.items(), key=lambda x: x[1]["registration"])
        ]

        if format.lower() == "csv":
            out_buf = io.StringIO()
            writer = csv.writer(out_buf)
            writer.writerow([
                "Date", "Vehicle ID", "Registration", "Operator", "Missions",
                "Median Dispatch-to-Ack (s)", "P90 Dispatch-to-Ack (s)",
                "Median Ack-to-Scene (m)", "P90 Ack-to-Scene (m)",
                "Median Scene-to-Hospital (m)", "P90 Scene-to-Hospital (m)",
                "Median Turnaround (m)"
            ])
            for d in by_day:
                writer.writerow([
                    d["day"], "ALL", "All Vehicles", "-", d["missions_count"],
                    d["dispatch_to_ack_s"]["median"], d["dispatch_to_ack_s"]["p90"],
                    d["ack_to_scene_m"]["median"], d["ack_to_scene_m"]["p90"],
                    d["scene_to_hospital_m"]["median"], d["scene_to_hospital_m"]["p90"],
                    d["total_turnaround_m"]["median"]
                ])
            for v in by_vehicle:
                writer.writerow([
                    "ALL", v["vehicle_id"], v["registration"], v["operator"], v["missions_count"],
                    v["dispatch_to_ack_s"]["median"], v["dispatch_to_ack_s"]["p90"],
                    v["ack_to_scene_m"]["median"], v["ack_to_scene_m"]["p90"],
                    v["scene_to_hospital_m"]["median"], v["scene_to_hospital_m"]["p90"],
                    v["total_turnaround_m"]["median"]
                ])
            return Response(content=out_buf.getvalue(), media_type="text/csv",
                            headers={"Content-Disposition": 'attachment; filename="response_times_report.csv"'})

        return {"summary": summary, "by_day": by_day, "by_vehicle": by_vehicle}

    web = Path(__file__).resolve().parent.parent / "web"
    for mount, sub in (("/console", "dispatcher"), ("/driver", "driver")):
        if (web / sub).is_dir():  # driver PWA may not exist yet
            app.mount(mount, StaticFiles(directory=web / sub, html=True), name=sub)
    return app

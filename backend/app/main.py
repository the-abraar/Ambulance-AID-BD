import os
import secrets
import time
from contextlib import asynccontextmanager, closing
import uuid
from datetime import datetime, timedelta, timezone

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from .bootstrap import add_user, add_vehicle
from .db import Conn, IntegrityError, close_pools, hash_token, migrate, open_db, token_expiry
from .state_machine import INITIAL, TRANSITIONS, InvalidTransition, State, required_role, transition

MAX_BODY = 64 * 1024  # keep equal to request_body max_size in Caddyfile
PING_LIMIT_KEEP_S = 86400
TERMINAL = [s.value for s in State if not TRANSITIONS[s]]


def create_app(db_path: str | None = None, ping_max_age_s: float = 300, ping_max_future_s: float = 60,
               ping_min_interval_s: float = 1.0) -> FastAPI:
    path = db_path or os.environ.get("AMBULANCE_DB_PATH", "dev.db")

    @asynccontextmanager
    async def lifespan(_):
        yield
        close_pools()

    app = FastAPI(title="Ambulance-AID MVP", lifespan=lifespan)
    migrate(path)
    with closing(open_db(path)) as c0:  # shortcut: prune at startup only; upgrade to a timer if a process runs for months
        c0.execute("DELETE FROM ping_limit WHERE last_at<?", (time.time() - PING_LIMIT_KEEP_S,))
        c0.commit()

    @app.middleware("http")
    async def body_cap(request: Request, call_next):
        # Caddy enforces the real cap (also for chunked bodies); this rejects honest oversize requests when run without it.
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            return JSONResponse({"detail": "request body too large"}, status_code=413)
        return await call_next(request)

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
                "SELECT u.id, u.role, u.token_expires_at, d.id AS driver_id FROM users u LEFT JOIN drivers d ON d.user_id=u.id "
                "WHERE u.token_hash=? AND u.revoked_at IS NULL AND u.token_expires_at > ?",
                (hash_token(authorization[7:]), now())).fetchone()
            if row:
                return dict(row)
        raise HTTPException(401, "invalid or missing bearer token")

    Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

    class MissionIn(BaseModel):
        pickup_address: Text
        assigned_vehicle_id: str | None = None
        assigned_driver_id: str | None = None
        pickup_lat: float | None = Field(None, ge=-90, le=90)
        pickup_lng: float | None = Field(None, ge=-180, le=180)

        @model_validator(mode="after")
        def both_or_neither(self):
            if (self.pickup_lat is None) != (self.pickup_lng is None):
                raise ValueError("pickup_lat and pickup_lng must be given together")
            return self

    class StatusIn(BaseModel):
        status: State
        notes: Annotated[str, StringConstraints(max_length=500)] | None = None

    class PingIn(BaseModel):
        lat: float = Field(ge=-90, le=90)
        lng: float = Field(ge=-180, le=180)
        ts: datetime

    def now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    def out(row) -> dict:
        d = dict(row)
        d["mission_id"] = d.pop("id")
        return d

    def audit(db: Conn, mid: str, uid: str, src: str | None, dst: str, t: str):
        db.execute("INSERT INTO mission_audit (mission_id,user_id,from_status,to_status,ts) VALUES (?,?,?,?,?)",
                   (mid, uid, src, dst, t))

    @app.post("/missions", status_code=201)
    def create_mission(body: MissionIn, u: dict = Depends(user), db: Conn = Depends(get_db)):
        if u["role"] != "dispatcher":
            raise HTTPException(403, "dispatcher only")
        if body.assigned_vehicle_id and not db.execute(
                "SELECT 1 FROM vehicles WHERE id=? AND active", (body.assigned_vehicle_id,)).fetchone():
            raise HTTPException(422, "unknown or inactive vehicle")
        if body.assigned_driver_id and not db.execute(
                "SELECT 1 FROM drivers WHERE id=?", (body.assigned_driver_id,)).fetchone():
            raise HTTPException(422, "unknown driver")
        mid, t = str(uuid.uuid4()), now()
        db.execute("INSERT INTO missions (id,status,pickup_address,assigned_vehicle_id,assigned_driver_id,created_at,"
                   "updated_at,pickup_lat,pickup_lng) VALUES (?,?,?,?,?,?,?,?,?)",
                   (mid, INITIAL.value, body.pickup_address, body.assigned_vehicle_id, body.assigned_driver_id, t, t,
                    body.pickup_lat, body.pickup_lng))
        audit(db, mid, u["id"], None, INITIAL.value, t)
        db.commit()
        return out(db.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone())

    @app.get("/missions")
    def list_missions(status: State | None = None, limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
                      u: dict = Depends(user), db: Conn = Depends(get_db)):
        if u["role"] != "dispatcher":
            raise HTTPException(403, "dispatcher only")
        rows = db.execute("SELECT * FROM missions WHERE (CAST(? AS TEXT) IS NULL OR status=?) ORDER BY created_at, id LIMIT ? OFFSET ?",
                          (status.value if status else None,) * 2 + (limit, offset)).fetchall()
        return [out(r) for r in rows]

    def load(db: Conn, mid: str):
        try:
            uuid.UUID(mid)
        except ValueError:
            raise HTTPException(404, "not found")
        row = db.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone()
        if not row:
            raise HTTPException(404, "not found")
        return row

    def dispatcher_only(u: dict = Depends(user)) -> dict:
        if u["role"] != "dispatcher":
            raise HTTPException(403, "dispatcher only")
        return u

    @app.get("/me")
    def me(u: dict = Depends(user), db: Conn = Depends(get_db)):
        r = {"role": u["role"], "user_id": u["id"], "token_expires_at": u["token_expires_at"]}
        if u["role"] == "driver":
            r["driver_id"] = u["driver_id"]
            m = current_row(db, u)
            r["vehicle_id"] = m["assigned_vehicle_id"] if m else None
        return r

    def current_row(db: Conn, u):
        return db.execute(
            f"SELECT * FROM missions WHERE assigned_driver_id=? AND status NOT IN ({','.join('?' * len(TERMINAL))}) "
            "ORDER BY created_at DESC LIMIT 1", (u["driver_id"], *TERMINAL)).fetchone()

    @app.get("/missions/current")
    def current_mission(u: dict = Depends(user), db: Conn = Depends(get_db)):
        if u["role"] != "driver":
            raise HTTPException(403, "driver only")
        m = current_row(db, u)
        if not m:
            raise HTTPException(404, "no active mission")
        return out(m)

    @app.get("/meta/transitions")
    def transitions(u: dict = Depends(user)):
        return {s.value: sorted(n.value for n in nxt if required_role(n) == u["role"])
                for s, nxt in TRANSITIONS.items()}

    class VehicleIn(BaseModel):
        operator: Text
        registration: Text

    class DriverIn(BaseModel):
        name: Text

    @app.get("/vehicles")
    def list_vehicles(u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        rows = db.execute(
            "SELECT v.id, v.operator, v.registration, v.active, p.lat, p.lng, p.ts FROM vehicles v "
            "LEFT JOIN vehicle_pings p ON p.id=(SELECT id FROM vehicle_pings WHERE vehicle_id=v.id "
            "ORDER BY ts DESC LIMIT 1) ORDER BY v.registration").fetchall()
        return [{"vehicle_id": r["id"], "operator": r["operator"], "registration": r["registration"],
                 "active": bool(r["active"]),
                 "last_ping": {"lat": r["lat"], "lng": r["lng"], "ts": r["ts"]} if r["ts"] else None}
                for r in rows]

    @app.post("/vehicles", status_code=201)
    def create_vehicle(body: VehicleIn, u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        try:
            vid = add_vehicle(db, body.operator, body.registration)
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "registration already exists")
        auth_audit(db, u["id"], vid, "create_vehicle")
        db.commit()
        return {"vehicle_id": vid, "operator": body.operator, "registration": body.registration, "active": True,
                "last_ping": None}

    @app.get("/drivers")
    def list_drivers(u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        return [{"driver_id": r["id"], "name": r["name"]}
                for r in db.execute("SELECT id, name FROM drivers ORDER BY name")]

    @app.post("/drivers", status_code=201)
    def create_driver(body: DriverIn, u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        did, tok = add_user(db, body.name, "driver")
        auth_audit(db, u["id"], driver_user(db, did), "create_driver")
        db.commit()
        return {"driver_id": did, "name": body.name, "token": tok}  # token shown once; only its hash is stored

    @app.get("/missions/{mid}/audit")
    def mission_audit(mid: str, u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        load(db, mid)
        return [dict(r) for r in db.execute(
            "SELECT user_id, from_status, to_status, ts FROM mission_audit WHERE mission_id=? ORDER BY id", (mid,))]

    @app.get("/missions/{mid}")
    def get_mission(mid: str, u: dict = Depends(user), db: Conn = Depends(get_db)):
        row = load(db, mid)
        if u["role"] != "dispatcher" and row["assigned_driver_id"] != u["driver_id"]:
            raise HTTPException(403, "not your mission")
        return out(row)

    def advance(db: Conn, mid: str, uid: str, expected: str, new: str):
        # Compare-and-set on the status we validated against; audit row in the same transaction.
        t = now()
        cur = db.execute("UPDATE missions SET status=?, updated_at=? WHERE id=? AND status=?",
                         (new, t, mid, expected))
        if cur.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "mission status changed concurrently")
        audit(db, mid, uid, expected, new, t)
        db.commit()

    app.state.advance = advance

    @app.patch("/missions/{mid}/status")
    def set_status(mid: str, body: StatusIn, u: dict = Depends(user), db: Conn = Depends(get_db)):
        need = required_role(body.status)
        if u["role"] != need:
            raise HTTPException(403, f"{need} only for {body.status.value}")
        row = load(db, mid)
        if need == "driver" and row["assigned_driver_id"] != u["driver_id"]:
            raise HTTPException(403, "not the assigned driver")
        try:
            new = transition(State(row["status"]), body.status)
        except InvalidTransition as e:
            raise HTTPException(409, str(e))
        advance(db, mid, u["id"], row["status"], new.value)
        return out(load(db, mid))

    @app.post("/vehicles/{vid}/pings", status_code=201)
    def ping(vid: str, body: PingIn, u: dict = Depends(user), db: Conn = Depends(get_db)):
        if u["role"] != "driver":
            raise HTTPException(403, "driver only")
        if not db.execute(
                f"SELECT 1 FROM missions WHERE assigned_driver_id=? AND assigned_vehicle_id=? "
                f"AND status NOT IN ({','.join('?' * len(TERMINAL))})", (u["driver_id"], vid, *TERMINAL)).fetchone():
            raise HTTPException(403, "no active mission for this driver and vehicle")
        if body.ts.tzinfo is None:
            raise HTTPException(422, "ts must include timezone")
        ts, n = body.ts.astimezone(timezone.utc), datetime.now(timezone.utc)
        if ts < n - timedelta(seconds=ping_max_age_s) or ts > n + timedelta(seconds=ping_max_future_s):
            raise HTTPException(422, "ts outside accepted window")
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
        # Clamp to receive time: a ping dated slightly ahead must not outrank later real ones in "latest position".
        db.execute("INSERT INTO vehicle_pings (vehicle_id,lat,lng,ts) VALUES (?,?,?,?)",
                   (vid, body.lat, body.lng, min(ts, n).isoformat(timespec="microseconds")))
        db.commit()
        return {"ok": True}

    @app.get("/vehicles/{vid}/position")
    def position(vid: str, u: dict = Depends(user), db: Conn = Depends(get_db)):
        if u["role"] != "dispatcher":
            raise HTTPException(403, "dispatcher only")
        row = db.execute("SELECT lat,lng,ts FROM vehicle_pings WHERE vehicle_id=? ORDER BY ts DESC LIMIT 1",
                         (vid,)).fetchone()
        if not row:
            raise HTTPException(404, "no position")
        return {"vehicle_id": vid, **dict(row)}

    def auth_audit(db: Conn, actor: str, target: str, action: str):
        db.execute("INSERT INTO auth_audit (actor_id,target_user_id,action,ts) VALUES (?,?,?,?)",
                   (actor, target, action, now()))

    def new_token(db: Conn, actor: str, user_id: str, reenable: bool) -> dict:
        # Self-rotation (reenable=False) must not undo a revoke that landed after the caller authenticated.
        tok, exp = secrets.token_urlsafe(32), token_expiry()
        cur = db.execute("UPDATE users SET token_hash=?, revoked_at=NULL, token_expires_at=? "
                         "WHERE id=?" + ("" if reenable else " AND revoked_at IS NULL"), (hash_token(tok), exp, user_id))
        if cur.rowcount != 1:
            db.rollback()
            raise HTTPException(401, "invalid or missing bearer token")
        auth_audit(db, actor, user_id, "rotate")
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
    def rotate_driver_token(did: str, u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        return {"driver_id": did, **new_token(db, u["id"], driver_user(db, did), reenable=True)}  # also re-enables a revoked driver

    @app.post("/drivers/{did}/token/revoke", status_code=204)
    def revoke_driver_token(did: str, u: dict = Depends(dispatcher_only), db: Conn = Depends(get_db)):
        target = driver_user(db, did)
        db.execute("UPDATE users SET revoked_at=? WHERE id=?", (now(), target))
        auth_audit(db, u["id"], target, "revoke")
        db.commit()

    web = Path(__file__).resolve().parent.parent / "web"
    for mount, sub in (("/console", "dispatcher"), ("/driver", "driver")):
        if (web / sub).is_dir():  # driver PWA may not exist yet
            app.mount(mount, StaticFiles(directory=web / sub, html=True), name=sub)
    return app

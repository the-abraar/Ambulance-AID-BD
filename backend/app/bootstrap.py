"""Bootstrap and recovery CLI. Prints a token once; only its hash is stored. Needs AMBULANCE_DB_PATH (or AMBULANCE_DEV=1).
  python -m app.bootstrap admin NAME          dispatcher who may also create users and mint/rotate/revoke tokens
  python -m app.bootstrap dispatcher NAME     dispatch only
  python -m app.bootstrap driver NAME
  python -m app.bootstrap vehicle OPERATOR REGISTRATION
  python -m app.bootstrap revoke USER_ID      kill any user's token at once (e.g. a stolen admin token)
"""
import secrets
import sys
import uuid

from .db import connect, db_target, hash_token, now, token_expiry


# Helpers do not commit: the caller commits them together with their audit row.
def add_user(db, name: str, role: str, admin: bool = False, phone: str | None = None) -> tuple[str, str]:
    uid, tok = str(uuid.uuid4()), secrets.token_urlsafe(32)
    db.execute("INSERT INTO users (id,name,role,token_hash,token_expires_at,admin) VALUES (?,?,?,?,?,?)",
               (uid, name, role, hash_token(tok), token_expiry(), admin and role == "dispatcher"))
    did = None
    if role == "driver":
        did = str(uuid.uuid4())
        db.execute("INSERT INTO drivers (id,name,user_id,phone) VALUES (?,?,?,?)", (did, name, uid, phone))
    return (did or uid), tok


def add_vehicle(db, operator: str, registration: str) -> str:
    vid = str(uuid.uuid4())
    db.execute("INSERT INTO vehicles (id,operator,registration,active) VALUES (?,?,?,?)", (vid, operator, registration, True))
    return vid


def auth_audit(db, actor: str, target: str, action: str) -> None:
    db.execute("INSERT INTO auth_audit (actor_id,target_user_id,action,ts) VALUES (?,?,?,?)", (actor, target, action, now()))


def revoke_user(db, actor: str, uid: str) -> bool:
    """Revoke any user's token (and any live pairing code) until an admin issues a new one. False if unknown."""
    if db.execute("UPDATE users SET revoked_at=? WHERE id=?", (now(), uid)).rowcount != 1:
        return False
    db.execute("DELETE FROM pairing_codes WHERE user_id=?", (uid,))
    auth_audit(db, actor, uid, "revoke")
    return True


if __name__ == "__main__":
    db = connect(db_target())
    kind, *a = sys.argv[1:] or [""]
    if kind in ("admin", "dispatcher", "driver") and len(a) == 1:
        ident, tok = add_user(db, a[0], "dispatcher" if kind == "admin" else kind, admin=kind == "admin")
        db.commit()
        print(f"{kind}_id={ident}\ntoken={tok}")
    elif kind == "vehicle" and len(a) == 2:
        vid = add_vehicle(db, *a)
        db.commit()
        print(f"vehicle_id={vid}")
    elif kind == "revoke" and len(a) == 1:
        if not revoke_user(db, "cli", a[0]):
            sys.exit(f"unknown user {a[0]}")
        db.commit()
        print(f"revoked {a[0]}")
    else:
        sys.exit(__doc__)

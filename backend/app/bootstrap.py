"""Dev bootstrap. Prints the token once; only its hash is stored.
  python -m app.bootstrap dispatcher NAME
  python -m app.bootstrap driver NAME
  python -m app.bootstrap vehicle OPERATOR REGISTRATION
"""
import os
import secrets
import sys
import uuid

from .db import connect, hash_token


def add_user(db, name: str, role: str) -> tuple[str, str]:
    uid, tok = str(uuid.uuid4()), secrets.token_urlsafe(32)
    db.execute("INSERT INTO users VALUES (?,?,?,?)", (uid, name, role, hash_token(tok)))
    did = None
    if role == "driver":
        did = str(uuid.uuid4())
        db.execute("INSERT INTO drivers VALUES (?,?,?)", (did, name, uid))
    db.commit()
    return (did or uid), tok


def add_vehicle(db, operator: str, registration: str) -> str:
    vid = str(uuid.uuid4())
    db.execute("INSERT INTO vehicles VALUES (?,?,?,1)", (vid, operator, registration))
    db.commit()
    return vid


if __name__ == "__main__":
    db = connect(os.environ.get("AMBULANCE_DB_PATH", "dev.db"))
    kind, *a = sys.argv[1:]
    if kind in ("dispatcher", "driver") and len(a) == 1:
        ident, tok = add_user(db, a[0], kind)
        print(f"{kind}_id={ident}\ntoken={tok}")
    elif kind == "vehicle" and len(a) == 2:
        print(f"vehicle_id={add_vehicle(db, *a)}")
    else:
        sys.exit(__doc__)

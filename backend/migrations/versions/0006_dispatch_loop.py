"""Dispatch loop: admin flag, driver phone and vehicle pairing, per-status mission times and ack, one active mission per
vehicle and per driver, on-behalf audit fields, ping accuracy, pairing codes, rate events, SMS audit."""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
STEPS = ["EN_ROUTE_PICKUP", "AT_SCENE", "TRANSPORTING_PATIENT", "AT_HOSPITAL", "COMPLETED", "CANCELLED"]
ACTIVE = "{t}status NOT IN ('COMPLETED','CANCELLED')"  # keep equal to the terminal states in app/state_machine.py
UNIQUE_ACTIVE = (("ux_missions_active_vehicle", "assigned_vehicle_id"), ("ux_missions_active_driver", "assigned_driver_id"))


def upgrade():
    bind = op.get_bind()
    op.add_column("users", sa.Column("admin", sa.Boolean, nullable=False, server_default=sa.false()))
    # Admin/dispatcher split: every existing dispatcher could mint tokens, so it becomes an admin and nobody loses access.
    bind.execute(sa.text("UPDATE users SET admin=:t WHERE role='dispatcher'"), {"t": True})
    op.add_column("drivers", sa.Column("phone", sa.Text))
    op.add_column("vehicles", sa.Column("driver_id", sa.Text))
    op.create_index("ux_vehicles_driver", "vehicles", ["driver_id"], unique=True)
    op.add_column("vehicle_pings", sa.Column("accuracy", sa.Float))
    for c in ["acknowledged_at"] + [f"{s.lower()}_at" for s in STEPS]:
        op.add_column("missions", sa.Column(c, sa.Text))
    for s in STEPS:  # backfill from the audit trail
        bind.execute(sa.text(f"UPDATE missions SET {s.lower()}_at=(SELECT MAX(ts) FROM mission_audit a "
                             f"WHERE a.mission_id=missions.id AND a.to_status='{s}')"))
    for c in ("on_behalf_of", "reason", "event_time"):
        op.add_column("mission_audit", sa.Column(c, sa.Text))
    # Double-dispatched missions (possible before this revision) would block the unique indexes: close every active
    # mission that has a newer active one on the same vehicle or driver, and say so in its audit trail.
    t = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    for _, col in UNIQUE_ACTIVE:
        dups = bind.execute(sa.text(
            f"SELECT id, status FROM missions m WHERE {ACTIVE.format(t='m.')} AND m.{col} IS NOT NULL AND EXISTS ("
            f"SELECT 1 FROM missions n WHERE n.{col}=m.{col} AND {ACTIVE.format(t='n.')} "
            f"AND (n.created_at > m.created_at OR (n.created_at = m.created_at AND n.id > m.id)))")).fetchall()
        for mid, status in dups:
            bind.execute(sa.text("UPDATE missions SET status='CANCELLED', cancelled_at=:t, updated_at=:t WHERE id=:m"),
                         {"t": t, "m": mid})
            bind.execute(sa.text("INSERT INTO mission_audit (mission_id,user_id,from_status,to_status,ts,reason) "
                                 "VALUES (:m,'migration-0006',:s,'CANCELLED',:t,:r)"),
                         {"m": mid, "s": status, "t": t, "r": f"closed: newer active mission on the same {col.split('_')[1]}"})
    where = sa.text(ACTIVE.format(t=""))
    for name, col in UNIQUE_ACTIVE:  # the check in create_mission can race; these cannot
        op.create_index(name, "missions", [col], unique=True, sqlite_where=where, postgresql_where=where)
    op.create_table("pairing_codes",
        sa.Column("user_id", sa.Text, primary_key=True), sa.Column("code_hash", sa.Text, nullable=False, unique=True),
        sa.Column("expires_at", sa.Text, nullable=False),
        sa.Column("failures", sa.Integer, nullable=False, server_default="0"))
    op.create_table("rate_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("bucket", sa.Text, nullable=False), sa.Column("at", sa.Float, nullable=False))
    op.create_index("ix_rate_events_bucket_at", "rate_events", ["bucket", "at"])
    op.create_table("sms_audit",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("mission_id", sa.Text, nullable=False), sa.Column("driver_id", sa.Text, nullable=False),
        sa.Column("event", sa.Text, nullable=False), sa.Column("result", sa.Text, nullable=False),
        sa.Column("ts", sa.Text, nullable=False))


def downgrade():
    op.drop_table("sms_audit")
    op.drop_index("ix_rate_events_bucket_at", "rate_events")
    op.drop_table("rate_events")
    op.drop_table("pairing_codes")
    for name, _ in UNIQUE_ACTIVE:
        op.drop_index(name, "missions")
    with op.batch_alter_table("mission_audit") as b:
        for c in ("on_behalf_of", "reason", "event_time"):
            b.drop_column(c)
    with op.batch_alter_table("missions") as b:
        for c in ["acknowledged_at"] + [f"{s.lower()}_at" for s in STEPS]:
            b.drop_column(c)
    with op.batch_alter_table("vehicle_pings") as b:
        b.drop_column("accuracy")
    op.drop_index("ux_vehicles_driver", "vehicles")
    with op.batch_alter_table("vehicles") as b:
        b.drop_column("driver_id")
    with op.batch_alter_table("drivers") as b:
        b.drop_column("phone")
    with op.batch_alter_table("users") as b:
        b.drop_column("admin")

"""initial schema"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    # TEXT ids/timestamps for SQLite dev; on Postgres use uuid/timestamptz and geography(Point).
    op.create_table("users",
        sa.Column("id", sa.Text, primary_key=True), sa.Column("name", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False), sa.Column("token_hash", sa.Text, nullable=False, unique=True))
    op.create_table("vehicles",
        sa.Column("id", sa.Text, primary_key=True), sa.Column("operator", sa.Text, nullable=False),
        sa.Column("registration", sa.Text, nullable=False, unique=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()))
    op.create_table("drivers",
        sa.Column("id", sa.Text, primary_key=True), sa.Column("name", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False, unique=True))
    op.create_table("missions",
        sa.Column("id", sa.Text, primary_key=True), sa.Column("status", sa.Text, nullable=False),
        sa.Column("pickup_address", sa.Text, nullable=False),
        sa.Column("assigned_vehicle_id", sa.Text, sa.ForeignKey("vehicles.id")),
        sa.Column("assigned_driver_id", sa.Text, sa.ForeignKey("drivers.id")),
        sa.Column("created_at", sa.Text, nullable=False), sa.Column("updated_at", sa.Text, nullable=False))
    op.create_table("vehicle_pings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.Text, nullable=False), sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lng", sa.Float, nullable=False), sa.Column("ts", sa.Text, nullable=False))
    op.create_index("ix_pings_vehicle_ts", "vehicle_pings", ["vehicle_id", "ts"])
    op.create_table("mission_audit",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("mission_id", sa.Text, sa.ForeignKey("missions.id"), nullable=False),
        sa.Column("user_id", sa.Text, nullable=False), sa.Column("from_status", sa.Text),
        sa.Column("to_status", sa.Text, nullable=False), sa.Column("ts", sa.Text, nullable=False))


def downgrade():
    for t in ("mission_audit", "vehicle_pings", "missions", "drivers", "vehicles", "users"):
        op.drop_table(t)

"""auth_audit (who rotated/revoked/created which credential) and indexes for the hot lookups"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade():
    op.create_table("auth_audit",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.Text, nullable=False), sa.Column("target_user_id", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False), sa.Column("ts", sa.Text, nullable=False))
    op.create_index("ix_missions_driver_status", "missions", ["assigned_driver_id", "status"])
    op.create_index("ix_audit_mission", "mission_audit", ["mission_id"])


def downgrade():
    op.drop_index("ix_audit_mission", "mission_audit")
    op.drop_index("ix_missions_driver_status", "missions")
    op.drop_table("auth_audit")

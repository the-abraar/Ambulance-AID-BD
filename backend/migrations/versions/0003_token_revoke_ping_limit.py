"""users.revoked_at (token revocation) and ping_limit (rate limit shared across workers)"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    op.add_column("users", sa.Column("revoked_at", sa.Text))
    op.create_table("ping_limit",
        sa.Column("vehicle_id", sa.Text, primary_key=True), sa.Column("last_at", sa.Float, nullable=False))


def downgrade():
    op.drop_table("ping_limit")
    with op.batch_alter_table("users") as b:
        b.drop_column("revoked_at")

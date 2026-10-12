"""users.token_expires_at; existing tokens get the standard lifetime from the day of this migration"""
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
TTL_DAYS = 90  # keep equal to app.db.TOKEN_TTL_DAYS


def upgrade():
    op.add_column("users", sa.Column("token_expires_at", sa.Text))
    exp = (datetime.now(timezone.utc) + timedelta(days=TTL_DAYS)).isoformat(timespec="microseconds")
    op.get_bind().execute(sa.text("UPDATE users SET token_expires_at=:e"), {"e": exp})


def downgrade():
    with op.batch_alter_table("users") as b:
        b.drop_column("token_expires_at")

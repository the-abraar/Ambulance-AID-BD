"""pickup_lat / pickup_lng on missions (nullable; existing rows keep NULL)"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.add_column("missions", sa.Column("pickup_lat", sa.Float))
    op.add_column("missions", sa.Column("pickup_lng", sa.Float))


def downgrade():
    with op.batch_alter_table("missions") as b:
        b.drop_column("pickup_lat")
        b.drop_column("pickup_lng")

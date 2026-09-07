"""Persist structured multi-backend capability snapshots."""

import sqlalchemy as sa

from alembic import op

revision = "0004_hardware_capabilities"
down_revision = "0003_remove_artifact_fingerprint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("runtime_capabilities")}
    if "hardware_json" not in columns:
        op.add_column("runtime_capabilities", sa.Column("hardware_json", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("runtime_capabilities") as batch:
        batch.drop_column("hardware_json")

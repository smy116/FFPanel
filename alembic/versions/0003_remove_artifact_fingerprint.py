"""Remove the SHA-256 fingerprint from transcoded artifacts."""

import sqlalchemy as sa

from alembic import op

revision = "0003_remove_artifact_fingerprint"
down_revision = "0002_add_ffmpeg_output"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("task_files")}
    if "artifact_fingerprint" not in columns:
        return
    with op.batch_alter_table("task_files") as batch_op:
        batch_op.drop_column("artifact_fingerprint")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("task_files")}
    if "artifact_fingerprint" in columns:
        return
    with op.batch_alter_table("task_files") as batch_op:
        batch_op.add_column(sa.Column("artifact_fingerprint", sa.String(length=200), nullable=True))

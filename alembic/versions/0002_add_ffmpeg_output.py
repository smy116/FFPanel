"""Persist the FFmpeg diagnostic output for each task file."""

import sqlalchemy as sa

from alembic import op

revision = "0002_add_ffmpeg_output"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial migration creates tables from the current metadata. Guard this
    # migration so a fresh database does not try to add the column twice.
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("task_files")}
    if "ffmpeg_output" not in columns:
        op.add_column("task_files", sa.Column("ffmpeg_output", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("task_files", "ffmpeg_output")

"""Initial FFPanel schema."""

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_json", sa.JSON(), nullable=False),
        sa.Column("destination_json", sa.JSON(), nullable=False),
        sa.Column("requested_params_json", sa.JSON(), nullable=False),
        sa.Column("companion_file_policy", sa.String(length=32), nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=False),
        sa.Column("completed_files", sa.Integer(), nullable=False),
        sa.Column("failed_files", sa.Integer(), nullable=False),
        sa.Column("skipped_files", sa.Integer(), nullable=False),
        sa.Column("companion_total", sa.Integer(), nullable=False),
        sa.Column("companion_completed", sa.Integer(), nullable=False),
        sa.Column("companion_failed", sa.Integer(), nullable=False),
        sa.Column("current_transcode_file_id", sa.String(length=36), nullable=True),
        sa.Column("current_upload_file_id", sa.String(length=36), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("stop_requested", sa.Boolean(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("interrupted_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_created_at", "tasks", ["created_at"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    op.create_table(
        "runtime_capabilities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ffmpeg_version", sa.Text(), nullable=True),
        sa.Column("ffprobe_available", sa.Boolean(), nullable=False),
        sa.Column("rclone_available", sa.Boolean(), nullable=False),
        sa.Column("mpp_available", sa.Boolean(), nullable=False),
        sa.Column("rga_available", sa.Boolean(), nullable=False),
        sa.Column("encoders_json", sa.JSON(), nullable=False),
        sa.Column("decoders_json", sa.JSON(), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("devices_json", sa.JSON(), nullable=False),
        sa.Column("hardware_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "task_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("previous_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_attempts_task_id", "task_attempts", ["task_id"])

    op.create_table(
        "companion_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("source_size", sa.Integer(), nullable=True),
        sa.Column("source_mtime_ns", sa.Integer(), nullable=True),
        sa.Column("final_output_path", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_companion_files_stage", "companion_files", ["stage"])
    op.create_index("ix_companion_files_task_id", "companion_files", ["task_id"])
    op.create_index("ix_companion_queue", "companion_files", ["stage", "created_at"])

    op.create_table(
        "task_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("source_size", sa.Integer(), nullable=True),
        sa.Column("source_mtime_ns", sa.Integer(), nullable=True),
        sa.Column("source_params_json", sa.JSON(), nullable=True),
        sa.Column("effective_params_json", sa.JSON(), nullable=True),
        sa.Column("decision_log_json", sa.JSON(), nullable=True),
        sa.Column("ffmpeg_argv_json", sa.JSON(), nullable=True),
        sa.Column("ffmpeg_output", sa.Text(), nullable=True),
        sa.Column("input_cache_path", sa.Text(), nullable=True),
        sa.Column("temp_output_path", sa.Text(), nullable=True),
        sa.Column("completed_artifact_path", sa.Text(), nullable=True),
        sa.Column("final_output_path", sa.Text(), nullable=True),
        sa.Column("artifact_size", sa.Integer(), nullable=True),
        sa.Column("progress_json", sa.JSON(), nullable=True),
        sa.Column("capability_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_exit_code", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transcode_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_files_queue", "task_files", ["stage", "created_at"])
    op.create_index("ix_task_files_stage", "task_files", ["stage"])
    op.create_index("ix_task_files_task_id", "task_files", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_files_task_id", table_name="task_files")
    op.drop_index("ix_task_files_stage", table_name="task_files")
    op.drop_index("ix_task_files_queue", table_name="task_files")
    op.drop_table("task_files")
    op.drop_index("ix_companion_queue", table_name="companion_files")
    op.drop_index("ix_companion_files_task_id", table_name="companion_files")
    op.drop_index("ix_companion_files_stage", table_name="companion_files")
    op.drop_table("companion_files")
    op.drop_index("ix_task_attempts_task_id", table_name="task_attempts")
    op.drop_table("task_attempts")
    op.drop_table("runtime_capabilities")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_created_at", table_name="tasks")
    op.drop_table("tasks")


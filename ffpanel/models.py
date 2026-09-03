from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class TaskStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    STOPPED = "stopped"
    INTERRUPTED = "interrupted"


class FileStage(str, enum.Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROBING = "probing"
    TRANSCODING = "transcoding"
    UPLOAD_QUEUED = "upload_queued"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    SKIPPED = "skipped"


class CompanionStage(str, enum.Enum):
    PENDING = "pending"
    COPYING = "copying"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    SKIPPED = "skipped"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.QUEUED.value, index=True)
    source_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    destination_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    requested_params_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    companion_file_policy: Mapped[str] = mapped_column(String(32), default="subtitles")
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    completed_files: Mapped[int] = mapped_column(Integer, default=0)
    failed_files: Mapped[int] = mapped_column(Integer, default=0)
    skipped_files: Mapped[int] = mapped_column(Integer, default=0)
    companion_total: Mapped[int] = mapped_column(Integer, default=0)
    companion_completed: Mapped[int] = mapped_column(Integer, default=0)
    companion_failed: Mapped[int] = mapped_column(Integer, default=0)
    current_transcode_file_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_upload_file_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    interrupted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    files: Mapped[list[TaskFile]] = relationship(back_populates="task", cascade="all, delete-orphan")
    companions: Mapped[list[CompanionFile]] = relationship(back_populates="task", cascade="all, delete-orphan")
    attempts: Mapped[list[TaskAttempt]] = relationship(back_populates="task", cascade="all, delete-orphan")


class TaskFile(Base):
    __tablename__ = "task_files"
    __table_args__ = (Index("ix_task_files_queue", "stage", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    relative_path: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(32), default=FileStage.PENDING.value, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    source_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_mtime_ns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_params_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    effective_params_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    decision_log_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    ffmpeg_argv_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    input_cache_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    temp_output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_fingerprint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    progress_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    capability_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transcode_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    task: Mapped[Task] = relationship(back_populates="files")


class CompanionFile(Base):
    __tablename__ = "companion_files"
    __table_args__ = (Index("ix_companion_queue", "stage", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    relative_path: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32))
    stage: Mapped[str] = mapped_column(String(32), default=CompanionStage.PENDING.value, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    source_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_mtime_ns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    task: Mapped[Task] = relationship(back_populates="companions")


class TaskAttempt(Base):
    __tablename__ = "task_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(32), default="create")
    previous_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[Task] = relationship(back_populates="attempts")


class RuntimeCapability(Base):
    __tablename__ = "runtime_capabilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ffmpeg_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    ffprobe_available: Mapped[bool] = mapped_column(Boolean, default=False)
    rclone_available: Mapped[bool] = mapped_column(Boolean, default=False)
    mpp_available: Mapped[bool] = mapped_column(Boolean, default=False)
    rga_available: Mapped[bool] = mapped_column(Boolean, default=False)
    encoders_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    decoders_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    filters_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    devices_json: Mapped[dict[str, bool]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


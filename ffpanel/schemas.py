from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from .models import CompanionStage, FileStage, TaskStatus


class APIModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class StorageKind(str, Enum):
    LOCAL = "local"
    RCLONE = "rclone"


class StorageLocation(APIModel):
    kind: StorageKind
    path: str
    remote: str | None = None

    @model_validator(mode="after")
    def require_remote(self) -> StorageLocation:
        if self.kind == StorageKind.RCLONE and not self.remote:
            raise ValueError("远程存储必须选择 remote")
        if self.kind == StorageKind.LOCAL and self.remote:
            raise ValueError("本地存储不能包含 remote")
        return self


class CompanionFilePolicy(str, Enum):
    NONE = "none"
    SUBTITLES = "subtitles"
    ALL_NON_VIDEO = "all_non_video"


HardwareMode = Literal["mpp_mpp", "cpu_mpp", "cpu_cpu"]
VideoCodec = Literal["h264", "hevc"]
Container = Literal["mp4", "mkv"]
FrameRate = Literal["source", "24", "25", "30", "50", "60"]
AudioStrategy = Literal["copy", "aac", "drop"]
SubtitleStrategy = Literal["auto", "copy", "drop"]


class TranscodeParams(APIModel):
    hardware_mode: HardwareMode = "mpp_mpp"
    auto_fallback: bool = True
    video_codec: VideoCodec = "hevc"
    container: Container = "mp4"
    height: Literal[-1, 360, 480, 720, 1080, 2160] = 720
    bitrate_kbps: int = Field(default=2000, ge=100, le=100_000)
    smart_bitrate_cap: bool = True
    frame_rate: FrameRate = "source"
    gop: int = Field(default=120, ge=1, le=600)
    audio_strategy: AudioStrategy = "copy"
    subtitle_strategy: SubtitleStrategy = "auto"


class BrowseRequest(APIModel):
    location: StorageLocation


class ScanRequest(APIModel):
    source: StorageLocation
    companion_file_policy: CompanionFilePolicy = CompanionFilePolicy.SUBTITLES


class ScanSummary(APIModel):
    scan_token: str
    video_count: int
    subtitle_count: int
    other_count: int
    companion_count: int
    total_bytes: int
    expires_at: datetime


class CreateTaskRequest(APIModel):
    name: str | None = Field(default=None, max_length=200)
    source: StorageLocation
    destination: StorageLocation
    scan_token: str
    companion_file_policy: CompanionFilePolicy = CompanionFilePolicy.SUBTITLES
    params: TranscodeParams


class ParameterReason(APIModel):
    field: str
    code: str
    message: str


class ParameterDecision(APIModel):
    source: dict[str, Any] | None
    requested: dict[str, Any] | None
    effective: dict[str, Any] | None
    reasons: list[ParameterReason]
    ffmpeg_argv: list[str] | None = None


class TranscodeProgress(APIModel):
    task_id: str
    file_id: str
    stage: Literal["transcoding"] = "transcoding"
    frame: int | None = None
    fps: float | None = None
    bitrate_kbps: float | None = None
    out_time_ms: int | None = None
    total_size_bytes: int | None = None
    speed: float | None = None
    percent: float | None = None
    eta_seconds: int | None = None
    progress: Literal["continue", "end"] = "continue"
    updated_at: datetime


class ErrorResponse(APIModel):
    code: str
    message: str
    details: Any | None = None
    request_id: str | None = None


class BrowseEntryResponse(APIModel):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    modified_at: datetime | None = None


class BrowseResponse(APIModel):
    items: list[BrowseEntryResponse]


class RemotesResponse(APIModel):
    items: list[str]
    available: bool
    config_path: str


class TaskFileResponse(APIModel):
    id: str
    task_id: str
    relative_path: str
    stage: FileStage
    attempt: int
    source_size: int | None = None
    final_output_path: str | None = None
    artifact_size: int | None = None
    progress: TranscodeProgress | None = None
    parameter_decision: ParameterDecision | None = None
    ffmpeg_output: str | None = None
    last_error: str | None = None
    last_exit_code: int | None = None
    version: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime


class CompanionFileResponse(APIModel):
    id: str
    task_id: str
    relative_path: str
    category: str
    stage: CompanionStage
    attempt: int
    source_size: int | None = None
    final_output_path: str | None = None
    last_error: str | None = None
    version: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime


class TaskResponse(APIModel):
    id: str
    name: str
    status: TaskStatus
    source: StorageLocation
    destination: StorageLocation
    requested_params: TranscodeParams
    companion_file_policy: CompanionFilePolicy
    total_files: int
    completed_files: int
    failed_files: int
    skipped_files: int
    companion_total: int
    companion_completed: int
    companion_failed: int
    percent: float
    current_transcode_file_id: str | None = None
    current_upload_file_id: str | None = None
    active_transcode_file: TaskFileResponse | None = None
    active_upload_file: TaskFileResponse | CompanionFileResponse | None = None
    upload_queued: int = 0
    retry_count: int
    last_error: str | None = None
    interrupted_reason: str | None = None
    version: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime


class RuntimeStatusResponse(APIModel):
    ffmpeg_version: str | None = None
    ffprobe_available: bool
    rclone_available: bool
    mpp_available: bool
    rga_available: bool
    encoders: list[str]
    decoders: list[str]
    filters: list[str]
    devices: dict[str, bool]
    error: str | None = None
    transcode_slot: int
    upload_slot: int
    upload_queued: int
    cpu_percent: float
    memory_percent: float


class MetricsResponse(APIModel):
    queued_tasks: int
    completed_tasks: int
    completed_videos: int
    source_bytes: int
    output_bytes: int


class SnapshotResponse(APIModel):
    tasks: list[TaskResponse]
    system: RuntimeStatusResponse
    metrics: MetricsResponse


class TaskFilesResponse(APIModel):
    items: list[TaskFileResponse]
    total: int
    offset: int
    limit: int


class CompanionFilesResponse(APIModel):
    items: list[CompanionFileResponse]
    total: int
    offset: int
    limit: int


class LogEntryResponse(APIModel):
    level: str
    message: str
    file_id: str | None = None
    created_at: datetime


class LogsResponse(APIModel):
    items: list[LogEntryResponse]
    limit: int

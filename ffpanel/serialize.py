from __future__ import annotations

from typing import Any

from .models import CompanionFile, RuntimeCapability, Task, TaskFile


def iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def task_dict(task: Task) -> dict[str, Any]:
    total_terminal = task.completed_files + task.failed_files + task.skipped_files
    percent = round(total_terminal / task.total_files * 100, 1) if task.total_files else 0.0
    return {
        "id": task.id,
        "name": task.name,
        "status": task.status,
        "source": task.source_json,
        "destination": task.destination_json,
        "requestedParams": task.requested_params_json,
        "companionFilePolicy": task.companion_file_policy,
        "totalFiles": task.total_files,
        "completedFiles": task.completed_files,
        "failedFiles": task.failed_files,
        "skippedFiles": task.skipped_files,
        "companionTotal": task.companion_total,
        "companionCompleted": task.companion_completed,
        "companionFailed": task.companion_failed,
        "percent": percent,
        "currentTranscodeFileId": task.current_transcode_file_id,
        "currentUploadFileId": task.current_upload_file_id,
        "retryCount": task.retry_count,
        "lastError": task.last_error,
        "interruptedReason": task.interrupted_reason,
        "version": task.version,
        "createdAt": iso(task.created_at),
        "startedAt": iso(task.started_at),
        "finishedAt": iso(task.finished_at),
        "updatedAt": iso(task.updated_at),
    }


def file_dict(item: TaskFile, *, include_decision: bool = True) -> dict[str, Any]:
    value = {
        "id": item.id,
        "taskId": item.task_id,
        "relativePath": item.relative_path,
        "stage": item.stage,
        "attempt": item.attempt,
        "sourceSize": item.source_size,
        "finalOutputPath": item.final_output_path,
        "artifactSize": item.artifact_size,
        "progress": item.progress_json,
        "ffmpegOutput": item.ffmpeg_output,
        "lastError": item.last_error,
        "lastExitCode": item.last_exit_code,
        "version": item.version,
        "startedAt": iso(item.started_at),
        "finishedAt": iso(item.finished_at),
        "updatedAt": iso(item.updated_at),
    }
    if include_decision:
        value["parameterDecision"] = {
            "source": item.source_params_json,
            "requested": item.task.requested_params_json if item.task else None,
            "effective": item.effective_params_json,
            "reasons": item.decision_log_json or [],
            "ffmpegArgv": item.ffmpeg_argv_json,
        } if item.source_params_json else None
    return value


def companion_dict(item: CompanionFile) -> dict[str, Any]:
    return {
        "id": item.id,
        "taskId": item.task_id,
        "relativePath": item.relative_path,
        "category": item.category,
        "stage": item.stage,
        "attempt": item.attempt,
        "sourceSize": item.source_size,
        "finalOutputPath": item.final_output_path,
        "lastError": item.last_error,
        "version": item.version,
        "startedAt": iso(item.started_at),
        "finishedAt": iso(item.finished_at),
        "updatedAt": iso(item.updated_at),
    }


def capability_dict(item: RuntimeCapability | None) -> dict[str, Any]:
    if item is None:
        return {
            "ffmpegVersion": None, "ffprobeAvailable": False, "rcloneAvailable": False,
            "mppAvailable": False, "rgaAvailable": False, "encoders": [], "decoders": [],
            "filters": [], "devices": {}, "error": "能力检测尚未完成",
        }
    return {
        "id": item.id,
        "ffmpegVersion": item.ffmpeg_version,
        "ffprobeAvailable": item.ffprobe_available,
        "rcloneAvailable": item.rclone_available,
        "mppAvailable": item.mpp_available,
        "rgaAvailable": item.rga_available,
        "encoders": item.encoders_json,
        "decoders": item.decoders_json,
        "filters": item.filters_json,
        "devices": item.devices_json,
        "error": item.error,
        "createdAt": iso(item.created_at),
    }


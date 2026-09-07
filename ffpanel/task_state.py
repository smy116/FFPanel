from __future__ import annotations

from .models import CompanionStage, FileStage, Task, TaskStatus, utcnow


def update_task_summary(task: Task, *, pending_status: TaskStatus = TaskStatus.RUNNING) -> None:
    """Derive task counters and status from the current file states before committing."""
    task.completed_files = sum(item.stage == FileStage.COMPLETED.value for item in task.files)
    task.failed_files = sum(item.stage == FileStage.FAILED.value for item in task.files)
    task.skipped_files = sum(item.stage == FileStage.SKIPPED.value for item in task.files)
    task.companion_completed = sum(
        item.stage == CompanionStage.COMPLETED.value for item in task.companions
    )
    task.companion_failed = sum(
        item.stage == CompanionStage.FAILED.value for item in task.companions
    )
    video_done = all(item.stage in {"completed", "failed", "skipped"} for item in task.files)
    companion_done = all(
        item.stage in {"completed", "failed", "skipped"} for item in task.companions
    )
    if task.stop_requested:
        task.status = TaskStatus.STOPPED.value
    elif video_done and companion_done:
        failures = task.failed_files + task.companion_failed
        successes = task.completed_files + task.companion_completed
        if failures:
            task.status = TaskStatus.PARTIAL_FAILED.value if successes else TaskStatus.FAILED.value
        else:
            task.status = TaskStatus.COMPLETED.value
        task.finished_at = task.finished_at or utcnow()
    else:
        task.status = pending_status.value
        task.finished_at = None
    errors = [item.last_error for item in task.files if item.last_error]
    errors.extend(item.last_error for item in task.companions if item.last_error)
    task.last_error = next(iter(errors), None)

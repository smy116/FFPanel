from __future__ import annotations

import asyncio
import shutil
from collections.abc import AsyncIterator, Generator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .models import (
    CompanionFile,
    CompanionStage,
    FileStage,
    Task,
    TaskAttempt,
    TaskFile,
    TaskStatus,
)
from .schemas import (
    BrowseRequest,
    BrowseResponse,
    CompanionFilesResponse,
    CreateTaskRequest,
    ErrorResponse,
    LogsResponse,
    RemotesResponse,
    ScanRequest,
    ScanSummary,
    SnapshotResponse,
    StorageKind,
    StorageLocation,
    TaskFilesResponse,
    TaskResponse,
)
from .serialize import companion_dict, file_dict, task_dict
from .storage import StorageError, StorageService, companion_selected

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "需要身份认证"},
    404: {"model": ErrorResponse, "description": "资源不存在"},
    409: {"model": ErrorResponse, "description": "状态或输出冲突"},
    422: {"model": ErrorResponse, "description": "参数或存储请求无效"},
    503: {"model": ErrorResponse, "description": "数据库或依赖暂不可用"},
}
router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)


def get_db(request: Request) -> Generator[Session, None, None]:
    factory = request.app.state.sessions
    with factory() as session:
        yield session


def get_task_or_404(session: Session, task_id: str) -> Task:
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "任务不存在"})
    return task


@router.get("/remotes", response_model=RemotesResponse)
async def remotes(request: Request) -> dict[str, Any]:
    values = await request.app.state.storage.list_remotes()
    return {"items": values, "available": bool(values), "configPath": str(request.app.state.settings.rclone_config)}


@router.post("/storage/browse", response_model=BrowseResponse)
async def browse(payload: BrowseRequest, request: Request) -> dict[str, Any]:
    return {"items": await request.app.state.storage.browse(payload.location)}


@router.post("/storage/scan", response_model=ScanSummary, response_model_by_alias=True)
async def scan(payload: ScanRequest, request: Request) -> ScanSummary:
    entries = await request.app.state.storage.scan(payload.source)
    videos = [entry for entry in entries if entry.category == "video"]
    if not videos:
        raise HTTPException(status_code=422, detail={"code": "no_videos", "message": "输入位置未找到支持的视频文件"})
    record = request.app.state.scans.put(payload.source, payload.companion_file_policy, entries)
    subtitles = sum(entry.category == "subtitle" for entry in entries)
    others = sum(entry.category == "other" for entry in entries)
    companions = sum(companion_selected(entry, payload.companion_file_policy) for entry in entries)
    return ScanSummary(
        scan_token=record.token,
        video_count=len(videos),
        subtitle_count=subtitles,
        other_count=others,
        companion_count=companions,
        total_bytes=sum(entry.size or 0 for entry in entries),
        expires_at=record.expires_at,
    )


@router.post("/tasks", status_code=201, response_model=TaskResponse)
async def create_task(payload: CreateTaskRequest, request: Request, session: Session = Depends(get_db)) -> dict[str, Any]:
    storage = request.app.state.storage
    if _locations_equal(payload.source, payload.destination, storage):
        raise HTTPException(status_code=409, detail={"code": "same_source_destination", "message": "输入和输出位置不能相同"})
    record = request.app.state.scans.consume(payload.scan_token, payload.source, payload.companion_file_policy)
    videos = [entry for entry in record.entries if entry.category == "video"]
    companions = [entry for entry in record.entries if companion_selected(entry, payload.companion_file_policy)]
    default_name = Path(payload.source.path.rstrip("/\\")).name or payload.source.remote or "转码任务"
    task = Task(
        name=payload.name.strip() if payload.name and payload.name.strip() else default_name,
        source_json=payload.source.model_dump(mode="json", by_alias=True),
        destination_json=payload.destination.model_dump(mode="json", by_alias=True),
        requested_params_json=payload.params.model_dump(mode="json", by_alias=True),
        companion_file_policy=payload.companion_file_policy,
        total_files=len(videos),
        companion_total=len(companions),
    )
    task.files = [
        TaskFile(relative_path=entry.relative_path, source_size=entry.size, source_mtime_ns=entry.mtime_ns)
        for entry in videos
    ]
    task.companions = [
        CompanionFile(relative_path=entry.relative_path, category=entry.category, source_size=entry.size, source_mtime_ns=entry.mtime_ns)
        for entry in companions
    ]
    task.attempts = [TaskAttempt(attempt=1, trigger="create")]
    session.add(task)
    session.commit()
    session.refresh(task)
    result = task_dict(task)
    await request.app.state.events.publish("task.state", result, task_id=task.id, version=task.version)
    return result


@router.get("/snapshot", response_model=SnapshotResponse)
async def snapshot(request: Request, session: Session = Depends(get_db)) -> dict[str, Any]:
    order = case(
        (Task.status == TaskStatus.RUNNING.value, 0),
        (Task.status == TaskStatus.QUEUED.value, 1),
        (Task.status.in_([TaskStatus.INTERRUPTED.value, TaskStatus.PARTIAL_FAILED.value, TaskStatus.FAILED.value]), 2),
        else_=3,
    )
    tasks = session.scalars(select(Task).order_by(order, Task.created_at.desc())).all()
    values = [_task_with_activity(task, session) for task in tasks]
    total_source = session.scalar(select(func.sum(TaskFile.source_size)).where(TaskFile.stage == FileStage.COMPLETED.value)) or 0
    total_output = session.scalar(select(func.sum(TaskFile.artifact_size)).where(TaskFile.stage == FileStage.COMPLETED.value)) or 0
    return {
        "tasks": values,
        "system": request.app.state.scheduler.system_status(),
        "metrics": {
            "queuedTasks": sum(task.status == TaskStatus.QUEUED.value for task in tasks),
            "completedTasks": sum(task.status == TaskStatus.COMPLETED.value for task in tasks),
            "completedVideos": sum(task.completed_files for task in tasks),
            "sourceBytes": int(total_source),
            "outputBytes": int(total_output),
        },
    }


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def task_detail(task_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    return _task_with_activity(get_task_or_404(session, task_id), session)


@router.get("/tasks/{task_id}/files", response_model=TaskFilesResponse)
async def task_files(
    task_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    get_task_or_404(session, task_id)
    total = session.scalar(select(func.count()).select_from(TaskFile).where(TaskFile.task_id == task_id)) or 0
    items = session.scalars(select(TaskFile).where(TaskFile.task_id == task_id).order_by(TaskFile.created_at).offset(offset).limit(limit)).all()
    return {"items": [file_dict(item) for item in items], "total": total, "offset": offset, "limit": limit}


@router.get("/tasks/{task_id}/companions", response_model=CompanionFilesResponse)
async def task_companions(
    task_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    get_task_or_404(session, task_id)
    total = session.scalar(select(func.count()).select_from(CompanionFile).where(CompanionFile.task_id == task_id)) or 0
    items = session.scalars(select(CompanionFile).where(CompanionFile.task_id == task_id).order_by(CompanionFile.created_at).offset(offset).limit(limit)).all()
    return {"items": [companion_dict(item) for item in items], "total": total, "offset": offset, "limit": limit}


@router.get("/tasks/{task_id}/logs", response_model=LogsResponse)
async def task_logs(task_id: str, request: Request, session: Session = Depends(get_db)) -> dict[str, Any]:
    get_task_or_404(session, task_id)
    return {"items": request.app.state.events.recent_logs(task_id), "limit": 300}


@router.post("/tasks/{task_id}/stop", response_model=TaskResponse)
async def stop_task(task_id: str, request: Request, session: Session = Depends(get_db)) -> dict[str, Any]:
    get_task_or_404(session, task_id)
    await request.app.state.scheduler.stop_task(task_id)
    with request.app.state.sessions() as fresh:
        return task_dict(get_task_or_404(fresh, task_id))


@router.post("/tasks/{task_id}/retry", response_model=TaskResponse)
async def retry_task(task_id: str, request: Request, session: Session = Depends(get_db)) -> dict[str, Any]:
    task = get_task_or_404(session, task_id)
    if task.status not in {TaskStatus.INTERRUPTED.value, TaskStatus.FAILED.value, TaskStatus.PARTIAL_FAILED.value, TaskStatus.STOPPED.value}:
        raise HTTPException(status_code=409, detail={"code": "task_not_retryable", "message": "当前任务状态不能 Retry"})
    previous_error = task.last_error or task.interrupted_reason
    task.retry_count += 1
    task.stop_requested = False
    task.status = TaskStatus.QUEUED.value
    task.last_error = None
    task.interrupted_reason = None
    task.finished_at = None
    task.current_transcode_file_id = None
    task.current_upload_file_id = None
    task.version += 1
    task.attempts.append(TaskAttempt(attempt=task.retry_count + 1, trigger="retry", previous_error=previous_error))
    destination = StorageLocation.model_validate(task.destination_json)
    for item in task.files:
        if item.stage == FileStage.COMPLETED.value:
            continue
        if item.final_output_path and item.artifact_size is not None:
            final_stat = await request.app.state.storage.stat(destination, item.final_output_path)
            if final_stat and final_stat.get("size") == item.artifact_size:
                item.stage = FileStage.COMPLETED.value
                item.finished_at = item.finished_at or task.updated_at
                item.last_error = None
                item.version += 1
                continue
            if final_stat:
                item.stage = FileStage.FAILED.value
                item.attempt += 1
                item.last_error = "最终输出已存在但校验信息不匹配，未执行覆盖"
                item.version += 1
                continue
        if item.completed_artifact_path and _artifact_valid(item):
            if destination.kind == StorageKind.RCLONE:
                item.stage = FileStage.UPLOAD_QUEUED.value
            else:
                if not item.final_output_path:
                    item.stage = FileStage.PENDING.value
                else:
                    final_path = request.app.state.storage.local_path(destination, item.final_output_path, allow_missing=True)
                    request.app.state.storage.commit_local(Path(item.completed_artifact_path), final_path)
                    item.completed_artifact_path = str(final_path)
                    item.stage = FileStage.COMPLETED.value
                    item.finished_at = task.updated_at
        else:
            if item.temp_output_path:
                _safe_unlink(Path(item.temp_output_path))
            item.stage = FileStage.PENDING.value
            item.source_params_json = None
            item.effective_params_json = None
            item.decision_log_json = None
            item.progress_json = None
        item.attempt += 1
        item.last_error = None
        item.finished_at = None
        item.version += 1
    for companion in task.companions:
        if companion.stage != CompanionStage.COMPLETED.value:
            companion.stage = CompanionStage.PENDING.value
            companion.attempt += 1
            companion.last_error = None
            companion.finished_at = None
            companion.version += 1
    pending = any(item.stage in {FileStage.PENDING.value, FileStage.UPLOAD_QUEUED.value} for item in task.files)
    pending = pending or any(item.stage == CompanionStage.PENDING.value for item in task.companions)
    if not pending:
        failures = sum(item.stage == FileStage.FAILED.value for item in task.files) + sum(
            item.stage == CompanionStage.FAILED.value for item in task.companions
        )
        successes = sum(item.stage == FileStage.COMPLETED.value for item in task.files) + sum(
            item.stage == CompanionStage.COMPLETED.value for item in task.companions
        )
        task.status = TaskStatus.PARTIAL_FAILED.value if failures and successes else TaskStatus.FAILED.value if failures else TaskStatus.COMPLETED.value
    session.commit()
    result = task_dict(task)
    await request.app.state.events.publish("task.state", result, task_id=task.id, version=task.version)
    return result


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str, request: Request, session: Session = Depends(get_db)) -> Response:
    task = get_task_or_404(session, task_id)
    await request.app.state.scheduler.stop_task(task_id)
    await asyncio.sleep(0)
    cache_root = request.app.state.settings.cache_dir / "tasks" / task_id
    session.delete(task)
    session.commit()
    if cache_root.is_dir():
        shutil.rmtree(cache_root, ignore_errors=True)
    return Response(status_code=204)


@router.get(
    "/events",
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
async def events(request: Request) -> StreamingResponse:
    bus = request.app.state.events

    async def stream() -> AsyncIterator[str]:
        async with bus.subscribe() as queue:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield bus.encode_sse(event)
                except TimeoutError:
                    yield ": keepalive\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _task_with_activity(task: Task, session: Session) -> dict[str, Any]:
    value = task_dict(task)
    transcode_file = session.get(TaskFile, task.current_transcode_file_id) if task.current_transcode_file_id else None
    value["activeTranscodeFile"] = file_dict(transcode_file, include_decision=False) if transcode_file else None
    upload_file = session.get(TaskFile, task.current_upload_file_id) if task.current_upload_file_id else None
    upload_companion = session.get(CompanionFile, task.current_upload_file_id) if task.current_upload_file_id and not upload_file else None
    value["activeUploadFile"] = file_dict(upload_file, include_decision=False) if upload_file else companion_dict(upload_companion) if upload_companion else None
    value["uploadQueued"] = session.scalar(select(func.count()).select_from(TaskFile).where(TaskFile.task_id == task.id, TaskFile.stage == FileStage.UPLOAD_QUEUED.value)) or 0
    return value


def _locations_equal(source: StorageLocation, destination: StorageLocation, storage: StorageService) -> bool:
    if source.kind != destination.kind:
        return False
    if source.kind == StorageKind.LOCAL:
        try:
            return storage.validate_local(source.path, allow_missing=True) == storage.validate_local(destination.path, allow_missing=True)
        except StorageError:
            return source.path == destination.path
    return bool(source.remote == destination.remote and source.path.strip("/") == destination.path.strip("/"))


def _artifact_valid(item: TaskFile) -> bool:
    if not item.completed_artifact_path:
        return False
    path = Path(item.completed_artifact_path)
    if not path.is_file() or (item.artifact_size is not None and path.stat().st_size != item.artifact_size):
        return False
    if item.artifact_fingerprint and item.artifact_fingerprint.startswith("sha256:"):
        import hashlib

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == item.artifact_fingerprint.removeprefix("sha256:")
    return True


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass

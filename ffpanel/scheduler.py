from __future__ import annotations

import asyncio
import contextlib
import hashlib
import shutil
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import psutil
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .events import EventBus
from .media import (
    CapabilitySnapshot,
    MediaError,
    build_ffmpeg_argv,
    decide_parameters,
    detect_capabilities,
    parse_progress_block,
    probe_media,
)
from .models import (
    CompanionFile,
    CompanionStage,
    FileStage,
    RuntimeCapability,
    Task,
    TaskFile,
    TaskStatus,
    utcnow,
)
from .schemas import HardwareMode, StorageKind, StorageLocation, TranscodeParams
from .serialize import companion_dict, file_dict, task_dict
from .storage import StorageError, StorageService

ACTIVE_TASK_STATUSES = {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value}
TERMINAL_FILE_STAGES = {FileStage.COMPLETED.value, FileStage.FAILED.value, FileStage.SKIPPED.value}
TERMINAL_COMPANION_STAGES = {CompanionStage.COMPLETED.value, CompanionStage.FAILED.value, CompanionStage.SKIPPED.value}
HARDWARE_MODE_LABELS: dict[HardwareMode, str] = {
    "mpp_mpp": "Rockchip MPP 硬件编解码",
    "cpu_mpp": "CPU 软解 + MPP 编码",
    "cpu_cpu": "CPU 软件编解码",
}
HARDWARE_FALLBACK_CHAINS: dict[HardwareMode, tuple[HardwareMode, ...]] = {
    "mpp_mpp": ("mpp_mpp", "cpu_mpp", "cpu_cpu"),
    "cpu_mpp": ("cpu_mpp", "cpu_cpu"),
    "cpu_cpu": ("cpu_cpu",),
}


def transcode_mode_chain(params: TranscodeParams) -> tuple[HardwareMode, ...]:
    if not params.auto_fallback:
        return (params.hardware_mode,)
    return HARDWARE_FALLBACK_CHAINS[params.hardware_mode]


class Scheduler:
    def __init__(
        self,
        settings: Settings,
        sessions: sessionmaker[Session],
        storage: StorageService,
        events: EventBus,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.storage = storage
        self.events = events
        self.capabilities = CapabilitySnapshot(None, False, False, False, False, [], [], [], {}, "能力检测尚未完成")
        self.capability_id: str | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()
        self._active_transcode: tuple[str, asyncio.subprocess.Process] | None = None
        self._active_transfer: tuple[str, asyncio.subprocess.Process] | None = None
        self._transcode_busy_task_id: str | None = None
        self._transfer_busy_task_id: str | None = None
        self.storage.process_observer = self._observe_storage_process

    async def start(self) -> None:
        self.capabilities = await detect_capabilities(self.settings)
        with self.sessions() as session:
            capability = RuntimeCapability(
                ffmpeg_version=self.capabilities.ffmpeg_version,
                ffprobe_available=self.capabilities.ffprobe_available,
                rclone_available=self.capabilities.rclone_available,
                mpp_available=self.capabilities.mpp_available,
                rga_available=self.capabilities.rga_available,
                encoders_json=self.capabilities.encoders,
                decoders_json=self.capabilities.decoders,
                filters_json=self.capabilities.filters,
                devices_json=self.capabilities.devices,
                error=self.capabilities.error,
            )
            session.add(capability)
            session.commit()
            self.capability_id = capability.id
        await self.recover()
        await self.events.publish("system.status", self.system_status())
        self._tasks = [
            asyncio.create_task(self._transcode_loop(), name="ffpanel-transcode"),
            asyncio.create_task(self._transfer_loop(), name="ffpanel-transfer"),
            asyncio.create_task(self._status_loop(), name="ffpanel-status"),
        ]

    async def shutdown(self) -> None:
        self._stopping.set()
        for active in (self._active_transcode, self._active_transfer):
            if active:
                active[1].terminate()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._mark_active_interrupted("graceful_shutdown")

    def system_status(self) -> dict[str, Any]:
        return self.capabilities.as_dict() | {
            "transcodeSlot": 1 if self._transcode_busy_task_id else 0,
            "uploadSlot": 1 if self._transfer_busy_task_id else 0,
            "uploadQueued": self._upload_queued_count(),
            "cpuPercent": psutil.cpu_percent(),
            "memoryPercent": psutil.virtual_memory().percent,
        }

    async def recover(self) -> int:
        interrupted = 0
        with self.sessions() as session:
            running_tasks = session.scalars(select(Task).where(Task.status == TaskStatus.RUNNING.value)).all()
            for task in running_tasks:
                task.status = TaskStatus.INTERRUPTED.value
                task.interrupted_reason = "unclean_shutdown"
                task.current_transcode_file_id = None
                task.current_upload_file_id = None
                task.version += 1
                for item in task.files:
                    if item.stage in {FileStage.DOWNLOADING.value, FileStage.PROBING.value, FileStage.TRANSCODING.value, FileStage.UPLOADING.value}:
                        previous_stage = item.stage
                        item.stage = FileStage.INTERRUPTED.value
                        item.last_error = "FFPanel 进程退出，活动子进程已失效"
                        item.version += 1
                        if item.temp_output_path and previous_stage != FileStage.UPLOADING.value:
                            self._safe_unlink(Path(item.temp_output_path))
                for companion in task.companions:
                    if companion.stage == CompanionStage.COPYING.value:
                        companion.stage = CompanionStage.INTERRUPTED.value
                        companion.last_error = "FFPanel 进程退出，复制操作已失效"
                        companion.version += 1
                interrupted += 1
            session.commit()
        return interrupted

    async def stop_task(self, task_id: str) -> bool:
        with self.sessions() as session:
            task = session.get(Task, task_id)
            if not task:
                return False
            task.stop_requested = True
            task.status = TaskStatus.STOPPED.value
            task.finished_at = utcnow()
            task.version += 1
            session.commit()
            payload = task_dict(task)
        processes = [active[1] for active in (self._active_transcode, self._active_transfer) if active and active[0] == task_id]
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                await asyncio.wait_for(process.wait(), timeout=self.settings.stop_timeout_seconds)
            except TimeoutError:
                process.kill()
                await process.wait()
        await self.events.publish("task.state", payload, task_id=task_id, version=payload["version"])
        return True

    async def _transcode_loop(self) -> None:
        while not self._stopping.is_set():
            item_id = self._next_transcode_id()
            if not item_id:
                await asyncio.sleep(0.35)
                continue
            self._transcode_busy_task_id = self._task_id_for_file(item_id)
            try:
                await self._process_transcode(item_id)
            finally:
                self._transcode_busy_task_id = None

    async def _transfer_loop(self) -> None:
        while not self._stopping.is_set():
            target = self._next_transfer()
            if not target:
                await asyncio.sleep(0.35)
                continue
            kind, item_id = target
            self._transfer_busy_task_id = self._task_id_for_file(item_id) if kind == "video" else self._task_id_for_companion(item_id)
            try:
                if kind == "video":
                    await self._process_upload(item_id)
                else:
                    await self._process_companion(item_id)
            finally:
                self._transfer_busy_task_id = None

    async def _status_loop(self) -> None:
        while not self._stopping.is_set():
            await self.events.publish("system.status", self.system_status())
            await asyncio.sleep(5)

    def _next_transcode_id(self) -> str | None:
        with self.sessions() as session:
            items = session.scalars(
                select(TaskFile)
                .join(Task)
                .where(TaskFile.stage == FileStage.PENDING.value, Task.status.in_(ACTIVE_TASK_STATUSES), Task.stop_requested.is_(False))
                .order_by(Task.created_at, TaskFile.created_at)
            ).all()
            for item in items:
                destination = StorageLocation.model_validate(item.task.destination_json)
                if destination.kind == StorageKind.RCLONE and self._remote_output_backpressured(session):
                    continue
                return item.id
        return None

    def _next_transfer(self) -> tuple[str, str] | None:
        with self.sessions() as session:
            video = session.scalar(
                select(TaskFile)
                .join(Task)
                .where(TaskFile.stage == FileStage.UPLOAD_QUEUED.value, Task.status.in_(ACTIVE_TASK_STATUSES), Task.stop_requested.is_(False))
                .order_by(TaskFile.transcode_completed_at, TaskFile.created_at)
            )
            companion = session.scalar(
                select(CompanionFile)
                .join(Task)
                .where(CompanionFile.stage == CompanionStage.PENDING.value, Task.status.in_(ACTIVE_TASK_STATUSES), Task.stop_requested.is_(False))
                .order_by(Task.created_at, CompanionFile.created_at)
            )
            if video and companion:
                return ("video", video.id) if video.created_at <= companion.created_at else ("companion", companion.id)
            if video:
                return "video", video.id
            if companion:
                return "companion", companion.id
        return None

    def _remote_output_backpressured(self, session: Session) -> bool:
        uploading = session.scalar(select(func.count()).select_from(TaskFile).where(TaskFile.stage == FileStage.UPLOADING.value)) or 0
        queued = session.scalar(select(func.count()).select_from(TaskFile).where(TaskFile.stage == FileStage.UPLOAD_QUEUED.value)) or 0
        return uploading >= 1 and queued >= 1

    async def _process_transcode(self, item_id: str) -> None:
        try:
            with self.sessions() as session:
                item = session.get(TaskFile, item_id)
                if not item or item.stage != FileStage.PENDING.value:
                    return
                task = item.task
                source = StorageLocation.model_validate(task.source_json)
                destination = StorageLocation.model_validate(task.destination_json)
                params = TranscodeParams.model_validate(task.requested_params_json)
                task.status = TaskStatus.RUNNING.value
                task.started_at = task.started_at or utcnow()
                task.current_transcode_file_id = item.id
                task.version += 1
                item.stage = FileStage.DOWNLOADING.value if source.kind == StorageKind.RCLONE else FileStage.PROBING.value
                item.started_at = item.started_at or utcnow()
                item.version += 1
                session.commit()
                task_id, relative = task.id, item.relative_path
                await self._publish_task_and_file(task, item)

            cache_root = self.settings.cache_dir / "tasks" / task_id
            if source.kind == StorageKind.RCLONE:
                input_path = cache_root / "input" / Path(relative)
                await self.storage.download(source, relative, input_path, task_id=task_id)
                await self._set_file_stage(item_id, FileStage.PROBING.value)
            else:
                input_path = self.storage.local_path(source, relative if Path(source.path).is_dir() else "")

            source_params = await probe_media(self.settings, input_path)
            output_relative = str(PurePosixPath(relative).with_suffix(f".{params.container}"))
            if await self.storage.exists(destination, output_relative):
                raise StorageError("output_conflict", f"目标文件已存在：{output_relative}")

            if destination.kind == StorageKind.LOCAL:
                final_path = self.storage.local_path(destination, output_relative, allow_missing=True)
                final_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = final_path.with_name(f".ffpanel-{final_path.stem}-{item_id[:8]}.part{final_path.suffix}")
            else:
                final_path = None
                temp_path = cache_root / "output" / Path(output_relative)
                temp_path = temp_path.with_name(f".ffpanel-{temp_path.stem}-{item_id[:8]}.part{temp_path.suffix}")
                temp_path.parent.mkdir(parents=True, exist_ok=True)
            fallback_reasons: list[dict[str, str]] = []
            failures: list[str] = []
            modes = transcode_mode_chain(params)
            for index, mode in enumerate(modes):
                if self._task_stop_requested(task_id):
                    raise MediaError("task_stopped", "任务已停止")
                attempt_params = params.model_copy(update={"hardware_mode": mode})
                attempt_decision_reasons: list[dict[str, str]] = []
                await self._persist_transcode_attempt(
                    item_id,
                    source_params=source_params,
                    effective=None,
                    reasons=fallback_reasons,
                    argv=None,
                    input_path=input_path,
                    input_is_cached=source.kind == StorageKind.RCLONE,
                    temp_path=temp_path,
                    output_relative=output_relative,
                )
                try:
                    effective, attempt_decision_reasons = decide_parameters(
                        source_params, attempt_params, self.capabilities
                    )
                    argv = build_ffmpeg_argv(self.settings, input_path, temp_path, effective)
                    await self._persist_transcode_attempt(
                        item_id,
                        source_params=source_params,
                        effective=effective,
                        reasons=[*attempt_decision_reasons, *fallback_reasons],
                        argv=argv,
                        input_path=input_path,
                        input_is_cached=source.kind == StorageKind.RCLONE,
                        temp_path=temp_path,
                        output_relative=output_relative,
                    )
                    exit_code, stderr_tail = await self._run_ffmpeg(
                        task_id,
                        item_id,
                        argv,
                        source_params.get("durationMs"),
                        input_path,
                        temp_path,
                    )
                    await self._set_transcode_exit_code(item_id, exit_code)
                    if self._task_stop_requested(task_id):
                        raise MediaError("task_stopped", "任务已停止")
                    if exit_code != 0:
                        suffix = f"：{stderr_tail}" if stderr_tail else ""
                        raise MediaError("ffmpeg_failed", f"FFmpeg 退出码 {exit_code}{suffix}")
                    if not temp_path.is_file() or temp_path.stat().st_size <= 0:
                        raise MediaError("output_invalid", "转码输出不存在或为空")
                    if not self.settings.mock_media:
                        await probe_media(self.settings, temp_path)
                    break
                except asyncio.CancelledError:
                    raise
                except (MediaError, OSError) as exc:
                    if self._task_stop_requested(task_id):
                        raise MediaError("task_stopped", "任务已停止") from exc
                    summary = self._summarize_transcode_error(exc)
                    failures.append(f"{HARDWARE_MODE_LABELS[mode]}：{summary}")
                    self._safe_unlink(temp_path)
                    next_mode = modes[index + 1] if index + 1 < len(modes) else None
                    if next_mode:
                        reason = {
                            "field": "hardwareMode",
                            "code": "transcode_auto_fallback",
                            "message": (
                                f"{HARDWARE_MODE_LABELS[mode]}失败：{summary}；"
                                f"自动退回到{HARDWARE_MODE_LABELS[next_mode]}"
                            ),
                        }
                        fallback_reasons.append(reason)
                        await self._record_transcode_failure(
                            item_id, [*attempt_decision_reasons, *fallback_reasons]
                        )
                        await self.events.log(task_id, "warning", reason["message"], item_id)
                        continue
                    final_reason = {
                        "field": "hardwareMode",
                        "code": "transcode_attempt_failed",
                        "message": f"{HARDWARE_MODE_LABELS[mode]}失败：{summary}",
                    }
                    fallback_reasons.append(final_reason)
                    await self._record_transcode_failure(
                        item_id, [*attempt_decision_reasons, *fallback_reasons]
                    )
                    if len(modes) > 1:
                        joined = "；".join(failures)
                        raise MediaError(
                            "transcode_fallback_exhausted",
                            f"所有转码模式均失败：{joined}",
                        ) from exc
                    raise
            artifact_size = temp_path.stat().st_size
            fingerprint = f"sha256:{self._sha256(temp_path)}"

            if destination.kind == StorageKind.LOCAL:
                assert final_path is not None
                if final_path.exists():
                    raise StorageError("output_conflict", f"目标文件已存在：{output_relative}")
                # Persist the expected artifact before the atomic commit. Recovery can then
                # recognize a crash after commit but before the completed state is stored.
                with self.sessions() as session:
                    item = session.get(TaskFile, item_id)
                    if not item:
                        return
                    item.completed_artifact_path = str(temp_path)
                    item.artifact_size = artifact_size
                    item.artifact_fingerprint = fingerprint
                    item.transcode_completed_at = utcnow()
                    item.version += 1
                    session.commit()
                self.storage.commit_local(temp_path, final_path)
                with self.sessions() as session:
                    item = session.get(TaskFile, item_id)
                    if not item:
                        return
                    item.stage = FileStage.COMPLETED.value
                    item.completed_artifact_path = str(final_path)
                    item.artifact_size = artifact_size
                    item.artifact_fingerprint = fingerprint
                    item.transcode_completed_at = utcnow()
                    item.finished_at = utcnow()
                    item.progress_json = (item.progress_json or {}) | {"percent": 100.0, "progress": "end"}
                    item.version += 1
                    item.task.current_transcode_file_id = None
                    session.commit()
                    await self._publish_file(item)
                    await self._refresh_task(session, item.task)
                self._safe_unlink(input_path if source.kind == StorageKind.RCLONE else None)
            else:
                with self.sessions() as session:
                    item = session.get(TaskFile, item_id)
                    if not item:
                        return
                    item.stage = FileStage.UPLOAD_QUEUED.value
                    item.completed_artifact_path = str(temp_path)
                    item.artifact_size = artifact_size
                    item.artifact_fingerprint = fingerprint
                    item.transcode_completed_at = utcnow()
                    item.temp_output_path = None
                    item.version += 1
                    item.task.current_transcode_file_id = None
                    session.commit()
                    await self._publish_file(item)
                    await self._refresh_task(session, item.task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_file(item_id, exc)

    async def _persist_transcode_attempt(
        self,
        item_id: str,
        *,
        source_params: dict[str, Any],
        effective: dict[str, Any] | None,
        reasons: list[dict[str, str]],
        argv: list[str] | None,
        input_path: Path,
        input_is_cached: bool,
        temp_path: Path,
        output_relative: str,
    ) -> None:
        with self.sessions() as session:
            item = session.get(TaskFile, item_id)
            if not item or item.task.stop_requested:
                raise MediaError("task_stopped", "任务已停止")
            item.stage = FileStage.TRANSCODING.value
            item.source_params_json = source_params
            item.effective_params_json = effective
            item.decision_log_json = reasons
            item.ffmpeg_argv_json = self._redact_argv(argv) if argv else None
            item.input_cache_path = str(input_path) if input_is_cached else None
            item.temp_output_path = str(temp_path)
            item.final_output_path = output_relative
            item.progress_json = None
            item.last_error = None
            item.last_exit_code = None
            item.capability_snapshot_id = self.capability_id
            item.version += 1
            session.commit()
            await self._publish_file(item)

    async def _record_transcode_failure(
        self, item_id: str, reasons: list[dict[str, str]]
    ) -> None:
        with self.sessions() as session:
            item = session.get(TaskFile, item_id)
            if not item:
                return
            item.decision_log_json = reasons
            item.progress_json = None
            item.version += 1
            session.commit()
            await self._publish_file(item)

    async def _set_transcode_exit_code(self, item_id: str, exit_code: int) -> None:
        with self.sessions() as session:
            item = session.get(TaskFile, item_id)
            if not item:
                return
            item.last_exit_code = exit_code
            item.version += 1
            session.commit()

    async def _run_ffmpeg(
        self,
        task_id: str,
        file_id: str,
        argv: list[str],
        duration_ms: int | None,
        input_path: Path,
        output_path: Path,
    ) -> tuple[int, str]:
        if self.settings.mock_media:
            for index in range(1, 6):
                await asyncio.sleep(0.06)
                with self.sessions() as session:
                    task = session.get(Task, task_id)
                    if task and task.stop_requested:
                        raise MediaError("task_stopped", "任务已停止")
                progress = {
                    "frame": index * 360, "fps": 120.0, "bitrateKbps": 1800.0,
                    "outTimeMs": index * 12_000, "totalSizeBytes": index * 1_000_000,
                    "speed": 4.0, "percent": index * 20.0, "etaSeconds": (5 - index) * 3,
                    "progress": "end" if index == 5 else "continue",
                }
                await self._progress(task_id, file_id, progress, persist=index == 5)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if input_path.exists() and input_path.stat().st_size:
                shutil.copy2(input_path, output_path)
            else:
                output_path.write_bytes(b"ffpanel-mock-output")
            return 0, ""

        process = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        self._active_transcode = (task_id, process)
        stderr_task = asyncio.create_task(self._consume_stderr(process, task_id, file_id))
        block: dict[str, str] = {}
        last_persist = 0.0
        assert process.stdout is not None
        while line := await process.stdout.readline():
            text = line.decode(errors="replace").strip()
            if "=" not in text:
                continue
            key, value = text.split("=", 1)
            block[key] = value
            if key == "progress":
                now = time.monotonic()
                progress = parse_progress_block(block, duration_ms)
                persist = now - last_persist >= self.settings.progress_persist_seconds or value == "end"
                await self._progress(task_id, file_id, progress, persist=persist)
                if persist:
                    last_persist = now
                block = {}
        return_code = await process.wait()
        stderr_tail = await stderr_task
        self._active_transcode = None
        return return_code, stderr_tail

    @staticmethod
    def _summarize_transcode_error(exc: Exception) -> str:
        message = " ".join(str(exc).split()) or exc.__class__.__name__
        return message[-600:]

    async def _consume_stderr(self, process: asyncio.subprocess.Process, task_id: str, file_id: str) -> str:
        assert process.stderr is not None
        tail: deque[str] = deque(maxlen=40)
        while line := await process.stderr.readline():
            message = line.decode(errors="replace").rstrip()
            if message:
                tail.append(message[-2000:])
                await self.events.log(task_id, "info", message[-2000:], file_id)
        return "\n".join(tail)[-4000:]

    async def _progress(self, task_id: str, file_id: str, progress: dict[str, Any], *, persist: bool) -> None:
        progress_payload = {
            "taskId": task_id, "fileId": file_id, "stage": "transcoding", **progress,
            "updatedAt": datetime.now(UTC).isoformat(),
        }
        version = 0
        if persist:
            with self.sessions() as session:
                item = session.get(TaskFile, file_id)
                if item:
                    item.progress_json = progress_payload
                    item.version += 1
                    version = item.version
                    session.commit()
        await self.events.publish("transcode.progress", progress_payload, task_id=task_id, file_id=file_id, version=version)

    async def _process_upload(self, item_id: str) -> None:
        try:
            with self.sessions() as session:
                item = session.get(TaskFile, item_id)
                if not item or item.stage != FileStage.UPLOAD_QUEUED.value:
                    return
                task = item.task
                destination = StorageLocation.model_validate(task.destination_json)
                if not item.completed_artifact_path or not self._artifact_valid(item):
                    raise MediaError("artifact_invalid", "待上传转码产物缺失或校验失败")
                item.stage = FileStage.UPLOADING.value
                item.version += 1
                task.current_upload_file_id = item.id
                task.version += 1
                session.commit()
                artifact = Path(item.completed_artifact_path)
                relative = item.final_output_path or item.relative_path
                task_id = item.task_id
                await self._publish_task_and_file(task, item)
            final_ref = await self.storage.upload_artifact(
                artifact,
                destination,
                relative,
                task_id=task_id,
                cancel_check=lambda: self._task_stop_requested(task_id),
            )
            with self.sessions() as session:
                item = session.get(TaskFile, item_id)
                if not item:
                    return
                item.stage = FileStage.COMPLETED.value
                item.final_output_path = final_ref
                item.finished_at = utcnow()
                item.version += 1
                item.task.current_upload_file_id = None
                session.commit()
                await self._publish_file(item)
                await self._refresh_task(session, item.task)
            self._safe_unlink(artifact)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_file(item_id, exc)

    async def _process_companion(self, item_id: str) -> None:
        try:
            with self.sessions() as session:
                item = session.get(CompanionFile, item_id)
                if not item or item.stage != CompanionStage.PENDING.value:
                    return
                task = item.task
                item.stage = CompanionStage.COPYING.value
                item.started_at = item.started_at or utcnow()
                item.version += 1
                task.status = TaskStatus.RUNNING.value
                task.started_at = task.started_at or utcnow()
                task.current_upload_file_id = item.id
                task.version += 1
                source = StorageLocation.model_validate(task.source_json)
                destination = StorageLocation.model_validate(task.destination_json)
                relative = item.relative_path
                task_id = task.id
                session.commit()
                await self.events.publish("companion.state", companion_dict(item), task_id=task_id, file_id=item.id, version=item.version)
                await self.events.publish("task.state", task_dict(task), task_id=task_id, version=task.version)
            final = await self.storage.copy_companion(
                source,
                destination,
                relative,
                task_id=task_id,
                cancel_check=lambda: self._task_stop_requested(task_id),
            )
            with self.sessions() as session:
                item = session.get(CompanionFile, item_id)
                if not item:
                    return
                item.stage = CompanionStage.COMPLETED.value
                item.final_output_path = final
                item.finished_at = utcnow()
                item.version += 1
                item.task.current_upload_file_id = None
                session.commit()
                await self.events.publish("companion.state", companion_dict(item), task_id=task_id, file_id=item.id, version=item.version)
                await self._refresh_task(session, item.task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_companion(item_id, exc)

    async def _fail_file(self, item_id: str, exc: Exception) -> None:
        with self.sessions() as session:
            item = session.get(TaskFile, item_id)
            if not item:
                return
            stopped = item.task.stop_requested
            item.stage = FileStage.INTERRUPTED.value if stopped else FileStage.FAILED.value
            item.last_error = str(exc)[-4000:]
            item.finished_at = utcnow()
            item.version += 1
            item.task.current_transcode_file_id = None if item.task.current_transcode_file_id == item.id else item.task.current_transcode_file_id
            item.task.current_upload_file_id = None if item.task.current_upload_file_id == item.id else item.task.current_upload_file_id
            session.commit()
            task_id = item.task_id
            await self._publish_file(item)
            await self.events.log(task_id, "error", str(exc), item.id)
            await self._refresh_task(session, item.task)

    async def _fail_companion(self, item_id: str, exc: Exception) -> None:
        with self.sessions() as session:
            item = session.get(CompanionFile, item_id)
            if not item:
                return
            stopped = item.task.stop_requested
            item.stage = CompanionStage.INTERRUPTED.value if stopped else CompanionStage.FAILED.value
            item.last_error = str(exc)[-4000:]
            item.finished_at = utcnow()
            item.version += 1
            item.task.current_upload_file_id = None
            session.commit()
            await self.events.publish("companion.state", companion_dict(item), task_id=item.task_id, file_id=item.id, version=item.version)
            await self.events.log(item.task_id, "error", str(exc), item.id)
            await self._refresh_task(session, item.task)

    async def _set_file_stage(self, item_id: str, stage: str) -> None:
        with self.sessions() as session:
            item = session.get(TaskFile, item_id)
            if item:
                item.stage = stage
                item.version += 1
                session.commit()
                await self._publish_file(item)

    async def _refresh_task(self, session: Session, task: Task) -> None:
        session.expire(task, ["files", "companions"])
        task.completed_files = sum(item.stage == FileStage.COMPLETED.value for item in task.files)
        task.failed_files = sum(item.stage == FileStage.FAILED.value for item in task.files)
        task.skipped_files = sum(item.stage == FileStage.SKIPPED.value for item in task.files)
        task.companion_completed = sum(item.stage == CompanionStage.COMPLETED.value for item in task.companions)
        task.companion_failed = sum(item.stage == CompanionStage.FAILED.value for item in task.companions)
        video_done = all(item.stage in TERMINAL_FILE_STAGES for item in task.files)
        companion_done = all(item.stage in TERMINAL_COMPANION_STAGES for item in task.companions)
        if task.stop_requested:
            task.status = TaskStatus.STOPPED.value
        elif video_done and companion_done:
            failures = task.failed_files + task.companion_failed
            successes = task.completed_files + task.companion_completed
            task.status = TaskStatus.PARTIAL_FAILED.value if failures and successes else TaskStatus.FAILED.value if failures else TaskStatus.COMPLETED.value
            task.finished_at = utcnow()
        else:
            task.status = TaskStatus.RUNNING.value
        errors = [item.last_error for item in task.files if item.last_error]
        errors.extend(item.last_error for item in task.companions if item.last_error)
        task.last_error = next(iter(errors), None)
        task.version += 1
        session.commit()
        payload = task_dict(task)
        await self.events.publish("task.metrics", payload, task_id=task.id, version=task.version)
        await self.events.publish("task.state", payload, task_id=task.id, version=task.version)

    async def _publish_file(self, item: TaskFile) -> None:
        await self.events.publish("file.state", file_dict(item, include_decision=True), task_id=item.task_id, file_id=item.id, version=item.version)

    async def _publish_task_and_file(self, task: Task, item: TaskFile) -> None:
        await self.events.publish("task.state", task_dict(task), task_id=task.id, version=task.version)
        await self._publish_file(item)

    async def _mark_active_interrupted(self, reason: str) -> None:
        with self.sessions() as session:
            tasks = session.scalars(select(Task).where(Task.status == TaskStatus.RUNNING.value)).all()
            for task in tasks:
                task.status = TaskStatus.INTERRUPTED.value
                task.interrupted_reason = reason
                task.current_transcode_file_id = None
                task.current_upload_file_id = None
                task.version += 1
                for item in task.files:
                    if item.stage in {FileStage.DOWNLOADING.value, FileStage.PROBING.value, FileStage.TRANSCODING.value, FileStage.UPLOADING.value}:
                        item.stage = FileStage.INTERRUPTED.value
                        item.version += 1
                for companion in task.companions:
                    if companion.stage == CompanionStage.COPYING.value:
                        companion.stage = CompanionStage.INTERRUPTED.value
                        companion.version += 1
            session.commit()

    def _upload_queued_count(self) -> int:
        with self.sessions() as session:
            return int(session.scalar(select(func.count()).select_from(TaskFile).where(TaskFile.stage == FileStage.UPLOAD_QUEUED.value)) or 0)

    def _task_id_for_file(self, item_id: str) -> str | None:
        with self.sessions() as session:
            return session.scalar(select(TaskFile.task_id).where(TaskFile.id == item_id))

    def _task_id_for_companion(self, item_id: str) -> str | None:
        with self.sessions() as session:
            return session.scalar(select(CompanionFile.task_id).where(CompanionFile.id == item_id))

    def _task_stop_requested(self, task_id: str) -> bool:
        with self.sessions() as session:
            return bool(session.scalar(select(Task.stop_requested).where(Task.id == task_id)))

    def _observe_storage_process(
        self,
        lane: str,
        task_id: str,
        process: asyncio.subprocess.Process | None,
    ) -> None:
        if lane == "transcode":
            self._active_transcode = (task_id, process) if process else None
        else:
            self._active_transfer = (task_id, process) if process else None

    @staticmethod
    def _artifact_valid(item: TaskFile) -> bool:
        if not item.completed_artifact_path:
            return False
        path = Path(item.completed_artifact_path)
        if not path.is_file() or (item.artifact_size is not None and path.stat().st_size != item.artifact_size):
            return False
        if item.artifact_fingerprint and item.artifact_fingerprint.startswith("sha256:"):
            return Scheduler._sha256(path) == item.artifact_fingerprint.removeprefix("sha256:")
        return True

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _safe_unlink(path: Path | None) -> None:
        if path and path.is_file():
            with contextlib.suppress(OSError):
                path.unlink()

    @staticmethod
    def _redact_argv(argv: list[str]) -> list[str]:
        result = argv.copy()
        for index, value in enumerate(result):
            if index and result[index - 1] == "-i":
                result[index] = f"<input>/{Path(value).name}"
            elif index == len(result) - 1:
                result[index] = f"<output>/{Path(value).name}"
        return result

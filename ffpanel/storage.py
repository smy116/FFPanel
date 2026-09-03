from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from .config import Settings
from .schemas import CompanionFilePolicy, StorageKind, StorageLocation

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".m4v", ".ts", ".m2ts", ".webm",
    ".flv", ".wmv", ".mpg", ".mpeg", ".vob", ".ogv", ".rm", ".rmvb", ".3gp",
}
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx"}


class StorageError(RuntimeError):
    def __init__(self, code: str, message: str, details: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(slots=True)
class ScanEntry:
    relative_path: str
    size: int | None
    mtime_ns: int | None
    category: str


@dataclass(slots=True)
class ScanRecord:
    token: str
    source: StorageLocation
    policy: CompanionFilePolicy
    entries: list[ScanEntry]
    expires_at: datetime
    signature: str


class ScanRegistry:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._records: dict[str, ScanRecord] = {}

    def put(self, source: StorageLocation, policy: CompanionFilePolicy, entries: list[ScanEntry]) -> ScanRecord:
        self._prune()
        token = uuid.uuid4().hex
        expires_at = datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)
        record = ScanRecord(token, source, policy, entries, expires_at, self.signature(source, policy))
        self._records[token] = record
        return record

    def consume(self, token: str, source: StorageLocation, policy: CompanionFilePolicy) -> ScanRecord:
        self._prune()
        record = self._records.pop(token, None)
        if record is None:
            raise StorageError("scan_expired", "扫描结果已失效，请重新扫描")
        if record.signature != self.signature(source, policy):
            raise StorageError("scan_mismatch", "路径或伴随文件策略已改变，请重新扫描")
        return record

    @staticmethod
    def signature(source: StorageLocation, policy: CompanionFilePolicy) -> str:
        payload = source.model_dump(mode="json", by_alias=True) | {"policy": policy}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _prune(self) -> None:
        now = datetime.now(UTC)
        expired = [token for token, record in self._records.items() if record.expires_at <= now]
        for token in expired:
            self._records.pop(token, None)


class StorageService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.process_observer: Callable[[str, str, asyncio.subprocess.Process | None], None] | None = None

    def validate_local(self, value: str, *, allow_missing: bool = False) -> Path:
        raw = Path(value)
        candidate = raw.resolve(strict=not allow_missing)
        if not any(candidate == root or root in candidate.parents for root in self.settings.allowed_local_roots):
            raise StorageError("path_forbidden", f"本地路径必须位于允许的媒体目录中：{value}")
        return candidate

    @staticmethod
    def validate_relative(relative_path: str) -> str:
        normalized = PurePosixPath(relative_path.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise StorageError("path_invalid", "文件相对路径不合法")
        return normalized.as_posix()

    @staticmethod
    def rclone_ref(location: StorageLocation, relative_path: str = "") -> str:
        if location.kind != StorageKind.RCLONE or not location.remote:
            raise StorageError("storage_invalid", "不是有效的 rclone 位置")
        base = location.path.strip("/")
        rel = relative_path.strip("/")
        joined = "/".join(value for value in (base, rel) if value)
        return f"{location.remote}:{joined}" if joined else f"{location.remote}:"

    def local_path(self, location: StorageLocation, relative_path: str = "", *, allow_missing: bool = False) -> Path:
        if location.kind != StorageKind.LOCAL:
            raise StorageError("storage_invalid", "不是本地存储位置")
        base = self.validate_local(location.path, allow_missing=allow_missing)
        relative = self.validate_relative(relative_path) if relative_path else ""
        target = (base / relative).resolve(strict=False)
        if target != base and base not in target.parents:
            raise StorageError("path_forbidden", "目标路径超出允许范围")
        return target

    async def list_remotes(self) -> list[str]:
        if not self.settings.rclone_config.is_file():
            return []
        try:
            output = await self._run([
                self.settings.rclone_path, "listremotes", "--config", str(self.settings.rclone_config)
            ])
        except (StorageError, FileNotFoundError):
            return []
        return [line.rstrip(":") for line in output.splitlines() if line.strip()]

    async def browse(self, location: StorageLocation) -> list[dict[str, Any]]:
        if location.kind == StorageKind.LOCAL:
            path = self.local_path(location)
            if not path.is_dir():
                raise StorageError("path_not_directory", "所选本地路径不是目录")
            return [
                {
                    "name": entry.name,
                    "path": str(entry),
                    "isDir": entry.is_dir(),
                    "size": entry.stat().st_size if entry.is_file() else None,
                    "modifiedAt": datetime.fromtimestamp(entry.stat().st_mtime, UTC).isoformat(),
                }
                for entry in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
                if not entry.name.startswith(".ffpanel-")
            ]

        result = await self._run_json([
            self.settings.rclone_path, "lsjson", self.rclone_ref(location), "--max-depth", "1",
            "--config", str(self.settings.rclone_config),
        ])
        return [
            {
                "name": item.get("Name"),
                "path": f"{location.path.rstrip('/')}/{item.get('Path', '')}".strip("/"),
                "isDir": bool(item.get("IsDir")),
                "size": item.get("Size") if not item.get("IsDir") else None,
                "modifiedAt": item.get("ModTime"),
            }
            for item in result
        ]

    async def scan(self, source: StorageLocation) -> list[ScanEntry]:
        if source.kind == StorageKind.LOCAL:
            root = self.local_path(source)
            if root.is_file():
                stat = root.stat()
                return [self._entry(root.name, stat.st_size, stat.st_mtime_ns)]
            if not root.is_dir():
                raise StorageError("path_not_found", "输入路径不存在")
            entries: list[ScanEntry] = []
            for current, directories, files in os.walk(root):
                directories[:] = [name for name in directories if not name.startswith(".ffpanel-")]
                for name in files:
                    path = Path(current) / name
                    relative = path.relative_to(root).as_posix()
                    stat = path.stat()
                    entries.append(self._entry(relative, stat.st_size, stat.st_mtime_ns))
            return sorted(entries, key=lambda entry: entry.relative_path.lower())

        result = await self._run_json([
            self.settings.rclone_path, "lsjson", self.rclone_ref(source), "--recursive", "--files-only",
            "--config", str(self.settings.rclone_config),
        ])
        entries = []
        for item in result:
            mod_time = item.get("ModTime")
            mtime_ns = None
            if mod_time:
                try:
                    mtime_ns = int(datetime.fromisoformat(mod_time).timestamp() * 1e9)
                except ValueError:
                    pass
            entries.append(self._entry(str(item.get("Path", "")), item.get("Size"), mtime_ns))
        return sorted(entries, key=lambda entry: entry.relative_path.lower())

    @staticmethod
    def _entry(relative_path: str, size: int | None, mtime_ns: int | None) -> ScanEntry:
        suffix = PurePosixPath(relative_path).suffix.lower()
        category = "video" if suffix in VIDEO_EXTENSIONS else "subtitle" if suffix in SUBTITLE_EXTENSIONS else "other"
        return ScanEntry(relative_path.replace("\\", "/"), size, mtime_ns, category)

    async def download(self, source: StorageLocation, relative_path: str, destination: Path, *, task_id: str | None = None) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.kind == StorageKind.LOCAL:
            shutil.copy2(self.local_path(source, relative_path), destination)
            return
        await self._run([
            self.settings.rclone_path, "copyto", self.rclone_ref(source, relative_path), str(destination),
            "--config", str(self.settings.rclone_config), "--no-traverse",
        ], lane="transcode", task_id=task_id)

    async def copy_companion(
        self,
        source: StorageLocation,
        destination: StorageLocation,
        relative_path: str,
        *,
        task_id: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> str:
        relative_path = self.validate_relative(relative_path)
        if await self.exists(destination, relative_path):
            raise StorageError("output_conflict", f"目标文件已存在：{relative_path}")
        token = uuid.uuid4().hex[:10]
        temp_relative = self._temp_relative(relative_path, token)

        if source.kind == StorageKind.LOCAL and destination.kind == StorageKind.LOCAL:
            source_path = self.local_path(source, relative_path)
            final_path = self.local_path(destination, relative_path, allow_missing=True)
            temp_path = self.local_path(destination, temp_relative, allow_missing=True)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copy2, source_path, temp_path)
            if cancel_check and cancel_check():
                temp_path.unlink(missing_ok=True)
                raise StorageError("task_stopped", "任务已停止")
            self.commit_local(temp_path, final_path)
            return str(final_path)

        source_ref = str(self.local_path(source, relative_path)) if source.kind == StorageKind.LOCAL else self.rclone_ref(source, relative_path)
        temp_ref = str(self.local_path(destination, temp_relative, allow_missing=True)) if destination.kind == StorageKind.LOCAL else self.rclone_ref(destination, temp_relative)
        final_ref = str(self.local_path(destination, relative_path, allow_missing=True)) if destination.kind == StorageKind.LOCAL else self.rclone_ref(destination, relative_path)
        if destination.kind == StorageKind.LOCAL:
            Path(temp_ref).parent.mkdir(parents=True, exist_ok=True)
        await self._run([
            self.settings.rclone_path, "copyto", source_ref, temp_ref, "--config", str(self.settings.rclone_config), "--no-traverse",
        ], lane="transfer", task_id=task_id)
        if cancel_check and cancel_check():
            if destination.kind == StorageKind.LOCAL:
                Path(temp_ref).unlink(missing_ok=True)
            raise StorageError("task_stopped", "任务已停止")
        if destination.kind == StorageKind.LOCAL:
            self.commit_local(Path(temp_ref), Path(final_ref))
        else:
            await self._run([
                self.settings.rclone_path, "moveto", temp_ref, final_ref, "--config", str(self.settings.rclone_config), "--no-traverse", "--immutable",
            ], lane="transfer", task_id=task_id)
        return final_ref

    async def upload_artifact(
        self,
        artifact: Path,
        destination: StorageLocation,
        relative_path: str,
        *,
        task_id: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> str:
        relative_path = self.validate_relative(relative_path)
        if await self.exists(destination, relative_path):
            raise StorageError("output_conflict", f"目标文件已存在：{relative_path}")
        temp_relative = self._temp_relative(relative_path, uuid.uuid4().hex[:10])
        temp_ref = self.rclone_ref(destination, temp_relative)
        final_ref = self.rclone_ref(destination, relative_path)
        await self._run([
            self.settings.rclone_path, "copyto", str(artifact), temp_ref, "--config", str(self.settings.rclone_config), "--no-traverse",
        ], lane="transfer", task_id=task_id)
        if cancel_check and cancel_check():
            raise StorageError("task_stopped", "任务已停止")
        await self._run([
            self.settings.rclone_path, "moveto", temp_ref, final_ref, "--config", str(self.settings.rclone_config), "--no-traverse", "--immutable",
        ], lane="transfer", task_id=task_id)
        return final_ref

    async def exists(self, destination: StorageLocation, relative_path: str) -> bool:
        return await self.stat(destination, relative_path) is not None

    async def stat(self, destination: StorageLocation, relative_path: str) -> dict[str, Any] | None:
        if destination.kind == StorageKind.LOCAL:
            path = self.local_path(destination, relative_path, allow_missing=True)
            if not path.exists():
                return None
            value = path.stat()
            return {"size": value.st_size, "modifiedAt": datetime.fromtimestamp(value.st_mtime, UTC).isoformat()}
        try:
            output = await self._run([
                self.settings.rclone_path, "lsjson", self.rclone_ref(destination, relative_path),
                "--stat", "--config", str(self.settings.rclone_config),
            ])
            value = json.loads(output)
            return {"size": value.get("Size"), "modifiedAt": value.get("ModTime"), "hashes": value.get("Hashes") or {}}
        except StorageError as exc:
            missing_markers = ("not found", "directory not found", "object not found", "doesn't exist")
            if any(marker in str(exc).lower() for marker in missing_markers):
                return None
            raise

    @staticmethod
    def commit_local(temp_path: Path, final_path: Path) -> None:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(temp_path, final_path)
        except FileExistsError as exc:
            raise StorageError("output_conflict", f"目标文件已存在：{final_path}") from exc
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                raise StorageError("atomic_commit_unavailable", "临时文件与目标文件不在同一文件系统") from exc
            raise
        temp_path.unlink()

    @staticmethod
    def _temp_relative(relative_path: str, token: str) -> str:
        path = PurePosixPath(relative_path)
        return str(path.with_name(f".ffpanel-{path.stem}-{token}.part{path.suffix}"))

    async def _run(self, argv: list[str], *, lane: str | None = None, task_id: str | None = None) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError as exc:
            raise StorageError("tool_unavailable", f"命令不可用：{argv[0]}") from exc
        if self.process_observer and lane and task_id:
            self.process_observer(lane, task_id, process)
        try:
            stdout, stderr = await process.communicate()
        finally:
            if self.process_observer and lane and task_id:
                self.process_observer(lane, task_id, None)
        if process.returncode != 0:
            message = stderr.decode(errors="replace").strip()[-2000:]
            raise StorageError("storage_command_failed", message or f"命令退出码 {process.returncode}")
        return stdout.decode(errors="replace")

    async def _run_json(self, argv: list[str]) -> list[dict[str, Any]]:
        output = await self._run(argv)
        try:
            value = json.loads(output or "[]")
        except json.JSONDecodeError as exc:
            raise StorageError("storage_response_invalid", "rclone 返回了无效 JSON") from exc
        return value if isinstance(value, list) else [value]


def companion_selected(entry: ScanEntry, policy: CompanionFilePolicy) -> bool:
    if policy == "none" or entry.category == "video":
        return False
    if policy == "subtitles":
        return entry.category == "subtitle"
    return True

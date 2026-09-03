from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import ffpanel.scheduler as scheduler_module
from ffpanel.config import Settings
from ffpanel.main import create_app
from ffpanel.models import TaskFile
from ffpanel.scheduler import CapabilitySnapshot, Scheduler, transcode_mode_chain
from ffpanel.schemas import TranscodeParams


def _mode_from_argv(argv: list[str]) -> str:
    if "-hwaccel" in argv:
        return "mpp_mpp"
    encoder = argv[argv.index("-c:v") + 1]
    return "cpu_mpp" if encoder.endswith("_rkmpp") else "cpu_cpu"


def _create_task(
    client: TestClient,
    media: Path,
    *,
    auto_fallback: bool,
    hardware_mode: str = "mpp_mpp",
) -> str:
    source = media / "input"
    destination = media / "output"
    source.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    (source / "movie.mkv").write_bytes(b"video-content")
    scan = client.post(
        "/api/v1/storage/scan",
        json={
            "source": {"kind": "local", "path": str(source)},
            "companionFilePolicy": "none",
        },
    )
    assert scan.status_code == 200, scan.text
    response = client.post(
        "/api/v1/tasks",
        json={
            "source": {"kind": "local", "path": str(source)},
            "destination": {"kind": "local", "path": str(destination)},
            "scanToken": scan.json()["scanToken"],
            "companionFilePolicy": "none",
            "params": {
                "hardwareMode": hardware_mode,
                "autoFallback": auto_fallback,
                "videoCodec": "h264",
                "container": "mp4",
                "height": 720,
                "bitrateKbps": 2000,
                "smartBitrateCap": True,
                "frameRate": "source",
                "rateControl": "vbr",
                "audioStrategy": "copy",
                "subtitleStrategy": "auto",
            },
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _wait_for_task(client: TestClient, task_id: str) -> dict:
    deadline = time.monotonic() + 4
    task: dict = {}
    while time.monotonic() < deadline:
        task = client.get(f"/api/v1/tasks/{task_id}").json()
        if task["status"] in {"completed", "failed", "partial_failed"}:
            return task
        time.sleep(0.05)
    pytest.fail(f"task did not finish: {task}")


def test_transcode_mode_chain_follows_the_requested_start() -> None:
    assert transcode_mode_chain(TranscodeParams(hardware_mode="mpp_mpp")) == (
        "mpp_mpp",
        "cpu_mpp",
        "cpu_cpu",
    )
    assert transcode_mode_chain(TranscodeParams(hardware_mode="cpu_mpp")) == (
        "cpu_mpp",
        "cpu_cpu",
    )
    assert transcode_mode_chain(TranscodeParams(hardware_mode="cpu_cpu")) == ("cpu_cpu",)
    assert transcode_mode_chain(
        TranscodeParams(hardware_mode="mpp_mpp", auto_fallback=False)
    ) == ("mpp_mpp",)


def test_runtime_failures_fall_back_to_cpu_and_preserve_one_file_attempt(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modes: list[str] = []
    output_existed: list[bool] = []
    progress_was_reset: list[bool] = []
    probe_count = 0
    original_probe = scheduler_module.probe_media

    async def counting_probe(settings: Settings, path: Path) -> dict:
        nonlocal probe_count
        probe_count += 1
        return await original_probe(settings, path)

    async def fake_run(
        self: Scheduler,
        task_id: str,
        file_id: str,
        argv: list[str],
        duration_ms: int | None,
        input_path: Path,
        output_path: Path,
    ) -> tuple[int, str]:
        del duration_ms, input_path
        modes.append(_mode_from_argv(argv))
        output_existed.append(output_path.exists())
        with self.sessions() as session:
            item = session.get(TaskFile, file_id)
            progress_was_reset.append(bool(item and item.progress_json is None))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"partial" if len(modes) < 3 else b"complete")
        if len(modes) < 3:
            with self.sessions() as session:
                item = session.get(TaskFile, file_id)
                assert item is not None
                item.progress_json = {"percent": 40.0, "progress": "continue"}
                session.commit()
            return 1, f"simulated failure {len(modes)}"
        await self._progress(
            task_id,
            file_id,
            {
                "frame": 1,
                "fps": 1.0,
                "bitrateKbps": 1.0,
                "outTimeMs": 60_000,
                "totalSizeBytes": len(b"complete"),
                "speed": 1.0,
                "percent": 100.0,
                "etaSeconds": 0,
                "progress": "end",
            },
            persist=True,
        )
        return 0, ""

    monkeypatch.setattr(scheduler_module, "probe_media", counting_probe)
    monkeypatch.setattr(Scheduler, "_run_ffmpeg", fake_run)

    with TestClient(create_app(settings)) as client:
        task_id = _create_task(client, tmp_path / "media", auto_fallback=True)
        assert _wait_for_task(client, task_id)["status"] == "completed"
        item = client.get(f"/api/v1/tasks/{task_id}/files").json()["items"][0]

    assert modes == ["mpp_mpp", "cpu_mpp", "cpu_cpu"]
    assert output_existed == [False, False, False]
    assert progress_was_reset == [True, True, True]
    assert probe_count == 1
    assert item["attempt"] == 1
    assert item["lastExitCode"] == 0
    assert item["parameterDecision"]["requested"]["hardwareMode"] == "mpp_mpp"
    assert item["parameterDecision"]["effective"]["hardwareMode"] == "cpu_cpu"
    assert [reason["code"] for reason in item["parameterDecision"]["reasons"]].count(
        "transcode_auto_fallback"
    ) == 2


def test_disabling_fallback_keeps_strict_single_mode(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modes: list[str] = []

    async def fake_run(
        self: Scheduler,
        task_id: str,
        file_id: str,
        argv: list[str],
        duration_ms: int | None,
        input_path: Path,
        output_path: Path,
    ) -> tuple[int, str]:
        del self, task_id, file_id, duration_ms, input_path, output_path
        modes.append(_mode_from_argv(argv))
        return 17, "strict failure"

    monkeypatch.setattr(Scheduler, "_run_ffmpeg", fake_run)
    with TestClient(create_app(settings)) as client:
        task_id = _create_task(client, tmp_path / "media", auto_fallback=False)
        task = _wait_for_task(client, task_id)
        item = client.get(f"/api/v1/tasks/{task_id}/files").json()["items"][0]

    assert task["status"] == "failed"
    assert modes == ["mpp_mpp"]
    assert item["ffmpegOutput"] == "strict failure"
    assert "FFmpeg 退出码 17" in item["lastError"]
    assert "所有转码模式均失败" not in item["lastError"]
    assert item["attempt"] == 1


def test_capability_decision_failures_skip_to_the_software_mode(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modes: list[str] = []

    async def unavailable_capabilities(settings: Settings) -> CapabilitySnapshot:
        del settings
        return CapabilitySnapshot(
            "test",
            True,
            False,
            False,
            False,
            ["libx264", "libx265"],
            [],
            [],
            {},
            None,
        )

    async def fake_run(
        self: Scheduler,
        task_id: str,
        file_id: str,
        argv: list[str],
        duration_ms: int | None,
        input_path: Path,
        output_path: Path,
    ) -> tuple[int, str]:
        del self, task_id, file_id, duration_ms, input_path
        modes.append(_mode_from_argv(argv))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"complete")
        return 0, ""

    monkeypatch.setattr(scheduler_module, "detect_capabilities", unavailable_capabilities)
    monkeypatch.setattr(Scheduler, "_run_ffmpeg", fake_run)
    with TestClient(create_app(settings)) as client:
        task_id = _create_task(client, tmp_path / "media", auto_fallback=True)
        assert _wait_for_task(client, task_id)["status"] == "completed"

    assert modes == ["cpu_cpu"]
    assert (tmp_path / "media" / "output" / "movie.mp4").is_file()


def test_all_fallback_modes_report_an_aggregated_failure(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modes: list[str] = []

    async def fake_run(
        self: Scheduler,
        task_id: str,
        file_id: str,
        argv: list[str],
        duration_ms: int | None,
        input_path: Path,
        output_path: Path,
    ) -> tuple[int, str]:
        del self, task_id, file_id, duration_ms, input_path
        modes.append(_mode_from_argv(argv))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"partial")
        return len(modes), f"failure {len(modes)}"

    monkeypatch.setattr(Scheduler, "_run_ffmpeg", fake_run)
    with TestClient(create_app(settings)) as client:
        task_id = _create_task(client, tmp_path / "media", auto_fallback=True)
        task = _wait_for_task(client, task_id)
        item = client.get(f"/api/v1/tasks/{task_id}/files").json()["items"][0]

    assert task["status"] == "failed"
    assert modes == ["mpp_mpp", "cpu_mpp", "cpu_cpu"]
    assert "所有转码模式均失败" in item["lastError"]
    assert all(label in item["lastError"] for label in (
        "Rockchip MPP 硬件编解码",
        "CPU 软解 + MPP 编码",
        "CPU 软件编解码",
    ))
    assert item["lastExitCode"] == 3
    assert item["attempt"] == 1
    assert not list((tmp_path / "media" / "output").glob(".ffpanel-*.part.*"))


def test_stop_does_not_start_the_next_fallback_mode(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modes: list[str] = []
    started = threading.Event()

    async def fake_run(
        self: Scheduler,
        task_id: str,
        file_id: str,
        argv: list[str],
        duration_ms: int | None,
        input_path: Path,
        output_path: Path,
    ) -> tuple[int, str]:
        del file_id, duration_ms, input_path, output_path
        modes.append(_mode_from_argv(argv))
        started.set()
        while not self._task_stop_requested(task_id):
            await asyncio.sleep(0.01)
        return -15, "terminated"

    monkeypatch.setattr(Scheduler, "_run_ffmpeg", fake_run)
    with TestClient(create_app(settings)) as client:
        task_id = _create_task(client, tmp_path / "media", auto_fallback=True)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not started.is_set():
            time.sleep(0.01)
        assert started.is_set()
        assert client.post(f"/api/v1/tasks/{task_id}/stop").status_code == 200
        deadline = time.monotonic() + 2
        stage = ""
        while time.monotonic() < deadline:
            stage = client.get(f"/api/v1/tasks/{task_id}/files").json()["items"][0]["stage"]
            if stage == "interrupted":
                break
            time.sleep(0.02)

    assert modes == ["mpp_mpp"]
    assert stage == "interrupted"

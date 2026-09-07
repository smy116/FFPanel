from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ffpanel.config import Settings
from ffpanel.hardware import detection, registry
from ffpanel.hardware.compat import CapabilitySnapshot
from ffpanel.hardware.types import FFmpegInventory, MediaError
from ffpanel.media import build_ffmpeg_argv, decide_parameters
from ffpanel.schemas import TranscodeParams

MODES = ["nvdec_nvenc", "cpu_nvenc", "qsv_qsv", "cpu_qsv", "vaapi_vaapi", "cpu_vaapi"]


def source(transform="scale", pixel_format="yuv420p", codec="h264"):
    rotation = int(transform) if transform in {"90", "180", "270"} else 0
    return {"video": {"codec": codec, "pixelFormat": pixel_format, "width": 1280, "height": 720,
        "displayWidth": 720 if rotation in {90, 270} else 1536 if transform == "sar" else 1280,
        "displayHeight": 1280 if rotation in {90, 270} else 720,
        "rotation": rotation, "sampleAspectRatio": "6:5" if transform == "sar" else "1:1"},
        "audio": [], "subtitles": []}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("codec", ["h264", "hevc"])
@pytest.mark.parametrize("rate", ["cbr", "vbr"])
@pytest.mark.parametrize("transform", ["none", "scale", "sar", "90", "180", "270"])
def test_gpu_video_contract(gpu_snapshot, mode, codec, rate, transform):
    profile = registry.profiles[mode]
    params = TranscodeParams.model_validate({"hardwareMode": mode, "videoCodec": codec,
        "rateControl": rate, "height": 360 if transform == "scale" else -1})
    if transform in {"90", "180", "270"} and profile.decode_mode == "hardware":
        with pytest.raises(MediaError, match="旋转"):
            decide_parameters(source(transform), params, gpu_snapshot)
        return
    effective, _ = decide_parameters(source(transform), params, gpu_snapshot)
    argv = build_ffmpeg_argv(Settings(), Path("input.mp4"), Path("output.mp4"), effective)
    assert argv == build_ffmpeg_argv(Settings(nvidia_device=7, intel_render_device="/dev/dri/renderD130"),
        Path("input.mp4"), Path("output.mp4"), json.loads(json.dumps(effective)))
    assert effective["hardwareDevice"] == ("2" if profile.backend_id == "nvidia" else "/dev/dri/renderD129")
    assert effective["pixelFormat"] == "nv12"
    assert argv[argv.index("-c:v") + 1] == f"{codec}_{'nvenc' if profile.backend_id == 'nvidia' else profile.backend_id}"
    assert "hwdownload" not in " ".join(argv)
    assert "-rc_mode" not in argv or profile.backend_id == "vaapi"
    vf = argv[argv.index("-vf") + 1]
    if profile.decode_mode == "hardware":
        assert argv.index("-hwaccel") < argv.index("-i") < argv.index("-vf")
        assert vf.startswith("scale_")
    else:
        assert "-hwaccel" not in argv
        assert ("hwupload" in vf) == (profile.backend_id != "nvidia")
    if transform == "sar":
        assert "setsar=1" in vf
    if transform in {"90", "180", "270"}:
        assert "-noautorotate" in argv
        assert "transpose=" in vf or "hflip,vflip" in vf
    if profile.backend_id == "qsv" and rate == "vbr":
        assert int(argv[argv.index("-b:v") + 1][:-1]) < int(argv[argv.index("-maxrate") + 1][:-1])


@pytest.mark.parametrize("mode", MODES[::2])
def test_missing_decode_or_pixel_format_is_not_silently_downloaded(gpu_snapshot, mode):
    params = TranscodeParams.model_validate({"hardwareMode": mode})
    with pytest.raises(MediaError, match="像素格式"):
        decide_parameters(source(pixel_format="yuv444p"), params, gpu_snapshot)
    caps = gpu_snapshot.backend_capabilities[registry.profiles[mode].backend_id]
    caps.features["decode_h264"] = False
    with pytest.raises(MediaError, match="硬件解码"):
        decide_parameters(source(), params, gpu_snapshot)


def test_codec_specific_capabilities_and_dri_does_not_imply_mpp(gpu_snapshot):
    caps = gpu_snapshot.backend_capabilities["nvidia"]
    caps.features["encode_hevc"] = False
    caps.errors["encode_hevc"] = "GPU does not support HEVC"
    gpu_snapshot.mpp_available = False
    gpu_snapshot.rga_available = False
    gpu_snapshot.backend_capabilities["rockchip"] = replace(
        gpu_snapshot.backend_capabilities["rockchip"], devices={"/dev/dri": True})
    public = gpu_snapshot.hardware_dict()
    nvidia = next(item for item in public["hardwareBackends"] if item["id"] == "nvidia")
    assert nvidia["status"] == "partial"
    profile = next(item for item in public["hardwareProfiles"] if item["id"] == "nvdec_nvenc")
    assert profile["codecs"] == ["h264"]
    assert public["recommendedHardwareMode"] == "qsv_qsv"
    assert not next(item for item in public["hardwareBackends"] if item["id"] == "rockchip")["detected"]
    with pytest.raises(MediaError, match="HEVC"):
        decide_parameters(source(), TranscodeParams(hardware_mode="cpu_nvenc"), gpu_snapshot)


@pytest.mark.parametrize("vendor,access,detected,error", [
    ("0x8086", True, True, None), ("0x1002", True, False, "不是 Intel"),
    ("0x8086", False, True, "权限不足"),
])
def test_intel_device_vendor_and_permissions(monkeypatch, vendor, access, detected, error):
    monkeypatch.setattr(Path, "exists", lambda _: True)
    monkeypatch.setattr(Path, "read_text", lambda _: vendor)
    monkeypatch.setattr(detection.os, "access", lambda *_: access)
    actual, reason = detection.intel_device_status("/dev/dri/renderD129")
    assert actual == detected
    assert reason is None if error is None else error in reason


@pytest.mark.parametrize("outcome", ["success", "driver", "hevc", "timeout"])
async def test_runtime_probe_isolated_failures(monkeypatch, gpu_snapshot, outcome):
    monkeypatch.setattr(Path, "exists", lambda _: True)
    monkeypatch.setattr(detection, "intel_device_status", lambda _: (True, None))
    calls = []

    async def fake_capture(argv, timeout):
        calls.append(argv)
        if outcome == "driver" and "cuda=gpu:0" in argv:
            raise MediaError("driver", "NVIDIA driver unavailable")
        if outcome == "hevc" and "hevc_nvenc" in argv:
            raise MediaError("encode", "HEVC unavailable")
        if outcome == "timeout" and "cuda=gpu:0" in argv:
            raise TimeoutError
        return ""

    monkeypatch.setattr(detection, "capture", fake_capture)
    result = await detection.probe_runtime(Settings(), registry, gpu_snapshot.backend_capabilities)
    assert result["qsv"].features["encode_hevc"]
    assert result["cpu"] is gpu_snapshot.backend_capabilities["cpu"]
    assert result["nvidia"].features["encode_hevc"] == (outcome == "success")
    assert result["nvidia"].features["encode_h264"] == (outcome in {"success", "hevc"})
    assert any("hwdownload" in " ".join(argv) for argv in calls)
    assert all("128x72" not in " ".join(argv) for argv in calls)
    assert any("scale_vaapi=w=256:h=144" in " ".join(argv) for argv in calls)


async def test_compiled_features_without_device_never_ready(monkeypatch):
    monkeypatch.setattr(Path, "exists", lambda _: False)
    capture = AsyncMock()
    monkeypatch.setattr(detection, "capture", capture)
    caps = registry.probe(FFmpegInventory(frozenset({"h264_nvenc"}), frozenset(), frozenset(), {}, frozenset({"cuda"})))
    result = await detection.probe_runtime(Settings(), registry, caps)
    assert not result["nvidia"].features["encode_h264"]
    assert result["nvidia"].errors["initialize"]
    capture.assert_not_awaited()


@pytest.mark.parametrize("cancel", [False, True])
async def test_probe_timeout_and_cancellation_reap_process(monkeypatch, cancel):
    class Process:
        returncode = None
        killed = False
        calls = 0

        async def communicate(self):
            self.calls += 1
            if self.calls == 1:
                await asyncio.Event().wait()
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9

    process = Process()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    task = asyncio.create_task(detection.capture(["ffmpeg"], 0.01))
    if cancel:
        await asyncio.sleep(0)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await task
    assert process.killed
    assert process.calls >= 1


def test_legacy_snapshot_does_not_invent_gpu_support():
    snapshot = CapabilitySnapshot("old", True, False, False, False,
        ["libx264", "h264_nvenc"], [], [], {})
    profiles = snapshot.hardware_dict()["hardwareProfiles"]
    assert not next(item for item in profiles if item["id"] == "cpu_nvenc")["available"]

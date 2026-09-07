"""Bounded runtime checks; planners stay deterministic and subprocess-free."""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import replace
from functools import partial
from pathlib import Path

from ..config import Settings
from .gpu import GpuBackend
from .registry import HardwareRegistry
from .types import BackendCapabilities, MediaError, VideoPlan, VideoSettings


async def capture(argv: list[str], timeout: float) -> str:
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.communicate()
        raise
    if process.returncode:
        raise MediaError("hardware_probe_failed", stderr.decode(errors="replace")[-2000:])
    return stdout.decode(errors="replace") + stderr.decode(errors="replace")


def intel_device_status(device: str) -> tuple[bool, str | None]:
    path = Path(device)
    if not path.exists():
        return False, f"Intel render 设备不存在：{device}"
    vendor = Path("/sys/class/drm") / path.name / "device/vendor"
    try:
        if vendor.read_text().strip().lower() != "0x8086":
            return False, f"所选 render 节点不是 Intel GPU：{device}"
    except OSError:
        return True, f"无法读取 Intel GPU 厂商信息：{vendor}"
    if not os.access(path, os.R_OK | os.W_OK):
        return True, f"Intel render 设备权限不足：{device}"
    return True, None


async def check_runtime(settings: Settings, caps: BackendCapabilities, label: str,
                        key: str, argv: list[str]) -> bool:
    try:
        await capture([settings.ffmpeg_path, "-nostdin", "-hide_banner", "-loglevel", "error"] + argv,
                      settings.hardware_probe_timeout_seconds)
        caps.features[key] = True
    except (OSError, MediaError, TimeoutError) as exc:
        caps.errors[key] = str(exc) or f"{label} {key} 探测超时"
    return caps.features.get(key, False)


async def probe_runtime(settings: Settings, registry: HardwareRegistry,
                        capabilities: dict[str, BackendCapabilities]) -> dict[str, BackendCapabilities]:
    result = dict(capabilities)
    for backend in registry.backends.values():
        if not isinstance(backend, GpuBackend):
            continue
        caps = capabilities[backend.id]
        if backend.id == "nvidia":
            device = str(settings.nvidia_device)
            detected = Path("/dev/nvidiactl").exists()
            device_error = None if detected else "未检测到 NVIDIA 设备；请检查 Container Toolkit 和 GPU 映射"
        else:
            device = settings.intel_render_device
            detected, device_error = intel_device_status(device)
        features = dict(caps.features)
        errors: dict[str, str] = {}
        for feature in ("initialize", "encode_h264", "encode_hevc", "decode_h264", "decode_hevc", "decode", "scale"):
            features[feature] = False
        caps = replace(caps, device=device, detected=detected, features=features, errors=errors)
        result[backend.id] = caps
        if device_error or not features.get("compiled"):
            errors["initialize"] = device_error or f"FFmpeg 未编译 {backend.label} 支持"
            continue

        check = partial(check_runtime, settings, caps, backend.label)

        if not await check("initialize", backend.device_args(device) + [
            "-f", "lavfi", "-i", "color=size=128x72:rate=1", "-frames:v", "1", "-f", "null", "-"]):
            continue
        video_settings = VideoSettings(128, 72, True, 0, False, 1000, "source", "vbr")
        with tempfile.TemporaryDirectory(prefix="ffpanel-probe-") as directory:
            for codec in ("h264", "hevc"):
                encoder = f"{codec}_{backend.suffix}"
                if encoder not in caps.encoders:
                    errors[f"encode_{codec}"] = f"FFmpeg 未编译 {encoder}"
                else:
                    plan = VideoPlan(backend.profiles()[1], encoder, video_settings, "scale", device, "nv12")
                    video_args = backend.build_video_args(plan)
                    await check(f"encode_{codec}", list(video_args.before_input) + [
                        "-f", "lavfi", "-i", "testsrc2=size=256x144:rate=1"] + list(video_args.after_input) + [
                        "-frames:v", "2", "-f", "null", "-"])
                sample = str(Path(directory) / f"{codec}.mkv")
                try:
                    await capture([settings.ffmpeg_path, "-nostdin", "-hide_banner", "-loglevel", "error",
                                   "-f", "lavfi", "-i", "testsrc2=size=256x144:rate=1", "-frames:v", "2",
                                   "-c:v", "libx264" if codec == "h264" else "libx265",
                                   "-threads", "1", "-y", sample], settings.hardware_probe_timeout_seconds)
                except (OSError, MediaError, TimeoutError) as exc:
                    errors[f"decode_{codec}"] = f"探测样本生成失败：{exc}"
                    continue
                # Download is only a probe sink, never part of a production hardware plan.
                args = backend.device_args(device) + [
                    "-hwaccel", backend.hwaccel, "-hwaccel_device", "va" if backend.id == "vaapi" else "gpu",
                    "-hwaccel_output_format", backend.hwaccel, "-i", sample,
                    "-vf", "hwdownload,format=nv12", "-frames:v", "2", "-f", "null", "-"]
                if await check(f"decode_{codec}", args):
                    features["decode"] = True
                    vf_index = args.index("-vf") + 1
                    args[vf_index] = f"scale_{backend.hwaccel}=w=128:h=72:format=nv12,hwdownload,format=nv12"
                    if await check(f"scale_{codec}", args):
                        features["scale"] = True
    return result

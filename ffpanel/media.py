from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .hardware import registry
from .hardware.compat import (
    CapabilitySnapshot,
    legacy_snapshot,
    mock_snapshot,
    restore_video_plan,
)
from .hardware.detection import capture as capture_hardware
from .hardware.detection import probe_runtime
from .hardware.types import FFmpegInventory, MediaError, VideoRequest, VideoSettings
from .schemas import TranscodeParams

__all__ = [
    "CapabilitySnapshot", "MediaError", "build_ffmpeg_argv", "decide_parameters",
    "detect_capabilities", "normalize_probe", "parse_progress_block", "probe_media",
]


async def detect_capabilities(settings: Settings) -> CapabilitySnapshot:
    if settings.mock_media:
        return mock_snapshot()
    try:
        version, encoders, decoders, filters = await asyncio.gather(
            _capture([settings.ffmpeg_path, "-version"]),
            _capture([settings.ffmpeg_path, "-hide_banner", "-encoders"]),
            _capture([settings.ffmpeg_path, "-hide_banner", "-decoders"]),
            _capture([settings.ffmpeg_path, "-hide_banner", "-filters"]),
        )
        devices = {path: Path(path).exists() for path in registry.device_paths}
        try:
            hwaccels = await capture_hardware(
                [settings.ffmpeg_path, "-hide_banner", "-hwaccels"], settings.hardware_probe_timeout_seconds)
        except (OSError, MediaError, TimeoutError):
            hwaccels = ""
        devices[settings.intel_render_device] = Path(settings.intel_render_device).exists()
        inventory = FFmpegInventory(
            frozenset(re.findall(r"\b\w+\b", encoders)),
            frozenset(re.findall(r"\b\w+\b", decoders)),
            frozenset(re.findall(r"\b\w+\b", filters)),
            devices,
            frozenset(re.findall(r"\b\w+\b", hwaccels)),
        )
        backends = await probe_runtime(settings, registry, registry.probe(inventory))
        return legacy_snapshot(
            version.splitlines()[0], await _available(settings.rclone_path),
            backends, devices,
        )
    except (FileNotFoundError, MediaError) as exc:
        return CapabilitySnapshot(None, False, await _available(settings.rclone_path), False, False, [], [], [], {}, str(exc))


async def probe_media(
    settings: Settings,
    path: Path,
    *,
    process_observer: Callable[[asyncio.subprocess.Process | None], None] | None = None,
) -> dict[str, Any]:
    if settings.mock_media:
        size = path.stat().st_size if path.exists() else 8_000_000
        return {
            "durationMs": 60_000,
            "formatBitrateKbps": 3000,
            "video": {"codec": "h264", "width": 1920, "height": 1080, "displayWidth": 1920, "displayHeight": 1080, "bitrateKbps": 2800, "fps": 30.0, "pixelFormat": "yuv420p", "rotation": 0},
            "audio": [{"codec": "aac", "channels": 2, "sampleRate": 48000}],
            "subtitles": [],
            "sizeBytes": size,
        }
    output = await _capture_stdout(
        [
            settings.ffprobe_path, "-v", "error", "-show_streams", "-show_format", "-of",
            "json", str(path),
        ],
        process_observer=process_observer,
    )
    try:
        raw = json.loads(output)
    except json.JSONDecodeError as exc:
        raise MediaError("probe_invalid", "ffprobe 返回了无效 JSON") from exc
    return normalize_probe(raw, path.stat().st_size)


def normalize_probe(raw: dict[str, Any], size_bytes: int | None = None) -> dict[str, Any]:
    streams = raw.get("streams") or []
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video" and not (stream.get("disposition") or {}).get("attached_pic")]
    if not video_streams:
        raise MediaError("probe_no_video", "文件中没有可用的视频流")
    video = video_streams[0]
    rotation = _rotation(video)
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    sar = _parse_ratio(video.get("sample_aspect_ratio")) or 1.0
    square_width = max(1, round(width * sar))
    display_width, display_height = (height, square_width) if abs(rotation) in {90, 270} else (square_width, height)
    duration = _float(video.get("duration")) or _float((raw.get("format") or {}).get("duration"))
    video_bitrate = _int(video.get("bit_rate"))
    format_bitrate = _int((raw.get("format") or {}).get("bit_rate"))
    return {
        "durationMs": round(duration * 1000) if duration is not None else None,
        "formatBitrateKbps": round(format_bitrate / 1000) if format_bitrate else None,
        "video": {
            "codec": video.get("codec_name"),
            "width": width,
            "height": height,
            "displayWidth": display_width,
            "displayHeight": display_height,
            "bitrateKbps": round(video_bitrate / 1000) if video_bitrate else None,
            "fps": _parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
            "pixelFormat": video.get("pix_fmt"),
            "rotation": rotation,
            "sampleAspectRatio": video.get("sample_aspect_ratio") or "1:1",
        },
        "audio": [
            {"codec": stream.get("codec_name"), "channels": stream.get("channels"), "sampleRate": _int(stream.get("sample_rate"))}
            for stream in streams if stream.get("codec_type") == "audio"
        ],
        "subtitles": [
            {"codec": stream.get("codec_name"), "language": (stream.get("tags") or {}).get("language")}
            for stream in streams if stream.get("codec_type") == "subtitle"
        ],
        "sizeBytes": size_bytes,
    }


def decide_parameters(
    source: dict[str, Any],
    requested: TranscodeParams,
    capabilities: CapabilitySnapshot,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    video = source["video"]
    reasons: list[dict[str, str]] = []
    source_height = int(video.get("displayHeight") or video.get("height") or 0)
    source_width = int(video.get("displayWidth") or video.get("width") or 0)
    if source_width <= 0 or source_height <= 0:
        raise MediaError("invalid_dimensions", "源视频分辨率无效")

    target_height = source_height if requested.height == -1 else min(source_height, requested.height)
    if requested.height != -1 and source_height < requested.height:
        reasons.append(_reason("height", "resolution_not_upscaled", f"源视频仅 {source_height}p，保持原分辨率"))
    target_width = max(2, round((source_width * target_height / source_height) / 2) * 2)
    target_height = max(2, round(target_height / 2) * 2)
    rotation = int(video.get("rotation") or 0) % 360
    coded_width = int(video.get("width") or source_width)
    coded_height = int(video.get("height") or source_height)
    oriented_width, oriented_height = (coded_height, coded_width) if rotation in {90, 270} else (coded_width, coded_height)
    sar = _parse_ratio(video.get("sampleAspectRatio")) or 1.0
    scale = (target_width, target_height) != (oriented_width, oriented_height) or not math.isclose(sar, 1.0)
    transform = scale or rotation != 0

    source_bitrate = video.get("bitrateKbps") or source.get("formatBitrateKbps")
    bitrate = requested.bitrate_kbps
    if requested.smart_bitrate_cap and source_bitrate and source_bitrate < bitrate:
        bitrate = max(100, int(source_bitrate))
        reasons.append(_reason("bitrateKbps", "smart_bitrate_cap", f"源码率 {source_bitrate} kbps 低于用户上限"))
    elif requested.smart_bitrate_cap and not source_bitrate:
        reasons.append(_reason("bitrateKbps", "source_bitrate_unknown", "无法确定源码率，使用用户上限"))

    profile = registry.profiles[requested.hardware_mode]
    backend = registry.backend_for(profile.id)
    request = VideoRequest(
        source_codec=str(video.get("codec")), video_codec=requested.video_codec,
        pixel_format=str(video.get("pixelFormat") or "yuv420p"),
        settings=VideoSettings(
            width=target_width, height=target_height, transform_required=transform,
            rotation=rotation, normalize_sar=not math.isclose(sar, 1.0),
            bitrate_kbps=bitrate, frame_rate=requested.frame_rate,
            rate_control=requested.rate_control,
        ),
    )
    plan = backend.plan_video(request, profile, capabilities.for_backend(backend.id))

    audio_codecs = {str(item.get("codec")) for item in source.get("audio", [])}
    if requested.container == "mp4" and requested.audio_strategy == "copy" and not audio_codecs.issubset({"aac", "mp3", "ac3", "eac3", "alac"}):
        raise MediaError("container_audio_incompatible", "MP4 无法安全复制当前音频编码，请选择 AAC 或 MKV")
    subtitle_codecs = {str(item.get("codec")) for item in source.get("subtitles", [])}
    subtitle_codec = None
    if requested.subtitle_strategy == "copy":
        if requested.container == "mp4" and not subtitle_codecs.issubset({"mov_text", "tx3g"}):
            raise MediaError("container_subtitle_incompatible", "MP4 无法直接复制当前字幕，请选择自动兼容、丢弃或 MKV")
        subtitle_codec = "copy"
    elif requested.subtitle_strategy == "auto" and subtitle_codecs:
        if requested.container == "mkv":
            subtitle_codec = "copy"
        elif subtitle_codecs.issubset({"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "tx3g"}):
            subtitle_codec = "mov_text"
            reasons.append(_reason("subtitleStrategy", "container_compatibility", "文本字幕转换为 MP4 mov_text"))
        else:
            raise MediaError("container_subtitle_incompatible", "MP4 无法安全转换当前图形字幕")

    effective = {
        "hardwareMode": requested.hardware_mode,
        "videoCodec": requested.video_codec,
        "encoder": plan.encoder,
        "container": requested.container,
        "width": target_width,
        "height": target_height,
        "scaleRequired": scale,
        "transformRequired": transform,
        "rotation": rotation,
        "normalizeSar": not math.isclose(sar, 1.0),
        "scaleFilter": plan.scale_filter,
        "bitrateKbps": bitrate,
        "frameRate": requested.frame_rate,
        "rateControl": requested.rate_control,
        "audioCodec": {"copy": "copy", "aac": "aac", "drop": None}[requested.audio_strategy],
        "subtitleCodec": subtitle_codec,
    }
    if plan.device is not None:
        effective.update(hardwareDevice=plan.device, pixelFormat=plan.pixel_format)
        if profile.backend_id == "qsv" and requested.rate_control == "vbr":
            reasons.append(_reason("bitrateKbps", "qsv_vbr_average",
                                   "QSV VBR 平均码率为上限的 90%，峰值保持用户码率上限"))
    return effective, reasons


def build_ffmpeg_argv(
    settings: Settings,
    input_path: Path,
    output_path: Path,
    effective: dict[str, Any],
) -> list[str]:
    argv = [settings.ffmpeg_path, "-nostdin", "-hide_banner", "-progress", "pipe:1", "-nostats", "-stats_period", "0.5"]
    plan = restore_video_plan(effective, registry)
    video_args = registry.backend_for(plan.profile.id).build_video_args(plan)
    argv.extend(video_args.before_input)
    argv += ["-i", str(input_path), "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?"]
    argv.extend(video_args.after_input)
    argv += ["-c:a", effective["audioCodec"]] if effective.get("audioCodec") else ["-an"]
    argv += ["-c:s", effective["subtitleCodec"]] if effective.get("subtitleCodec") else ["-sn"]
    argv += ["-f", "matroska" if effective["container"] == "mkv" else "mp4", "-y", str(output_path)]
    return argv


def parse_progress_block(block: dict[str, str], duration_ms: int | None) -> dict[str, Any]:
    out_time_ms = _progress_time_ms(block)
    speed = _float((block.get("speed") or "").rstrip("x"))
    percent = None
    eta = None
    if duration_ms and out_time_ms is not None and duration_ms > 0:
        percent = round(max(0.0, min(100.0, out_time_ms / duration_ms * 100)), 1)
        if speed and speed > 0:
            eta = max(0, round((duration_ms - out_time_ms) / 1000 / speed))
    return {
        "frame": _int(block.get("frame")),
        "fps": _float(block.get("fps")),
        "bitrateKbps": _parse_bitrate(block.get("bitrate")),
        "outTimeMs": out_time_ms,
        "totalSizeBytes": _int(block.get("total_size")),
        "speed": speed,
        "percent": percent,
        "etaSeconds": eta,
        "progress": block.get("progress", "continue"),
    }


def _progress_time_ms(block: dict[str, str]) -> int | None:
    if block.get("out_time_us"):
        value = _int(block["out_time_us"])
        return round(value / 1000) if value is not None else None
    if block.get("out_time_ms"):
        value = _int(block["out_time_ms"])
        # FFmpeg historically labels microseconds as out_time_ms. Prefer the formatted clock
        # when values disagree by orders of magnitude.
        clock = _clock_ms(block.get("out_time"))
        if value is None:
            return clock
        candidate = round(value / 1000)
        return clock if clock is not None and abs(clock - candidate) > 2000 else candidate
    return _clock_ms(block.get("out_time"))


def _clock_ms(value: str | None) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"(\d+):(\d+):(\d+(?:\.\d+)?)", value)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)


def _rotation(stream: dict[str, Any]) -> int:
    value = (stream.get("tags") or {}).get("rotate")
    for side_data in stream.get("side_data_list") or []:
        if side_data.get("rotation") is not None:
            value = side_data["rotation"]
    try:
        return round(float(value or 0)) % 360
    except (TypeError, ValueError):
        return 0


def _parse_rate(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        return round(float(numerator) / float(denominator), 3) if float(denominator) else None
    return _float(value)


def _parse_ratio(value: str | None) -> float | None:
    if not value or value in {"0:1", "N/A"}:
        return None
    separator = ":" if ":" in value else "/" if "/" in value else None
    if separator:
        numerator, denominator = value.split(separator, 1)
        return float(numerator) / float(denominator) if float(denominator) else None
    return _float(value)


def _parse_bitrate(value: str | None) -> float | None:
    if not value or value == "N/A":
        return None
    match = re.search(r"([\d.]+)\s*kbits/s", value)
    return float(match.group(1)) if match else _float(value)


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _reason(field: str, code: str, message: str) -> dict[str, str]:
    return {"field": field, "code": code, "message": message}


async def _available(binary: str) -> bool:
    try:
        await _capture([binary, "version"])
        return True
    except (FileNotFoundError, MediaError):
        return False


async def _capture(argv: list[str]) -> str:
    return await _capture_output(argv, include_stderr=True)


async def _capture_stdout(
    argv: list[str],
    *,
    process_observer: Callable[[asyncio.subprocess.Process | None], None] | None = None,
) -> str:
    """Capture machine-readable stdout without appending diagnostic stderr."""
    return await _capture_output(
        argv,
        include_stderr=False,
        process_observer=process_observer,
    )


async def _capture_output(
    argv: list[str],
    *,
    include_stderr: bool,
    process_observer: Callable[[asyncio.subprocess.Process | None], None] | None = None,
) -> str:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if process_observer:
        process_observer(process)
    try:
        stdout, stderr = await process.communicate()
    except BaseException:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.communicate()
        raise
    finally:
        if process_observer:
            process_observer(None)
    if process.returncode != 0:
        raise MediaError("media_command_failed", stderr.decode(errors="replace").strip()[-2000:])
    output = stdout.decode(errors="replace")
    return output + stderr.decode(errors="replace") if include_stderr else output

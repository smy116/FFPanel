from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .schemas import TranscodeParams


class MediaError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class CapabilitySnapshot:
    ffmpeg_version: str | None
    ffprobe_available: bool
    rclone_available: bool
    mpp_available: bool
    rga_available: bool
    encoders: list[str]
    decoders: list[str]
    filters: list[str]
    devices: dict[str, bool]
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ffmpegVersion": self.ffmpeg_version,
            "ffprobeAvailable": self.ffprobe_available,
            "rcloneAvailable": self.rclone_available,
            "mppAvailable": self.mpp_available,
            "rgaAvailable": self.rga_available,
            "encoders": self.encoders,
            "decoders": self.decoders,
            "filters": self.filters,
            "devices": self.devices,
            "error": self.error,
        }


async def detect_capabilities(settings: Settings) -> CapabilitySnapshot:
    if settings.mock_media:
        return CapabilitySnapshot("mock-1.0", True, False, True, True, ["h264_rkmpp", "hevc_rkmpp", "libx264", "libx265"], ["h264_rkmpp", "hevc_rkmpp"], ["scale_rkrga"], {}, None)
    try:
        version, encoders, decoders, filters = await asyncio.gather(
            _capture([settings.ffmpeg_path, "-version"]),
            _capture([settings.ffmpeg_path, "-hide_banner", "-encoders"]),
            _capture([settings.ffmpeg_path, "-hide_banner", "-decoders"]),
            _capture([settings.ffmpeg_path, "-hide_banner", "-filters"]),
        )
        encoder_names = _extract_capabilities(encoders, {"h264_rkmpp", "hevc_rkmpp", "libx264", "libx265"})
        decoder_names = _extract_capabilities(
            decoders,
            {
                "av1_rkmpp", "h263_rkmpp", "h264_rkmpp", "hevc_rkmpp", "mjpeg_rkmpp",
                "mpeg1_rkmpp", "mpeg2_rkmpp", "mpeg4_rkmpp", "vp8_rkmpp", "vp9_rkmpp",
            },
        )
        filter_names = _extract_capabilities(filters, {"scale_rkrga", "vpp_rkrga", "overlay_rkrga"})
        device_paths = (
            "/dev/dri", "/dev/dma_heap", "/dev/rga", "/dev/mpp_service", "/dev/mpp-service",
            "/dev/vpu_service", "/dev/vpu-service", "/dev/hevc_service", "/dev/hevc-service",
            "/dev/rkvdec", "/dev/rkvenc", "/dev/vepu", "/dev/h265e", "/dev/iep",
        )
        devices = {path: Path(path).exists() for path in device_paths}
        mpp_nodes = {path for path in device_paths if path not in {"/dev/dri", "/dev/dma_heap", "/dev/rga", "/dev/iep"}}
        mpp = bool({"h264_rkmpp", "hevc_rkmpp"} & encoder_names) and bool(decoder_names) and any(
            devices[path] for path in mpp_nodes
        )
        rga = "scale_rkrga" in filter_names and devices.get("/dev/rga", False)
        return CapabilitySnapshot(version.splitlines()[0], True, await _available(settings.rclone_path), mpp, rga, sorted(encoder_names), sorted(decoder_names), sorted(filter_names), devices)
    except (FileNotFoundError, MediaError) as exc:
        return CapabilitySnapshot(None, False, await _available(settings.rclone_path), False, False, [], [], [], {}, str(exc))


async def probe_media(settings: Settings, path: Path) -> dict[str, Any]:
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
    output = await _capture([
        settings.ffprobe_path, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ])
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

    encoder = {
        ("cpu_cpu", "h264"): "libx264", ("cpu_cpu", "hevc"): "libx265",
        ("cpu_mpp", "h264"): "h264_rkmpp", ("cpu_mpp", "hevc"): "hevc_rkmpp",
        ("mpp_mpp", "h264"): "h264_rkmpp", ("mpp_mpp", "hevc"): "hevc_rkmpp",
    }[(requested.hardware_mode, requested.video_codec)]
    source_codec = str(video.get("codec"))
    decoder_codec = {
        "h265": "hevc", "avc": "h264", "mpeg1video": "mpeg1", "mpeg2video": "mpeg2",
    }.get(source_codec, source_codec)
    decoder = f"{decoder_codec}_rkmpp"
    needs_rga = requested.hardware_mode == "mpp_mpp" and transform
    if requested.hardware_mode == "mpp_mpp" and (
        not capabilities.mpp_available
        or decoder not in capabilities.decoders
        or (needs_rga and not capabilities.rga_available)
        or (rotation != 0 and "vpp_rkrga" not in capabilities.filters)
    ):
        raise MediaError("hardware_unavailable", "MPP/RGA 能力不足，无法执行所选硬件方案")
    if requested.hardware_mode == "cpu_mpp" and not capabilities.mpp_available:
        raise MediaError("hardware_unavailable", "MPP 编码器不可用")
    if encoder not in capabilities.encoders:
        raise MediaError("encoder_unavailable", f"所选编码器不可用：{encoder}")

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
        "encoder": encoder,
        "container": requested.container,
        "width": target_width,
        "height": target_height,
        "scaleRequired": scale,
        "transformRequired": transform,
        "rotation": rotation,
        "normalizeSar": not math.isclose(sar, 1.0),
        "scaleFilter": "vpp_rkrga" if rotation and requested.hardware_mode == "mpp_mpp" else "scale_rkrga" if needs_rga else "scale" if transform else None,
        "bitrateKbps": bitrate,
        "frameRate": requested.frame_rate,
        "gop": requested.gop,
        "audioCodec": {"copy": "copy", "aac": "aac", "drop": None}[requested.audio_strategy],
        "subtitleCodec": subtitle_codec,
    }
    return effective, reasons


def build_ffmpeg_argv(
    settings: Settings,
    input_path: Path,
    output_path: Path,
    effective: dict[str, Any],
) -> list[str]:
    argv = [settings.ffmpeg_path, "-nostdin", "-hide_banner", "-progress", "pipe:1", "-nostats", "-stats_period", "0.5"]
    if effective["hardwareMode"] == "mpp_mpp":
        argv += ["-hwaccel", "rkmpp", "-hwaccel_output_format", "drm_prime", "-afbc", "rga"]
    if effective.get("rotation"):
        argv += ["-noautorotate"]
    argv += ["-i", str(input_path), "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?"]
    if effective.get("transformRequired"):
        rotation = int(effective.get("rotation") or 0)
        if effective["scaleFilter"] in {"scale_rkrga", "vpp_rkrga"}:
            if rotation:
                transpose = {90: "cclock", 180: "reversal", 270: "clock"}[rotation]
                video_filter = f"vpp_rkrga=w={effective['width']}:h={effective['height']}:format=nv12:transpose={transpose}"
            else:
                video_filter = f"scale_rkrga=w={effective['width']}:h={effective['height']}:format=nv12"
        else:
            filters = []
            if rotation == 90:
                filters.append("transpose=cclock")
            elif rotation == 180:
                filters.extend(["hflip", "vflip"])
            elif rotation == 270:
                filters.append("transpose=clock")
            filters.append(f"scale={effective['width']}:{effective['height']}:flags=fast_bilinear")
            filters.append("format=yuv420p")
            video_filter = ",".join(filters)
        if effective.get("normalizeSar"):
            video_filter += ",setsar=1"
        argv += ["-vf", video_filter]
    argv += ["-c:v", effective["encoder"], "-b:v", f"{effective['bitrateKbps']}k", "-maxrate", f"{effective['bitrateKbps']}k", "-bufsize", f"{effective['bitrateKbps'] * 2}k", "-g", str(effective["gop"])]
    if effective["hardwareMode"] != "cpu_cpu":
        argv += ["-rc_mode", "VBR"]
    if effective["frameRate"] != "source":
        argv += ["-r", effective["frameRate"]]
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


def _extract_capabilities(output: str, candidates: set[str]) -> set[str]:
    return {candidate for candidate in candidates if re.search(rf"\b{re.escape(candidate)}\b", output)}


async def _available(binary: str) -> bool:
    try:
        await _capture([binary, "version"])
        return True
    except (FileNotFoundError, MediaError):
        return False


async def _capture(argv: list[str]) -> str:
    process = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise MediaError("media_command_failed", stderr.decode(errors="replace").strip()[-2000:])
    return stdout.decode(errors="replace") + stderr.decode(errors="replace")

"""Public media contract checks, established before extracting hardware backends."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ffpanel.config import Settings
from ffpanel.media import CapabilitySnapshot, build_ffmpeg_argv, decide_parameters
from ffpanel.schemas import TranscodeParams


@pytest.mark.parametrize("mode", ["cpu_cpu", "cpu_mpp", "mpp_mpp"])
@pytest.mark.parametrize("codec", ["h264", "hevc"])
@pytest.mark.parametrize("rate", ["cbr", "vbr"])
@pytest.mark.parametrize("transform", ["none", "scale", "sar", "90", "180", "270"])
def test_legacy_video_contract(mode: str, codec: str, rate: str, transform: str) -> None:
    rotation = int(transform) if transform.isdigit() else 0
    width, height = (720, 1280) if rotation in {90, 270} else (1280, 720)
    sar = transform == "sar"
    resize = transform == "scale"
    if sar:
        width = 1536
    target_width, target_height = (640, 360) if resize else (width, height)
    source = {
        "video": {
            "codec": "h264",
            "width": 1280,
            "height": 720,
            "displayWidth": width,
            "displayHeight": height,
            "rotation": rotation,
            "sampleAspectRatio": "6:5" if sar else "1:1",
            "bitrateKbps": 3000,
        },
        "audio": [{"codec": "aac"}],
        "subtitles": [],
    }
    caps = CapabilitySnapshot(
        "test",
        True,
        True,
        True,
        True,
        ["libx264", "libx265", "h264_rkmpp", "hevc_rkmpp"],
        ["h264_rkmpp"],
        ["scale_rkrga", "vpp_rkrga"],
        {},
    )
    params = TranscodeParams.model_validate(
        {
            "hardwareMode": mode,
            "videoCodec": codec,
            "rateControl": rate,
            "height": 360 if resize else -1,
            "frameRate": "25",
        }
    )
    effective, reasons = decide_parameters(source, params, caps)
    encoder = (
        {"h264": "libx264", "hevc": "libx265"}[codec] if mode == "cpu_cpu" else f"{codec}_rkmpp"
    )
    has_transform = transform != "none"
    scale_filter = None
    if has_transform:
        scale_filter = (
            ("vpp_rkrga" if rotation else "scale_rkrga") if mode == "mpp_mpp" else "scale"
        )
    assert reasons == []
    assert effective == {
        "hardwareMode": mode,
        "videoCodec": codec,
        "encoder": encoder,
        "container": "mp4",
        "width": target_width,
        "height": target_height,
        "scaleRequired": sar or resize,
        "transformRequired": has_transform,
        "rotation": rotation,
        "normalizeSar": sar,
        "scaleFilter": scale_filter,
        "bitrateKbps": 2000,
        "frameRate": "25",
        "rateControl": rate,
        "audioCodec": "copy",
        "subtitleCodec": None,
    }
    expected = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-progress",
        "pipe:1",
        "-nostats",
        "-stats_period",
        "0.5",
    ]
    if mode == "mpp_mpp":
        expected += ["-hwaccel", "rkmpp", "-hwaccel_output_format", "drm_prime", "-afbc", "rga"]
    if rotation:
        expected += ["-noautorotate"]
    expected += ["-i", "input.mkv", "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?"]
    if has_transform:
        if mode == "mpp_mpp":
            vf = f"{scale_filter}=w={target_width}:h={target_height}:format=nv12"
            if rotation:
                vf += ":transpose=" + {90: "cclock", 180: "reversal", 270: "clock"}[rotation]
        else:
            prefix = {0: "", 90: "transpose=cclock,", 180: "hflip,vflip,", 270: "transpose=clock,"}
            vf = prefix[rotation] + f"scale={target_width}:{target_height}:flags=fast_bilinear"
            vf += ",format=yuv420p"
        if sar:
            vf += ",setsar=1"
        expected += ["-vf", vf]
    expected += ["-c:v", encoder, "-b:v", "2000k"]
    if rate == "cbr":
        expected += ["-minrate", "2000k"]
    expected += ["-maxrate", "2000k", "-bufsize", "4000k"]
    if mode != "cpu_cpu":
        expected += ["-rc_mode", rate.upper()]
    expected += ["-r", "25", "-c:a", "copy", "-sn", "-f", "mp4", "-y", "output.mp4"]
    # Persisted decisions must remain sufficient to rebuild argv without probing again.
    restored = json.loads(json.dumps(effective))
    assert (
        build_ffmpeg_argv(
            Settings(ffmpeg_path="ffmpeg"),
            Path("input.mkv"),
            Path("output.mp4"),
            restored,
        )
        == expected
    )

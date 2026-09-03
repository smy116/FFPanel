from __future__ import annotations

from pathlib import Path

import pytest

import ffpanel.media as media_module
from ffpanel.config import Settings
from ffpanel.media import (
    CapabilitySnapshot,
    MediaError,
    build_ffmpeg_argv,
    decide_parameters,
    normalize_probe,
    parse_progress_block,
    probe_media,
)
from ffpanel.schemas import TranscodeParams

CAPABILITIES = CapabilitySnapshot(
    "test", True, True, True, True,
    ["h264_rkmpp", "hevc_rkmpp", "libx264", "libx265"],
    ["h264_rkmpp", "hevc_rkmpp"], ["scale_rkrga", "vpp_rkrga"], {}, None,
)


def source(height: int = 720, bitrate: int | None = 1400) -> dict:
    return {
        "durationMs": 120_000,
        "formatBitrateKbps": bitrate,
        "video": {
            "codec": "h264", "width": height * 16 // 9, "height": height,
            "displayWidth": height * 16 // 9, "displayHeight": height,
            "bitrateKbps": bitrate, "fps": 30, "pixelFormat": "yuv420p", "rotation": 0,
        },
        "audio": [{"codec": "aac"}], "subtitles": [],
    }


def test_does_not_upscale_and_caps_bitrate() -> None:
    effective, reasons = decide_parameters(
        source(), TranscodeParams(height=1080, bitrate_kbps=2000), CAPABILITIES
    )
    assert effective["height"] == 720
    assert effective["bitrateKbps"] == 1400
    assert {item["code"] for item in reasons} == {"resolution_not_upscaled", "smart_bitrate_cap"}


def test_rotation_changes_display_dimensions() -> None:
    raw = {
        "streams": [{
            "codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
            "avg_frame_rate": "30000/1001", "side_data_list": [{"rotation": -90}],
        }],
        "format": {"duration": "10.5"},
    }
    result = normalize_probe(raw)
    assert result["video"]["displayWidth"] == 1080
    assert result["video"]["displayHeight"] == 1920
    assert result["video"]["fps"] == pytest.approx(29.97, abs=0.01)


def test_sample_aspect_ratio_is_normalized_to_display_width() -> None:
    raw = {
        "streams": [{
            "codec_type": "video", "codec_name": "h264", "width": 720, "height": 576,
            "sample_aspect_ratio": "16:15", "avg_frame_rate": "25/1",
        }],
        "format": {"duration": "10"},
    }
    result = normalize_probe(raw)
    assert result["video"]["displayWidth"] == 768
    effective, _ = decide_parameters(result, TranscodeParams(hardware_mode="cpu_cpu", height=-1), CAPABILITIES)
    assert effective["width"] == 768
    assert effective["normalizeSar"] is True


async def test_probe_media_ignores_ffprobe_diagnostics_from_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = Path(__file__)

    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return (
                b"".join((
                    b'{"streams":[{"codec_type":"video","codec_name":"h264",',
                    b'"width":1280,"height":720}],"format":{"duration":"1"}}',
                )),
                b"[h264 @ 0x1] incomplete frame\n",
            )

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> FakeProcess:
        del args, kwargs
        return FakeProcess()

    monkeypatch.setattr(media_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    result = await probe_media(Settings(mock_media=False), input_path)

    assert result["video"]["codec"] == "h264"


def test_full_hardware_rotation_uses_rga_vpp_without_autorotate() -> None:
    value = source(1080)
    value["video"] |= {
        "width": 1920, "height": 1080, "displayWidth": 1080, "displayHeight": 1920,
        "rotation": 270,
    }
    effective, _ = decide_parameters(value, TranscodeParams(hardware_mode="mpp_mpp", height=720), CAPABILITIES)
    argv = build_ffmpeg_argv(Settings(), Path("input.mkv"), Path("output.mp4"), effective)
    assert "-noautorotate" in argv
    assert any("vpp_rkrga" in argument and "transpose=clock" in argument for argument in argv)


def test_gpu_selection_never_silently_falls_back() -> None:
    unavailable = CapabilitySnapshot("test", True, False, False, False, [], [], [], {}, None)
    with pytest.raises(MediaError, match="MPP/RGA"):
        decide_parameters(source(2160), TranscodeParams(hardware_mode="mpp_mpp"), unavailable)


def test_mp4_rejects_incompatible_audio_copy() -> None:
    value = source()
    value["audio"] = [{"codec": "dts"}]
    with pytest.raises(MediaError, match="AAC"):
        decide_parameters(value, TranscodeParams(container="mp4", audio_strategy="copy"), CAPABILITIES)


def test_structured_progress_and_unknown_duration() -> None:
    progress = parse_progress_block(
        {"frame": "150", "fps": "75.2", "out_time_us": "30000000", "speed": "3.0x", "progress": "continue"},
        60_000,
    )
    assert progress["outTimeMs"] == 30_000
    assert progress["percent"] == 50.0
    assert progress["etaSeconds"] == 10
    unknown = parse_progress_block({"frame": "10", "out_time": "00:00:04.500", "progress": "continue"}, None)
    assert unknown["outTimeMs"] == 4500
    assert unknown["percent"] is None
    assert unknown["etaSeconds"] is None

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ffpanel import media
from ffpanel.config import Settings
from ffpanel.hardware import registry
from ffpanel.hardware.compat import CapabilitySnapshot
from ffpanel.hardware.cpu import CpuBackend
from ffpanel.hardware.registry import HardwareRegistry
from ffpanel.hardware.rockchip import RockchipBackend
from ffpanel.hardware.types import (
    BackendCapabilities,
    FFmpegInventory,
    HardwareProfile,
    MediaError,
    VideoArguments,
    VideoPlan,
    VideoRequest,
    VideoSettings,
)
from ffpanel.schemas import TranscodeParams


def inventory() -> FFmpegInventory:
    return FFmpegInventory(
        frozenset({"h264_rkmpp", "hevc_rkmpp", "libx264", "libx265", "h264_nvenc"}),
        frozenset({"h264_rkmpp", "hevc_rkmpp", "mpeg1_rkmpp", "mpeg2_rkmpp", "h264"}),
        frozenset({"scale_rkrga", "vpp_rkrga", "overlay_rkrga", "scale_cuda"}),
        {"/dev/mpp_service": True, "/dev/rga": True},
    )


def request(*, transform: bool = False, rotation: int = 0) -> VideoRequest:
    return VideoRequest(
        "h264",
        "h264",
        VideoSettings(1280, 720, transform, rotation, False, 2000, "source", "vbr"),
    )


@pytest.mark.parametrize(
    ("change", "expected_mpp", "expected_rga"),
    [
        ({}, True, True),
        ({"encoders": frozenset()}, False, True),
        ({"decoders": frozenset()}, False, True),
        ({"devices": {"/dev/rga": True}}, False, True),
        ({"devices": {"/dev/mpp_service": True}}, True, False),
        ({"filters": frozenset({"vpp_rkrga"})}, True, False),
    ],
)
def test_probe_preserves_mpp_and_rga_requirements(
    change: dict,
    expected_mpp: bool,
    expected_rga: bool,
) -> None:
    capabilities = RockchipBackend().probe(replace(inventory(), **change))
    assert capabilities.features == {"mpp": expected_mpp, "rga": expected_rga}
    assert "h264_nvenc" not in capabilities.encoders
    assert "h264" not in capabilities.decoders
    assert "scale_cuda" not in capabilities.filters


@pytest.mark.parametrize(
    ("mode", "missing", "transform", "rotation", "code", "message"),
    [
        ("mpp_mpp", "mpp", False, 0, "hardware_unavailable", "MPP/RGA"),
        ("cpu_mpp", "mpp", False, 0, "hardware_unavailable", "MPP 编码器不可用"),
        ("mpp_mpp", "decoder", False, 0, "hardware_unavailable", "MPP/RGA"),
        ("mpp_mpp", "rga", True, 0, "hardware_unavailable", "MPP/RGA"),
        ("mpp_mpp", "vpp", True, 90, "hardware_unavailable", "MPP/RGA"),
        ("mpp_mpp", "encoder", False, 0, "encoder_unavailable", "h264_rkmpp"),
        ("cpu_mpp", "encoder", False, 0, "encoder_unavailable", "h264_rkmpp"),
        ("cpu_cpu", "encoder", False, 0, "encoder_unavailable", "libx264"),
    ],
)
def test_missing_capability_errors(
    mode: str,
    missing: str,
    transform: bool,
    rotation: int,
    code: str,
    message: str,
) -> None:
    backend = registry.backend_for(mode)
    caps = backend.probe(inventory())
    if missing in {"mpp", "rga"}:
        caps = replace(caps, features=caps.features | {missing: False})
    elif missing == "decoder":
        caps = replace(caps, decoders=frozenset())
    elif missing == "vpp":
        caps = replace(caps, filters=caps.filters - {"vpp_rkrga"})
    else:
        caps = replace(caps, encoders=frozenset())
    with pytest.raises(MediaError, match=message) as caught:
        backend.plan_video(
            request(transform=transform, rotation=rotation), registry.profiles[mode], caps
        )
    assert caught.value.code == code


def test_hardware_validation_precedes_encoder_and_container_checks() -> None:
    caps = CapabilitySnapshot("test", True, True, False, False, [], [], [], {})
    source = {"video": {"width": 1280, "height": 720}, "audio": [{"codec": "dts"}]}
    with pytest.raises(MediaError, match="MPP/RGA") as caught:
        media.decide_parameters(source, TranscodeParams(), caps)
    assert caught.value.code == "hardware_unavailable"


def test_software_decode_does_not_require_the_source_decoder_or_rga() -> None:
    backend = RockchipBackend()
    caps = backend.probe(inventory())
    caps = replace(caps, decoders=frozenset(), filters=frozenset(), features={"mpp": True})
    plan = backend.plan_video(
        request(transform=True, rotation=90), registry.profiles["cpu_mpp"], caps
    )
    assert plan.scale_filter == "scale"
    assert "-hwaccel" not in backend.build_video_args(plan).before_input


def test_hardware_decode_without_transform_does_not_require_rga() -> None:
    backend = RockchipBackend()
    caps = replace(backend.probe(inventory()), filters=frozenset(), features={"mpp": True})
    plan = backend.plan_video(request(), registry.profiles["mpp_mpp"], caps)
    assert plan.scale_filter is None
    assert "-vf" not in backend.build_video_args(plan).after_input


@pytest.mark.parametrize("codec", ["h265", "avc", "mpeg1video", "mpeg2video"])
def test_rockchip_source_codec_aliases(codec: str) -> None:
    backend = RockchipBackend()
    backend.plan_video(
        replace(request(), source_codec=codec),
        registry.profiles["mpp_mpp"],
        backend.probe(inventory()),
    )


class TestBackend:
    __test__ = False
    id = "test"
    device_paths = ("/test/device",)

    def __init__(self, profiles: tuple[HardwareProfile, ...]) -> None:
        self._profiles = profiles
        self.calls: list[str] = []

    def profiles(self) -> tuple[HardwareProfile, ...]:
        return self._profiles

    def probe(self, inventory: FFmpegInventory) -> BackendCapabilities:
        self.calls.append("probe")
        return BackendCapabilities(self.id, inventory.encoders, frozenset(), frozenset(), {}, {})

    def plan_video(
        self,
        request: VideoRequest,
        profile: HardwareProfile,
        capabilities: BackendCapabilities,
    ) -> VideoPlan:
        self.calls.append("plan")
        assert capabilities.backend_id == self.id
        return VideoPlan(profile, "test_encoder", request.settings, None)

    def build_video_args(self, plan: VideoPlan) -> VideoArguments:
        self.calls.append("build")
        assert plan.encoder == "test_encoder"
        return VideoArguments(("-test_input", "device"), ("-c:v", plan.encoder))


@pytest.mark.parametrize(
    ("profiles", "message"),
    [
        ((HardwareProfile("x", "X", "test", "software"),) * 2, "Duplicate profile"),
        ((HardwareProfile("x", "X", "test", "software", "missing"),), "Unknown fallback"),
        ((HardwareProfile("x", "X", "test", "software", "x"),), "Cyclic fallback"),
        (
            (
                HardwareProfile("x", "X", "test", "software", "y"),
                HardwareProfile("y", "Y", "test", "software", "x"),
            ),
            "Cyclic fallback",
        ),
        ((HardwareProfile("x", "X", "other", "software"),), "Profile backend mismatch"),
    ],
)
def test_registry_rejects_invalid_profiles(
    profiles: tuple[HardwareProfile, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        HardwareRegistry((TestBackend(profiles),))


def test_registry_rejects_duplicate_backends_and_profiles_across_backends() -> None:
    with pytest.raises(ValueError, match="Duplicate backend"):
        HardwareRegistry((CpuBackend(), CpuBackend()))
    duplicate = HardwareProfile("cpu_cpu", "Duplicate", "test", "software")
    with pytest.raises(ValueError, match="Duplicate profile"):
        HardwareRegistry((CpuBackend(), TestBackend((duplicate,))))


def test_test_backend_uses_the_same_media_composition_without_replanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reuse a legacy wire mode so no production schema or registration is modified.
    profile = HardwareProfile("cpu_cpu", "Test", "test", "software")
    backend = TestBackend((profile,))
    custom = HardwareRegistry((backend,))
    assert custom.device_paths == ("/test/device",)
    assert custom.probe(inventory())["test"].backend_id == "test"
    monkeypatch.setattr(media, "registry", custom)
    caps = CapabilitySnapshot("test", True, True, False, False, [], [], [], {})
    effective, _ = media.decide_parameters(
        {"video": {"width": 1280, "height": 720}},
        TranscodeParams(hardware_mode="cpu_cpu"),
        caps,
    )
    argv = media.build_ffmpeg_argv(
        Settings(ffmpeg_path="ffmpeg"),
        Path("in.mkv"),
        Path("out.mp4"),
        effective,
    )
    assert argv == [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-progress",
        "pipe:1",
        "-nostats",
        "-stats_period",
        "0.5",
        "-test_input",
        "device",
        "-i",
        "in.mkv",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-map",
        "0:s?",
        "-c:v",
        "test_encoder",
        "-c:a",
        "copy",
        "-sn",
        "-f",
        "mp4",
        "-y",
        "out.mp4",
    ]
    assert backend.calls == ["probe", "plan", "build"]


async def test_capability_detection_preserves_commands_and_public_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    outputs = {
        "-version": "ffmpeg test\nconfiguration: test",
        "-encoders": " V..... h264_rkmpp\n V..... hevc_rkmpp\n V..... libx264\n V..... libx265\n"
        " V..... h264_nvenc\n V..... prefix_h264_rkmpp_suffix",
        "-decoders": " V..... h264_rkmpp\n V..... h264\n",
        "-filters": " .. scale_rkrga\n .. vpp_rkrga\n .. scale_cuda",
    }

    async def capture(argv: list[str]) -> str:
        calls.append(argv)
        return outputs[argv[-1]]

    async def available(binary: str) -> bool:
        assert binary == "rclone"
        return True

    async def capture_hwaccels(argv: list[str], timeout: float) -> str:
        assert argv == ["ffmpeg", "-hide_banner", "-hwaccels"]
        assert timeout > 0
        return "cuda qsv vaapi"

    monkeypatch.setattr(media, "_capture", capture)
    monkeypatch.setattr(media, "_available", available)
    monkeypatch.setattr(media, "capture_hardware", capture_hwaccels)
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: (
            str(path).replace("\\", "/")
            in {
                "/dev/mpp_service",
                "/dev/rga",
            }
        ),
    )
    snapshot = await media.detect_capabilities(Settings(ffmpeg_path="ffmpeg", rclone_path="rclone"))
    assert calls == [
        ["ffmpeg", "-version"],
        ["ffmpeg", "-hide_banner", "-encoders"],
        ["ffmpeg", "-hide_banner", "-decoders"],
        ["ffmpeg", "-hide_banner", "-filters"],
    ]
    public = snapshot.as_dict()
    assert {key: value for key, value in public.items() if key not in {
        "hardwareBackends", "hardwareProfiles", "recommendedHardwareMode"}} == {
        "ffmpegVersion": "ffmpeg test",
        "ffprobeAvailable": True,
        "rcloneAvailable": True,
        "mppAvailable": True,
        "rgaAvailable": True,
        "encoders": ["h264_nvenc", "h264_rkmpp", "hevc_rkmpp", "libx264", "libx265"],
        "decoders": ["h264", "h264_rkmpp"],
        "filters": ["scale_cuda", "scale_rkrga", "vpp_rkrga"],
        "devices": {
            path: path in {"/dev/mpp_service", "/dev/rga"} for path in (*registry.device_paths, "/dev/dri/renderD128")
        },
        "error": None,
    }


async def test_mock_capabilities_need_no_device_or_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected(*args: object) -> str:
        pytest.fail("mock mode must not spawn a process")

    monkeypatch.setattr(media, "_capture", unexpected)
    monkeypatch.setattr(media, "capture_hardware", unexpected)
    snapshot = await media.detect_capabilities(Settings(mock_media=True))
    public = snapshot.as_dict()
    assert {key: value for key, value in public.items() if key not in {
        "hardwareBackends", "hardwareProfiles", "recommendedHardwareMode"}} == {
        "ffmpegVersion": "mock-1.0",
        "ffprobeAvailable": True,
        "rcloneAvailable": False,
        "mppAvailable": True,
        "rgaAvailable": True,
        "encoders": ["h264_rkmpp", "hevc_rkmpp", "libx264", "libx265"],
        "decoders": ["h264_rkmpp", "hevc_rkmpp"],
        "filters": ["scale_rkrga"],
        "devices": {},
        "error": None,
    }
    effective, _ = media.decide_parameters(
        {"video": {"codec": "h264", "width": 1280, "height": 720}},
        TranscodeParams(),
        snapshot,
    )
    assert effective["encoder"] == "hevc_rkmpp"


@pytest.mark.parametrize("error", [FileNotFoundError("missing"), MediaError("command", "failed")])
async def test_capability_detection_error_keeps_legacy_shape(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    async def capture(argv: list[str]) -> str:
        raise error

    async def available(binary: str) -> bool:
        return False

    monkeypatch.setattr(media, "_capture", capture)
    monkeypatch.setattr(media, "_available", available)
    snapshot = await media.detect_capabilities(Settings())
    assert snapshot == CapabilitySnapshot(
        None, False, False, False, False, [], [], [], {}, str(error)
    )

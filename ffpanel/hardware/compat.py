"""Adapters for the unchanged public capability and parameter-decision formats."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .registry import HardwareRegistry
from .types import BackendCapabilities, VideoPlan, VideoSettings


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

    def for_backend(self, backend_id: str) -> BackendCapabilities:
        # Snapshot flags are authoritative: mock and persisted snapshots may have no nodes.
        features = (
            {"mpp": self.mpp_available, "rga": self.rga_available}
            if backend_id == "rockchip"
            else {}
        )
        return BackendCapabilities(
            backend_id,
            frozenset(self.encoders),
            frozenset(self.decoders),
            frozenset(self.filters),
            dict(self.devices),
            features,
        )


def legacy_snapshot(
    version: str,
    rclone_available: bool,
    backends: dict[str, BackendCapabilities],
    devices: dict[str, bool],
) -> CapabilitySnapshot:
    rockchip = backends["rockchip"]
    return CapabilitySnapshot(
        version,
        True,
        rclone_available,
        rockchip.features["mpp"],
        rockchip.features["rga"],
        sorted({name for caps in backends.values() for name in caps.encoders}),
        sorted({name for caps in backends.values() for name in caps.decoders}),
        sorted({name for caps in backends.values() for name in caps.filters}),
        devices,
    )


def mock_snapshot() -> CapabilitySnapshot:
    return CapabilitySnapshot(
        "mock-1.0",
        True,
        False,
        True,
        True,
        ["h264_rkmpp", "hevc_rkmpp", "libx264", "libx265"],
        ["h264_rkmpp", "hevc_rkmpp"],
        ["scale_rkrga"],
        {},
        None,
    )


def restore_video_plan(effective: dict[str, Any], registry: HardwareRegistry) -> VideoPlan:
    return VideoPlan(
        profile=registry.profiles[effective["hardwareMode"]],
        encoder=effective["encoder"],
        settings=VideoSettings(
            width=effective["width"],
            height=effective["height"],
            transform_required=bool(effective.get("transformRequired")),
            rotation=int(effective.get("rotation") or 0),
            normalize_sar=bool(effective.get("normalizeSar")),
            bitrate_kbps=effective["bitrateKbps"],
            frame_rate=effective["frameRate"],
            rate_control=effective["rateControl"],
        ),
        scale_filter=effective.get("scaleFilter"),
    )

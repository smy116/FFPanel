"""Adapters for the unchanged public capability and parameter-decision formats."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    backend_capabilities: dict[str, BackendCapabilities] = field(default_factory=dict)

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
        } | self.hardware_dict()

    def hardware_dict(self) -> dict[str, Any]:
        from . import registry

        backends: list[dict[str, Any]] = []
        profiles: list[dict[str, Any]] = []
        labels = {"cpu": "CPU", "rockchip": "MPP", "nvidia": "NVENC",
                  "qsv": "Intel QSV", "vaapi": "Intel VAAPI"}
        for backend in registry.backends.values():
            caps = self.for_backend(backend.id)
            legacy = backend.id in {"cpu", "rockchip"}
            detected = (backend.id == "cpu" or self.mpp_available or self.rga_available
                        or any(present for path, present in caps.devices.items()
                               if path in backend.device_paths
                               and path not in {"/dev/dri", "/dev/dma_heap", "/dev/iep"})) if legacy else caps.detected
            backend_profiles = []
            for profile in backend.profiles():
                codecs = []
                for codec in ("h264", "hevc"):
                    if backend.id == "cpu":
                        supported = {"h264": "libx264", "hevc": "libx265"}[codec] in caps.encoders
                    elif backend.id == "rockchip":
                        supported = self.mpp_available and f"{codec}_rkmpp" in caps.encoders
                    else:
                        supported = caps.features.get(f"encode_{codec}", False)
                        if profile.decode_mode == "hardware":
                            supported = supported and caps.features.get("decode", False) and caps.features.get("scale", False)
                    if supported:
                        codecs.append(codec)
                available = bool(codecs)
                item = {
                    "id": profile.id, "label": profile.label, "backendId": backend.id,
                    "decodeMode": profile.decode_mode, "fallback": profile.fallback,
                    "detected": detected, "available": available, "codecs": codecs,
                    "reason": None if available else (next(iter(caps.errors.values()), None)
                                                       or f"{labels[backend.id]} 当前不可用"),
                }
                profiles.append(item)
                backend_profiles.append(item)
            states = [item["available"] for item in backend_profiles]
            if backend.id == "rockchip":
                states.append(self.rga_available)
            elif not legacy:
                states.extend(caps.features.get(key, False) for key in
                              ("encode_h264", "encode_hevc", "decode_h264", "decode_hevc", "scale"))
            status = "ready" if all(states) else "partial" if any(states) else "unavailable"
            if self.error == "能力检测尚未完成":
                status = "detecting"
            backends.append({
                "id": backend.id, "label": labels[backend.id],
                "group": "intel" if backend.id in {"qsv", "vaapi"} else backend.id,
                "detected": detected, "status": status, "device": caps.device,
                "features": caps.features, "errors": caps.errors,
                "encoders": sorted(caps.encoders), "decoders": sorted(caps.decoders),
                "filters": sorted(caps.filters),
            })
        order = ("nvdec_nvenc", "cpu_nvenc", "qsv_qsv", "cpu_qsv", "vaapi_vaapi",
                 "cpu_vaapi", "mpp_mpp", "cpu_mpp", "cpu_cpu")
        recommended = next((mode for mode in order if any(
            item["id"] == mode and "hevc" in item["codecs"] for item in profiles)), "cpu_cpu")
        return {"hardwareBackends": backends, "hardwareProfiles": profiles,
                "recommendedHardwareMode": recommended}

    def for_backend(self, backend_id: str) -> BackendCapabilities:
        if backend_id in self.backend_capabilities:
            caps = self.backend_capabilities[backend_id]
            return replace(caps, features={"mpp": self.mpp_available, "rga": self.rga_available}) if backend_id == "rockchip" else caps
        # Snapshot flags are authoritative: mock and persisted snapshots may have no nodes.
        features = (
            {"mpp": self.mpp_available, "rga": self.rga_available}
            if backend_id == "rockchip"
            else {}
        )
        return BackendCapabilities(
            backend_id,
            frozenset(self.encoders) if backend_id not in {"nvidia", "qsv", "vaapi"} else frozenset(),
            frozenset(self.decoders) if backend_id not in {"nvidia", "qsv", "vaapi"} else frozenset(),
            frozenset(self.filters) if backend_id not in {"nvidia", "qsv", "vaapi"} else frozenset(),
            dict(self.devices) if backend_id == "rockchip" else {},
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
        backend_capabilities=backends,
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
        device=effective.get("hardwareDevice"),
        pixel_format=effective.get("pixelFormat"),
    )

"""Typed contracts shared by video backends; no tasks, paths, or subprocesses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..schemas import FrameRate, RateControl, VideoCodec


class MediaError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class FFmpegInventory:
    encoders: frozenset[str]
    decoders: frozenset[str]
    filters: frozenset[str]
    devices: dict[str, bool]
    hwaccels: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    backend_id: str
    encoders: frozenset[str]
    decoders: frozenset[str]
    filters: frozenset[str]
    devices: dict[str, bool]
    features: dict[str, bool]
    device: str | None = None
    detected: bool = False
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    id: str
    label: str
    backend_id: str
    decode_mode: Literal["hardware", "software"]
    fallback: str | None = None


@dataclass(frozen=True, slots=True)
class VideoSettings:
    width: int
    height: int
    transform_required: bool
    rotation: int
    normalize_sar: bool
    bitrate_kbps: int
    frame_rate: FrameRate
    rate_control: RateControl


@dataclass(frozen=True, slots=True)
class VideoRequest:
    source_codec: str
    video_codec: VideoCodec
    settings: VideoSettings
    pixel_format: str = "yuv420p"


@dataclass(frozen=True, slots=True)
class VideoPlan:
    profile: HardwareProfile
    encoder: str
    settings: VideoSettings
    scale_filter: str | None
    device: str | None = None
    pixel_format: str | None = None


@dataclass(frozen=True, slots=True)
class VideoArguments:
    before_input: tuple[str, ...]
    after_input: tuple[str, ...]


class HardwareBackend(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def device_paths(self) -> tuple[str, ...]: ...

    def probe(self, inventory: FFmpegInventory) -> BackendCapabilities: ...

    def profiles(self) -> tuple[HardwareProfile, ...]: ...

    def plan_video(
        self,
        request: VideoRequest,
        profile: HardwareProfile,
        capabilities: BackendCapabilities,
    ) -> VideoPlan: ...

    def build_video_args(self, plan: VideoPlan) -> VideoArguments: ...

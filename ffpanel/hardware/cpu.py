from .common import bitrate_args, frame_rate_args, software_filter
from .types import (
    BackendCapabilities,
    FFmpegInventory,
    HardwareProfile,
    MediaError,
    VideoArguments,
    VideoPlan,
    VideoRequest,
)


class CpuBackend:
    id = "cpu"
    device_paths: tuple[str, ...] = ()

    def profiles(self) -> tuple[HardwareProfile, ...]:
        return (HardwareProfile("cpu_cpu", "CPU 软件编解码", self.id, "software"),)

    def probe(self, inventory: FFmpegInventory) -> BackendCapabilities:
        return BackendCapabilities(
            self.id,
            inventory.encoders & {"libx264", "libx265"},
            frozenset(),
            frozenset(),
            {},
            {},
        )

    def plan_video(
        self,
        request: VideoRequest,
        profile: HardwareProfile,
        capabilities: BackendCapabilities,
    ) -> VideoPlan:
        encoder = {"h264": "libx264", "hevc": "libx265"}[request.video_codec]
        if encoder not in capabilities.encoders:
            raise MediaError("encoder_unavailable", f"所选编码器不可用：{encoder}")
        return VideoPlan(
            profile,
            encoder,
            request.settings,
            "scale" if request.settings.transform_required else None,
        )

    def build_video_args(self, plan: VideoPlan) -> VideoArguments:
        settings = plan.settings
        before = ("-noautorotate",) if settings.rotation else ()
        after = []
        if settings.transform_required:
            vf = software_filter(settings)
            if settings.normalize_sar:
                vf += ",setsar=1"
            after += ["-vf", vf]
        after += bitrate_args(plan)
        after += frame_rate_args(settings)
        return VideoArguments(before, tuple(after))

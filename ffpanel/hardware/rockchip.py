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


class RockchipBackend:
    id = "rockchip"
    device_paths = (
        "/dev/dri",
        "/dev/dma_heap",
        "/dev/rga",
        "/dev/mpp_service",
        "/dev/mpp-service",
        "/dev/vpu_service",
        "/dev/vpu-service",
        "/dev/hevc_service",
        "/dev/hevc-service",
        "/dev/rkvdec",
        "/dev/rkvenc",
        "/dev/vepu",
        "/dev/h265e",
        "/dev/iep",
    )

    def profiles(self) -> tuple[HardwareProfile, ...]:
        return (
            HardwareProfile(
                "mpp_mpp",
                "Rockchip MPP 硬件编解码",
                self.id,
                "hardware",
                "cpu_mpp",
            ),
            HardwareProfile("cpu_mpp", "CPU 软解 + MPP 编码", self.id, "software", "cpu_cpu"),
        )

    def probe(self, inventory: FFmpegInventory) -> BackendCapabilities:
        encoders = inventory.encoders & {"h264_rkmpp", "hevc_rkmpp"}
        decoders = inventory.decoders & {
            "av1_rkmpp",
            "h263_rkmpp",
            "h264_rkmpp",
            "hevc_rkmpp",
            "mjpeg_rkmpp",
            "mpeg1_rkmpp",
            "mpeg2_rkmpp",
            "mpeg4_rkmpp",
            "vp8_rkmpp",
            "vp9_rkmpp",
        }
        filters = inventory.filters & {"scale_rkrga", "vpp_rkrga", "overlay_rkrga"}
        devices = {path: inventory.devices.get(path, False) for path in self.device_paths}
        mpp_nodes = set(self.device_paths) - {"/dev/dri", "/dev/dma_heap", "/dev/rga", "/dev/iep"}
        # Keep the legacy availability rule, including its decoder requirement.
        mpp = bool(encoders) and bool(decoders) and any(devices[path] for path in mpp_nodes)
        rga = "scale_rkrga" in filters and devices["/dev/rga"]
        return BackendCapabilities(
            self.id,
            encoders,
            decoders,
            filters,
            devices,
            {"mpp": mpp, "rga": rga},
        )

    def plan_video(
        self,
        request: VideoRequest,
        profile: HardwareProfile,
        capabilities: BackendCapabilities,
    ) -> VideoPlan:
        settings = request.settings
        encoder = {"h264": "h264_rkmpp", "hevc": "hevc_rkmpp"}[request.video_codec]
        codec = {
            "h265": "hevc",
            "avc": "h264",
            "mpeg1video": "mpeg1",
            "mpeg2video": "mpeg2",
        }.get(request.source_codec, request.source_codec)
        hardware_decode = profile.decode_mode == "hardware"
        needs_rga = hardware_decode and settings.transform_required
        if hardware_decode and (
            not capabilities.features.get("mpp", False)
            or f"{codec}_rkmpp" not in capabilities.decoders
            or (needs_rga and not capabilities.features.get("rga", False))
            or (settings.rotation != 0 and "vpp_rkrga" not in capabilities.filters)
        ):
            raise MediaError("hardware_unavailable", "MPP/RGA 能力不足，无法执行所选硬件方案")
        if not hardware_decode and not capabilities.features.get("mpp", False):
            raise MediaError("hardware_unavailable", "MPP 编码器不可用")
        if encoder not in capabilities.encoders:
            raise MediaError("encoder_unavailable", f"所选编码器不可用：{encoder}")
        scale_filter = None
        if settings.rotation and hardware_decode:
            scale_filter = "vpp_rkrga"
        elif needs_rga:
            scale_filter = "scale_rkrga"
        elif settings.transform_required:
            scale_filter = "scale"
        return VideoPlan(profile, encoder, settings, scale_filter)

    def build_video_args(self, plan: VideoPlan) -> VideoArguments:
        settings = plan.settings
        before = []
        if plan.profile.decode_mode == "hardware":
            before += ["-hwaccel", "rkmpp", "-hwaccel_output_format", "drm_prime", "-afbc", "rga"]
        if settings.rotation:
            before += ["-noautorotate"]
        after = []
        if settings.transform_required:
            if plan.scale_filter in {"scale_rkrga", "vpp_rkrga"}:
                size = f"w={settings.width}:h={settings.height}:format=nv12"
                if settings.rotation:
                    transpose = {90: "cclock", 180: "reversal", 270: "clock"}[settings.rotation]
                    vf = f"vpp_rkrga={size}:transpose={transpose}"
                else:
                    vf = f"scale_rkrga={size}"
            else:
                vf = software_filter(settings)
            if settings.normalize_sar:
                vf += ",setsar=1"
            after += ["-vf", vf]
        after += bitrate_args(plan)
        after += ["-rc_mode", settings.rate_control.upper()]
        after += frame_rate_args(settings)
        return VideoArguments(tuple(before), tuple(after))

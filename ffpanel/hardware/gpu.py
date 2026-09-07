"""GPU video planners. Device discovery and subprocesses live in detection.py."""

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


class GpuBackend:
    id: str
    suffix: str
    hwaccel: str
    hardware_profile: str
    software_profile: str
    label: str
    next_profile = "cpu_cpu"
    device_paths: tuple[str, ...] = ()

    def profiles(self) -> tuple[HardwareProfile, ...]:
        return (
            HardwareProfile(self.hardware_profile, f"{self.label} 硬件编解码", self.id,
                            "hardware", self.software_profile),
            HardwareProfile(self.software_profile, f"CPU 软解 + {self.label} 编码", self.id,
                            "software", self.next_profile),
        )

    def probe(self, inventory: FFmpegInventory) -> BackendCapabilities:
        codecs = {"h264", "hevc", "vp8", "vp9", "av1", "mpeg2video", "mjpeg"}
        decoder_names = (
            {f"{'mpeg2' if codec == 'mpeg2video' else codec}_{'cuvid' if self.id == 'nvidia' else 'qsv'}" for codec in codecs}
            if self.id != "vaapi" else codecs
        )
        return BackendCapabilities(
            self.id,
            inventory.encoders & {f"h264_{self.suffix}", f"hevc_{self.suffix}"},
            inventory.decoders & decoder_names,
            inventory.filters & {f"scale_{self.hwaccel}", "hwupload", "format", "setsar"},
            {path: inventory.devices.get(path, False) for path in self.device_paths},
            {"compiled": self.hwaccel in inventory.hwaccels},
        )

    def plan_video(self, request: VideoRequest, profile: HardwareProfile,
                   capabilities: BackendCapabilities) -> VideoPlan:
        encoder = f"{request.video_codec}_{self.suffix}"
        if not capabilities.features.get(f"encode_{request.video_codec}", False):
            raise MediaError("hardware_unavailable", capabilities.errors.get(
                f"encode_{request.video_codec}", f"{self.label} 编码器无法初始化"))
        if encoder not in capabilities.encoders:
            raise MediaError("encoder_unavailable", f"所选编码器不可用：{encoder}")
        if not capabilities.device:
            raise MediaError("hardware_unavailable", f"{self.label} 未选择可用设备")
        hardware = profile.decode_mode == "hardware"
        if hardware:
            if request.settings.rotation:
                raise MediaError("hardware_transform_unavailable",
                                 f"{self.label} 旋转需要 CPU 软解和软件滤镜")
            codec = {"h265": "hevc", "avc": "h264"}.get(request.source_codec,
                                                               request.source_codec)
            decoder = codec if self.id == "vaapi" else (
                f"{'mpeg2' if codec == 'mpeg2video' else codec}_{'cuvid' if self.id == 'nvidia' else 'qsv'}")
            if (not capabilities.features.get("decode", False)
                    or decoder not in capabilities.decoders
                    or capabilities.features.get(f"decode_{codec}") is False):
                raise MediaError("hardware_unavailable", f"{self.label} 无法硬件解码 {codec}")
            if request.pixel_format not in {"yuv420p", "nv12", "yuv420p10le", "p010le"}:
                raise MediaError("hardware_unavailable",
                                 f"{self.label} 不支持源像素格式 {request.pixel_format}")
            if not capabilities.features.get("scale", False):
                raise MediaError("hardware_transform_unavailable",
                                 f"{self.label} 硬件缩放不可用")
        return VideoPlan(profile, encoder, request.settings,
                         f"scale_{self.hwaccel}" if hardware else "scale",
                         capabilities.device, "nv12")

    def device_args(self, device: str) -> list[str]:
        if self.id == "nvidia":
            return ["-init_hw_device", f"cuda=gpu:{device}", "-filter_hw_device", "gpu"]
        args = ["-init_hw_device", f"vaapi=va:{device},driver=iHD"]
        if self.id == "qsv":
            args += ["-init_hw_device", "qsv=gpu@va", "-filter_hw_device", "gpu"]
        else:
            args += ["-filter_hw_device", "va"]
        return args

    def build_video_args(self, plan: VideoPlan) -> VideoArguments:
        if plan.device is None:
            raise MediaError("hardware_unavailable", "已保存的视频计划缺少 GPU 设备")
        settings = plan.settings
        hardware = plan.profile.decode_mode == "hardware"
        before = self.device_args(plan.device) if hardware or self.id != "nvidia" else []
        if hardware:
            before += ["-hwaccel", self.hwaccel, "-hwaccel_device",
                       "va" if self.id == "vaapi" else "gpu",
                       "-hwaccel_output_format", self.hwaccel]
        if settings.rotation:
            before += ["-noautorotate", "-display_rotation:v:0", "0"]
        if hardware:
            vf = f"{plan.scale_filter}=w={settings.width}:h={settings.height}:format={plan.pixel_format}"
        else:
            vf = (software_filter(settings) + "," if settings.transform_required else "")
            vf += f"format={plan.pixel_format}"
        if settings.normalize_sar:
            vf += ",setsar=1"
        if not hardware and self.id != "nvidia":
            vf += ",hwupload=extra_hw_frames=64"
        after = ["-vf", vf] + bitrate_args(plan)
        if self.id == "nvidia":
            after += ["-gpu", plan.device, "-rc", settings.rate_control]
        elif self.id == "vaapi":
            after += ["-rc_mode", settings.rate_control.upper()]
        elif settings.rate_control == "vbr":
            # QSV selects CBR when average == maximum; keep maximum at the user's ceiling.
            after[after.index("-b:v") + 1] = f"{max(1, settings.bitrate_kbps * 9 // 10)}k"
        after += frame_rate_args(settings)
        return VideoArguments(tuple(before), tuple(after))


class NvidiaBackend(GpuBackend):
    id = "nvidia"
    suffix = "nvenc"
    hwaccel = "cuda"
    hardware_profile = "nvdec_nvenc"
    software_profile = "cpu_nvenc"
    label = "NVIDIA NVENC"
    device_paths = ("/dev/nvidiactl", "/dev/nvidia-uvm")


class QsvBackend(GpuBackend):
    id = "qsv"
    suffix = "qsv"
    hwaccel = "qsv"
    hardware_profile = "qsv_qsv"
    software_profile = "cpu_qsv"
    label = "Intel QSV"
    next_profile = "vaapi_vaapi"


class VaapiBackend(GpuBackend):
    id = "vaapi"
    suffix = "vaapi"
    hwaccel = "vaapi"
    hardware_profile = "vaapi_vaapi"
    software_profile = "cpu_vaapi"
    label = "Intel VAAPI"

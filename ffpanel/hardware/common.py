"""Reusable video argument helpers, independent of the backend registry."""

from .types import VideoPlan, VideoSettings


def software_filter(settings: VideoSettings) -> str:
    filters = []
    if settings.rotation == 90:
        filters.append("transpose=cclock")
    elif settings.rotation == 180:
        filters.extend(["hflip", "vflip"])
    elif settings.rotation == 270:
        filters.append("transpose=clock")
    filters.append(f"scale={settings.width}:{settings.height}:flags=fast_bilinear")
    filters.append("format=yuv420p")
    return ",".join(filters)


def bitrate_args(plan: VideoPlan) -> list[str]:
    bitrate = f"{plan.settings.bitrate_kbps}k"
    argv = ["-c:v", plan.encoder, "-b:v", bitrate]
    if plan.settings.rate_control == "cbr":
        argv += ["-minrate", bitrate]
    argv += ["-maxrate", bitrate, "-bufsize", f"{plan.settings.bitrate_kbps * 2}k"]
    return argv


def frame_rate_args(settings: VideoSettings) -> list[str]:
    return ["-r", settings.frame_rate] if settings.frame_rate != "source" else []

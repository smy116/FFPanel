"""Strict real-device verification through FFPanel's production video planner."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

from ffpanel.config import Settings
from ffpanel.hardware import registry
from ffpanel.media import build_ffmpeg_argv, decide_parameters, detect_capabilities, probe_media
from ffpanel.schemas import TranscodeParams


def run(argv: list[str]) -> None:
    subprocess.run(argv, check=True, timeout=120, stdout=subprocess.DEVNULL)


async def verify(backend: str, codecs: list[str]) -> None:
    settings = Settings(mock_media=False)
    caps = await detect_capabilities(settings)
    print(json.dumps(caps.hardware_dict(), ensure_ascii=False, indent=2))
    ids = {"intel": {"qsv", "vaapi"}, "rockchip": {"rockchip"}, "cpu": {"cpu"},
           "nvidia": {"nvidia"}, "qsv": {"qsv"}, "vaapi": {"vaapi"}}[backend]
    profiles = [profile for profile in registry.profiles.values() if profile.backend_id in ids]
    with tempfile.TemporaryDirectory(prefix="ffpanel-verify-") as directory:
        root = Path(directory)
        for codec in codecs:
            source = root / f"source-{codec}.mp4"
            run([settings.ffmpeg_path, "-nostdin", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24", "-t", "1",
                 "-c:v", "libx264" if codec == "h264" else "libx265", "-preset", "ultrafast", str(source)])
            for profile in profiles:
                for height in (-1, 360):
                    output = root / f"{profile.id}-{codec}-{height}.mp4"
                    params = TranscodeParams.model_validate({"hardwareMode": profile.id,
                        "autoFallback": False, "videoCodec": codec, "height": height})
                    effective, _ = decide_parameters(await probe_media(settings, source), params, caps)
                    assert effective["hardwareMode"] == profile.id
                    if profile.backend_id != "cpu":
                        assert effective["encoder"] not in {"libx264", "libx265"}, "CPU fallback forbidden"
                    argv = build_ffmpeg_argv(settings, source, output, effective)
                    print(json.dumps({"profile": profile.id, "argv": argv}, ensure_ascii=False))
                    run(argv)
                    actual = await probe_media(settings, output)
                    assert actual["video"]["codec"] == codec, actual
                    assert (actual["video"]["width"], actual["video"]["height"]) == (
                        effective["width"], effective["height"]), actual
                    assert output.stat().st_size > 0
                    run([settings.ffmpeg_path, "-nostdin", "-v", "error", "-i", str(output), "-f", "null", "-"])
                    print(f"PASS {profile.id} {codec} {effective['width']}x{effective['height']}")
    print(f"{backend} strict hardware verification passed (no automatic fallback)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["cpu", "rockchip", "nvidia", "intel", "qsv", "vaapi"], required=True)
    parser.add_argument("--codec", choices=["h264", "hevc", "both"], default="both")
    args = parser.parse_args()
    asyncio.run(verify(args.backend, ["h264", "hevc"] if args.codec == "both" else [args.codec]))

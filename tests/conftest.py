from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ffpanel.config import Settings
from ffpanel.hardware import registry
from ffpanel.hardware.compat import CapabilitySnapshot, legacy_snapshot
from ffpanel.hardware.types import FFmpegInventory


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    media = tmp_path / "media"
    config = tmp_path / "config"
    cache = tmp_path / "cache"
    media.mkdir()
    return Settings(
        config_dir=config,
        cache_dir=cache,
        local_roots=str(media),
        database_url=f"sqlite:///{(config / 'ffpanel.db').as_posix()}",
        mock_media=True,
    )


@pytest.fixture
def gpu_snapshot() -> CapabilitySnapshot:
    inventory = FFmpegInventory(
        frozenset({"libx264", "libx265", "h264_rkmpp", "hevc_rkmpp"} |
                  {f"{codec}_{suffix}" for codec in ("h264", "hevc") for suffix in ("nvenc", "qsv", "vaapi")}),
        frozenset({"h264", "hevc"} | {f"{codec}_{suffix}" for codec in ("h264", "hevc")
                                     for suffix in ("cuvid", "qsv", "rkmpp")}),
        frozenset({"scale_cuda", "scale_qsv", "scale_vaapi", "scale_rkrga", "hwupload", "format", "setsar"}),
        {"/dev/nvidiactl": True, "/dev/mpp_service": True, "/dev/rga": True},
        frozenset({"cuda", "qsv", "vaapi"}),
    )
    backends = registry.probe(inventory)
    for backend_id in ("nvidia", "qsv", "vaapi"):
        backends[backend_id] = replace(backends[backend_id], detected=True,
            device="2" if backend_id == "nvidia" else "/dev/dri/renderD129",
            features={key: True for key in ("compiled", "initialize", "encode_h264", "encode_hevc",
                                            "decode_h264", "decode_hevc", "decode", "scale")})
    return legacy_snapshot("test", True, backends, inventory.devices)


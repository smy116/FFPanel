from __future__ import annotations

from pathlib import Path

import pytest

from ffpanel.schemas import StorageLocation
from ffpanel.storage import ScanRegistry, StorageError, StorageService, companion_selected


@pytest.mark.asyncio
async def test_local_scan_and_companion_policies(settings, tmp_path: Path) -> None:
    root = tmp_path / "media" / "library"
    (root / "season").mkdir(parents=True)
    (root / "season" / "episode.mkv").write_bytes(b"video")
    (root / "season" / "episode.ass").write_text("subtitle", encoding="utf-8")
    (root / "poster.jpg").write_bytes(b"image")
    service = StorageService(settings)
    entries = await service.scan(StorageLocation(kind="local", path=str(root)))
    assert [entry.relative_path for entry in entries] == ["poster.jpg", "season/episode.ass", "season/episode.mkv"]
    assert sum(companion_selected(entry, "subtitles") for entry in entries) == 1
    assert sum(companion_selected(entry, "all_non_video") for entry in entries) == 2


def test_path_traversal_is_rejected(settings, tmp_path: Path) -> None:
    service = StorageService(settings)
    with pytest.raises(StorageError, match="允许"):
        service.validate_local(str(tmp_path / "outside"), allow_missing=True)
    with pytest.raises(StorageError, match="相对路径"):
        service.validate_relative("../secret")


def test_scan_token_is_single_use(settings, tmp_path: Path) -> None:
    registry = ScanRegistry(900)
    source = StorageLocation(kind="local", path=str(tmp_path / "media"))
    record = registry.put(source, "none", [])
    assert registry.consume(record.token, source, "none") == record
    with pytest.raises(StorageError, match="失效"):
        registry.consume(record.token, source, "none")


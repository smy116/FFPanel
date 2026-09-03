from __future__ import annotations

from pathlib import Path

import pytest

from ffpanel.config import Settings


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


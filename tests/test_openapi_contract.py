from __future__ import annotations

import json
from pathlib import Path

from ffpanel.main import create_app


def test_committed_openapi_matches_application() -> None:
    committed = json.loads((Path(__file__).parents[1] / "openapi.json").read_text(encoding="utf-8"))
    assert committed == create_app().openapi(), "运行 scripts/export_openapi.py 并重新生成前端 API 类型"

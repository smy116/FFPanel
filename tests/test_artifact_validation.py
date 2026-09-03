from pathlib import Path

from ffpanel.api import _artifact_valid as api_artifact_valid
from ffpanel.models import TaskFile
from ffpanel.scheduler import Scheduler


def test_artifact_validation_uses_file_size_only(tmp_path: Path) -> None:
    artifact = tmp_path / "movie.part.mp4"
    artifact.write_bytes(b"original")
    item = TaskFile(completed_artifact_path=str(artifact), artifact_size=8)

    assert api_artifact_valid(item)
    assert Scheduler._artifact_valid(item)

    artifact.write_bytes(b"changed!")
    assert api_artifact_valid(item)
    assert Scheduler._artifact_valid(item)

    artifact.write_bytes(b"too-large!")
    assert not api_artifact_valid(item)
    assert not Scheduler._artifact_valid(item)

    item.artifact_size = None
    assert not api_artifact_valid(item)
    assert not Scheduler._artifact_valid(item)


def test_artifact_validation_rejects_missing_file(tmp_path: Path) -> None:
    item = TaskFile(completed_artifact_path=str(tmp_path / "missing.mp4"), artifact_size=8)

    assert not api_artifact_valid(item)
    assert not Scheduler._artifact_valid(item)

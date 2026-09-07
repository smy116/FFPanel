import pytest
from fastapi.testclient import TestClient

from ffpanel.main import create_app
from ffpanel.models import CompanionFile, Task, TaskFile
from ffpanel.scheduler import Scheduler
from ffpanel.schemas import TranscodeParams


@pytest.mark.parametrize("checkpoint", ["temporary", "committed"])
def test_retry_recounts_completed_checkpoints(settings, monkeypatch, checkpoint: str) -> None:
    monkeypatch.setattr(Scheduler, "_next_transcode_id", lambda self: None)
    monkeypatch.setattr(Scheduler, "_next_transfer", lambda self: None)
    app = create_app(settings)
    with TestClient(app) as client:
        destination = settings.allowed_local_roots[0] / "output"
        destination.mkdir()
        artifact = destination / (".part.mp4" if checkpoint == "temporary" else "movie.mp4")
        artifact.write_bytes(b"complete-artifact")
        with app.state.sessions() as session:
            task = Task(
                name="checkpoint", status="interrupted", total_files=2,
                failed_files=1, skipped_files=1, last_error="old failure",
                source_json={"kind": "local", "path": str(settings.allowed_local_roots[0])},
                destination_json={"kind": "local", "path": str(destination)},
                requested_params_json=TranscodeParams().model_dump(mode="json", by_alias=True),
                companion_total=1, companion_completed=0,
            )
            task.files = [
                TaskFile(
                    relative_path="movie.mkv", stage="interrupted",
                    completed_artifact_path=str(artifact), final_output_path="movie.mp4",
                    artifact_size=artifact.stat().st_size, last_error="old failure",
                ),
                TaskFile(relative_path="skipped.mkv", stage="skipped"),
            ]
            task.companions = [
                CompanionFile(relative_path="movie.srt", category="subtitle", stage="completed")
            ]
            session.add(task)
            session.commit()
            task_id = task.id
        response = client.post(f"/api/v1/tasks/{task_id}/retry")
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["status"] == "completed"
        assert value["completedFiles"] == 1
        assert value["failedFiles"] == 0
        assert value["skippedFiles"] == 1
        assert value["companionCompleted"] == 1
        assert value["percent"] == 100
        assert value["finishedAt"] is not None
        assert value["lastError"] is None
        files = client.get(f"/api/v1/tasks/{task_id}/files").json()["items"]
        completed = next(item for item in files if item["stage"] == "completed")
        assert completed["finishedAt"] is not None
        assert (destination / "movie.mp4").read_bytes() == b"complete-artifact"
        snapshot = client.get("/api/v1/snapshot").json()
        assert snapshot["metrics"]["completedVideos"] == 1


@pytest.mark.parametrize("conflict", [False, True])
def test_retry_recounts_pending_and_conflicting_files(settings, monkeypatch, conflict: bool) -> None:
    monkeypatch.setattr(Scheduler, "_next_transcode_id", lambda self: None)
    monkeypatch.setattr(Scheduler, "_next_transfer", lambda self: None)
    app = create_app(settings)
    with TestClient(app) as client:
        destination = settings.allowed_local_roots[0] / "output"
        destination.mkdir()
        if conflict:
            (destination / "retry.mp4").write_bytes(b"existing")
        with app.state.sessions() as session:
            task = Task(
                name="mixed", status="failed", total_files=2, failed_files=2,
                source_json={"kind": "local", "path": str(settings.allowed_local_roots[0])},
                destination_json={"kind": "local", "path": str(destination)},
                requested_params_json=TranscodeParams().model_dump(mode="json", by_alias=True),
            )
            task.files = [
                TaskFile(relative_path="done.mkv", stage="completed"),
                TaskFile(
                    relative_path="retry.mkv", stage="failed", last_error="old failure",
                    final_output_path="retry.mp4", artifact_size=100,
                ),
            ]
            session.add(task)
            session.commit()
            task_id = task.id
        value = client.post(f"/api/v1/tasks/{task_id}/retry").json()
        assert value["completedFiles"] == 1
        assert value["failedFiles"] == int(conflict)
        assert value["status"] == ("partial_failed" if conflict else "queued")
        assert value["percent"] == (100 if conflict else 50)
        assert bool(value["finishedAt"]) == conflict
        assert bool(value["lastError"]) == conflict
        if conflict:
            assert (destination / "retry.mp4").read_bytes() == b"existing"

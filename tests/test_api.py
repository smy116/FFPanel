from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from ffpanel.config import Settings
from ffpanel.db import Base, create_db_engine, create_session_factory
from ffpanel.main import create_app
from ffpanel.models import FileStage, Task, TaskFile, TaskStatus


def request_payload(media: Path, scan_token: str) -> dict:
    return {
        "name": "测试批次",
        "source": {"kind": "local", "path": str(media / "input")},
        "destination": {"kind": "local", "path": str(media / "output")},
        "scanToken": scan_token,
        "companionFilePolicy": "subtitles",
        "params": {
            "hardwareMode": "cpu_cpu", "videoCodec": "h264", "container": "mp4",
            "height": 720, "bitrateKbps": 2000, "smartBitrateCap": True,
            "frameRate": "source", "rateControl": "vbr", "audioStrategy": "copy", "subtitleStrategy": "auto",
        },
    }


def test_create_task_runs_pipeline_and_preserves_companion(settings: Settings, tmp_path: Path) -> None:
    media = tmp_path / "media"
    source = media / "input" / "show"
    destination = media / "output"
    source.mkdir(parents=True)
    destination.mkdir()
    (source / "episode.mkv").write_bytes(b"video-content")
    (source / "episode.srt").write_text("subtitle", encoding="utf-8")
    with TestClient(create_app(settings)) as client:
        scan = client.post("/api/v1/storage/scan", json={
            "source": {"kind": "local", "path": str(media / "input")},
            "companionFilePolicy": "subtitles",
        })
        assert scan.status_code == 200, scan.text
        summary = scan.json()
        assert summary["videoCount"] == 1
        assert summary["companionCount"] == 1
        created = client.post("/api/v1/tasks", json=request_payload(media, summary["scanToken"]))
        assert created.status_code == 201, created.text
        assert created.json()["requestedParams"]["autoFallback"] is True
        task_id = created.json()["id"]
        deadline = time.monotonic() + 4
        task = created.json()
        while time.monotonic() < deadline and task["status"] not in {"completed", "failed", "partial_failed"}:
            time.sleep(0.1)
            task = client.get(f"/api/v1/tasks/{task_id}").json()
        assert task["status"] == "completed", task
        assert (destination / "show" / "episode.mp4").exists()
        assert (destination / "show" / "episode.srt").exists()


def test_same_source_destination_is_rejected(settings: Settings, tmp_path: Path) -> None:
    media = tmp_path / "media"
    folder = media / "same"
    folder.mkdir()
    (folder / "one.mp4").write_bytes(b"video")
    with TestClient(create_app(settings)) as client:
        scan = client.post("/api/v1/storage/scan", json={"source": {"kind": "local", "path": str(folder)}, "companionFilePolicy": "none"}).json()
        payload = request_payload(media, scan["scanToken"])
        payload["source"]["path"] = str(folder)
        payload["destination"]["path"] = str(folder)
        response = client.post("/api/v1/tasks", json=payload)
        assert response.status_code == 409
        assert set(response.json()) == {"code", "message", "details", "requestId"}
        assert response.json()["code"] == "same_source_destination"


def test_basic_auth_protects_ui_and_api(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    settings = Settings(
        config_dir=tmp_path / "config", cache_dir=tmp_path / "cache", local_roots=str(media),
        database_url=f"sqlite:///{(tmp_path / 'config' / 'auth.db').as_posix()}", mock_media=True,
        auth_enabled=True, auth_username="operator", auth_password="secret",
    )
    with TestClient(create_app(settings)) as client:
        unauthorized = client.get("/api/v1/snapshot")
        assert unauthorized.status_code == 401
        assert unauthorized.json()["code"] == "unauthorized"
        assert unauthorized.json()["requestId"]
        assert client.get("/api/v1/snapshot", auth=("operator", "secret")).status_code == 200
        assert client.get("/healthz").status_code == 200


def test_startup_marks_active_work_interrupted(settings: Settings, tmp_path: Path) -> None:
    settings.ensure_directories()
    engine = create_db_engine(settings.db_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    with sessions() as session:
        task = Task(
            name="crashed", status=TaskStatus.RUNNING.value,
            source_json={"kind": "local", "path": str(tmp_path / "media" / "input")},
            destination_json={"kind": "local", "path": str(tmp_path / "media" / "output")},
            requested_params_json={"hardwareMode": "cpu_cpu", "videoCodec": "h264", "container": "mp4", "height": 720, "bitrateKbps": 2000, "smartBitrateCap": True, "frameRate": "source", "rateControl": "vbr", "audioStrategy": "copy", "subtitleStrategy": "auto"},
            total_files=1,
        )
        task.files = [TaskFile(relative_path="movie.mkv", stage=FileStage.TRANSCODING.value)]
        session.add(task); session.commit(); task_id = task.id
    engine.dispose()
    with TestClient(create_app(settings)) as client:
        task = client.get(f"/api/v1/tasks/{task_id}").json()
        assert task["status"] == "interrupted"
        files = client.get(f"/api/v1/tasks/{task_id}/files").json()["items"]
        assert files[0]["stage"] == "interrupted"


def test_retry_commits_valid_local_checkpoint(settings: Settings, tmp_path: Path) -> None:
    media = tmp_path / "media"
    source = media / "input"; destination = media / "output"
    source.mkdir(parents=True); destination.mkdir()
    artifact = tmp_path / "cache" / "tasks" / "task" / "movie.part.mp4"
    artifact.parent.mkdir(parents=True); artifact.write_bytes(b"complete-artifact")
    settings.ensure_directories()
    engine = create_db_engine(settings.db_url); Base.metadata.create_all(engine); sessions = create_session_factory(engine)
    with sessions() as session:
        task = Task(
            name="checkpoint", status=TaskStatus.INTERRUPTED.value,
            source_json={"kind": "local", "path": str(source)}, destination_json={"kind": "local", "path": str(destination)},
            requested_params_json={"hardwareMode": "cpu_cpu", "videoCodec": "h264", "container": "mp4", "height": 720, "bitrateKbps": 2000, "smartBitrateCap": True, "frameRate": "source", "rateControl": "vbr", "audioStrategy": "copy", "subtitleStrategy": "auto"}, total_files=1,
        )
        task.files = [TaskFile(relative_path="movie.mkv", stage=FileStage.INTERRUPTED.value, completed_artifact_path=str(artifact), final_output_path="movie.mp4", artifact_size=artifact.stat().st_size)]
        session.add(task); session.commit(); task_id = task.id
    engine.dispose()
    with TestClient(create_app(settings)) as client:
        response = client.post(f"/api/v1/tasks/{task_id}/retry")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "completed"
        assert (destination / "movie.mp4").read_bytes() == b"complete-artifact"

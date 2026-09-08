import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ffpanel.events import EventBus
from ffpanel.main import create_app
from ffpanel.models import Task, TaskFile
from ffpanel.scheduler import Scheduler
from ffpanel.schemas import TranscodeParams


def test_idle_scheduler_is_healthy(settings) -> None:
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").status_code == 200
        system = client.get("/api/v1/snapshot").json()["system"]
        assert system["schedulerHealthy"] is True
        assert len(system["schedulerWorkers"]) == 3
        assert all(system["schedulerWorkers"].values())


@pytest.mark.parametrize("worker", ["transcode", "transfer", "status"])
def test_worker_failure_is_reported_by_health_and_snapshot(settings, monkeypatch, worker) -> None:
    published = []
    publish = EventBus.publish

    async def capture(self, event_type, payload, **kwargs):
        published.append((event_type, payload))
        return await publish(self, event_type, payload, **kwargs)

    async def fail(self):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(Scheduler, f"_{worker}_loop", fail)
    monkeypatch.setattr(EventBus, "publish", capture)
    with TestClient(create_app(settings)) as client:
        response = client.get("/healthz")
        assert response.status_code == 503
        assert response.json()["status"] == "unhealthy"
        system = client.get("/api/v1/snapshot").json()["system"]
        assert system["schedulerHealthy"] is False
        assert system["schedulerWorkers"][f"ffpanel-{worker}"] is False
        assert any(
            kind == "system.status" and payload.get("schedulerHealthy") is False
            for kind, payload in published
        )


def test_cancelled_worker_is_unhealthy(settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        async def cancel_worker():
            worker = app.state.scheduler._tasks[0]
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

        assert client.portal is not None
        client.portal.call(cancel_worker)
        assert client.get("/healthz").status_code == 503


def test_remote_output_pauses_with_one_queued_artifact(settings, monkeypatch) -> None:
    next_transcode = Scheduler._next_transcode_id
    monkeypatch.setattr(Scheduler, "_next_transcode_id", lambda self: None)
    monkeypatch.setattr(Scheduler, "_next_transfer", lambda self: None)
    app = create_app(settings)
    with TestClient(app):
        with app.state.sessions() as session:
            task = Task(
                name="backpressure",
                status="queued",
                total_files=2,
                source_json={"kind": "local", "path": str(settings.allowed_local_roots[0])},
                destination_json={"kind": "rclone", "remote": "media", "path": "encoded"},
                requested_params_json=TranscodeParams().model_dump(mode="json", by_alias=True),
            )
            pending = TaskFile(relative_path="next.mkv", stage="pending")
            queued = TaskFile(relative_path="ready.mkv", stage="upload_queued")
            task.files = [pending, queued]
            session.add(task)
            session.commit()
            pending_id = pending.id

        assert next_transcode(app.state.scheduler) is None

        with app.state.sessions() as session:
            queued = session.scalar(
                select(TaskFile).where(TaskFile.stage == "upload_queued")
            )
            assert queued is not None
            queued.stage = "completed"
            session.commit()

        assert next_transcode(app.state.scheduler) == pending_id

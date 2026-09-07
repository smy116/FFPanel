from fastapi.testclient import TestClient

from ffpanel.main import create_app
from ffpanel.models import CompanionFile, Task, TaskFile, utcnow
from ffpanel.schemas import TranscodeParams


def test_file_pages_include_all_rows_with_identical_creation_times(settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        with app.state.sessions() as session:
            task = Task(
                name="large task", status="stopped", total_files=501, companion_total=501,
                source_json={"kind": "local", "path": str(settings.allowed_local_roots[0])},
                destination_json={"kind": "local", "path": str(settings.allowed_local_roots[0])},
                requested_params_json=TranscodeParams().model_dump(mode="json", by_alias=True),
            )
            created_at = utcnow()
            task.files = [
                TaskFile(relative_path=f"{index}.mp4", created_at=created_at)
                for index in range(501)
            ]
            task.companions = [
                CompanionFile(relative_path=f"{index}.srt", category="subtitle", created_at=created_at)
                for index in range(501)
            ]
            session.add(task)
            session.commit()
            task_id = task.id
        for resource in ("files", "companions"):
            first = client.get(f"/api/v1/tasks/{task_id}/{resource}?limit=500").json()
            second = client.get(f"/api/v1/tasks/{task_id}/{resource}?limit=500&offset=500").json()
            assert first["total"] == second["total"] == 501
            assert len(first["items"]) == 500
            assert len(second["items"]) == 1
            ids = [item["id"] for item in first["items"] + second["items"]]
            assert len(set(ids)) == 501
            assert ids == sorted(ids)

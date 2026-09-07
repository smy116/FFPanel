from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from alembic import command
from ffpanel.config import get_settings
from ffpanel.db import create_db_engine

PROJECT_ROOT = Path(__file__).parents[1]


def _upgrade_to_head(db_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FFPANEL_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    finally:
        get_settings.cache_clear()


def test_migrations_have_a_single_initial_revision() -> None:
    script = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini")))

    revisions = list(script.walk_revisions())

    assert script.get_heads() == ["0001_initial"]
    assert [revision.revision for revision in revisions] == ["0001_initial"]
    assert revisions[0].down_revision is None


def test_new_database_migration_creates_current_schema(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "new.db"
    _upgrade_to_head(db_path, monkeypatch)

    engine = create_db_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == {
            "alembic_version",
            "companion_files",
            "runtime_capabilities",
            "task_attempts",
            "task_files",
            "tasks",
        }
        task_file_columns = {column["name"] for column in inspector.get_columns("task_files")}
        capability_columns = {
            column["name"] for column in inspector.get_columns("runtime_capabilities")
        }
    finally:
        engine.dispose()

    assert {"artifact_size", "ffmpeg_output"} <= task_file_columns
    assert "artifact_fingerprint" not in task_file_columns
    assert "hardware_json" in capability_columns


def test_initial_migration_downgrades_to_an_empty_schema(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "downgrade.db"
    monkeypatch.setenv("FFPANEL_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    get_settings.cache_clear()
    try:
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        command.upgrade(config, "head")
        command.downgrade(config, "base")
    finally:
        get_settings.cache_clear()

    engine = create_db_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar_one() == 0
    finally:
        engine.dispose()

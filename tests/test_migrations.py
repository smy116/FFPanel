from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from alembic import command
from ffpanel import models  # noqa: F401
from ffpanel.config import get_settings
from ffpanel.db import Base, create_db_engine

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
        assert set(inspector.get_table_names()) == {"alembic_version", *Base.metadata.tables}
        for table_name, table in Base.metadata.tables.items():
            database_columns = {
                column["name"]: column["nullable"]
                for column in inspector.get_columns(table_name)
            }
            model_columns = {column.name: column.nullable for column in table.columns}
            assert database_columns == model_columns
            assert {index["name"] for index in inspector.get_indexes(table_name)} == {
                index.name for index in table.indexes
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
            count = connection.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar_one()
            assert count == 0
    finally:
        engine.dispose()

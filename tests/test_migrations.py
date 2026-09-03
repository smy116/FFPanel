from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command
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


def test_new_database_migration_does_not_create_artifact_fingerprint(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "new.db"
    _upgrade_to_head(db_path, monkeypatch)

    engine = create_db_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("task_files")}
    finally:
        engine.dispose()

    assert "artifact_size" in columns
    assert "artifact_fingerprint" not in columns


def test_migration_removes_legacy_artifact_fingerprint(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "legacy.db"
    engine = create_db_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE task_files ADD COLUMN artifact_fingerprint VARCHAR(200)"))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0002_add_ffmpeg_output')"))
    engine.dispose()

    _upgrade_to_head(db_path, monkeypatch)

    engine = create_db_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("task_files")}
    finally:
        engine.dispose()

    assert "artifact_size" in columns
    assert "artifact_fingerprint" not in columns

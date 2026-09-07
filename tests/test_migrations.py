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


def test_hardware_migration_backfills_old_snapshots(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "hardware.db"
    monkeypatch.setenv("FFPANEL_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    get_settings.cache_clear()
    try:
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        command.upgrade(config, "0003_remove_artifact_fingerprint")
        engine = create_db_engine(f"sqlite:///{db_path.as_posix()}")
        with engine.begin() as connection:
            # Initial migration uses current metadata; remove the new column to model an old DB.
            connection.execute(text("ALTER TABLE runtime_capabilities DROP COLUMN hardware_json"))
            connection.execute(text("INSERT INTO runtime_capabilities (id, ffprobe_available, rclone_available, mpp_available, rga_available, encoders_json, decoders_json, filters_json, devices_json, created_at) VALUES ('old', 1, 0, 1, 1, '[]', '[]', '[]', '{}', CURRENT_TIMESTAMP)"))
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT hardware_json FROM runtime_capabilities WHERE id = 'old'")).scalar_one() == "{}"
        command.downgrade(config, "0003_remove_artifact_fingerprint")
        assert "hardware_json" not in {column["name"] for column in inspect(engine).get_columns("runtime_capabilities")}
        engine.dispose()
    finally:
        get_settings.cache_clear()

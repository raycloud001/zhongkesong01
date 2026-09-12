import os
import sqlite3
import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _upgrade(database_url: str, *, explicit_url: str | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "alembic", "upgrade", "head"]
    if explicit_url is not None:
        command[3:3] = ["-x", f"database_url={explicit_url}"]
    return subprocess.run(
        command,
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )


def _has_migration_table(path: Path) -> bool:
    if not path.exists():
        return False
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
    return row is not None


def test_alembic_uses_database_url_from_environment(tmp_path: Path):
    database = tmp_path / "from-environment.db"

    result = _upgrade(_sqlite_url(database))

    assert result.returncode == 0, result.stderr
    assert _has_migration_table(database)


def test_explicit_alembic_database_url_overrides_environment(tmp_path: Path):
    environment_database = tmp_path / "environment.db"
    explicit_database = tmp_path / "explicit.db"

    result = _upgrade(_sqlite_url(environment_database), explicit_url=_sqlite_url(explicit_database))

    assert result.returncode == 0, result.stderr
    assert _has_migration_table(explicit_database)
    assert not _has_migration_table(environment_database)

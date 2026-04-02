"""Bootstrap for live PostgreSQL integration tests."""

from __future__ import annotations

import os
import subprocess  # noqa: S404
import sys
import time
from pathlib import Path

import psycopg2
import pytest
from pydantic import SecretStr

from config import DatabaseConfig, load_config

ROOT = Path(__file__).resolve().parents[2]
LIVE_DB_HOST = "localhost"
LIVE_DB_PORT = 5434
LIVE_DB_USER = "bot"
LIVE_DB_NAME = "kubachi_db"


def _run_command(args: list[str], *, env: dict[str, str] | None = None) -> None:
    """Run a command in the repository root."""
    subprocess.run(  # noqa: S603
        args,
        cwd=ROOT,
        env=env,
        check=True,
    )


def _wait_for_database(timeout_seconds: int = 120) -> None:
    """Wait until the live Postgres container is ready for connections."""
    started_at = time.monotonic()
    password = load_config().database.password.get_secret_value()
    while True:
        try:
            with psycopg2.connect(
                host=LIVE_DB_HOST,
                port=LIVE_DB_PORT,
                user=LIVE_DB_USER,
                password=password,
                dbname=LIVE_DB_NAME,
            ):
                return
        except psycopg2.OperationalError as exc:
            if time.monotonic() - started_at >= timeout_seconds:
                raise TimeoutError(
                    "Timed out while waiting for the live PostgreSQL instance"
                ) from exc
            time.sleep(2)


def _run_alembic_upgrade() -> None:
    """Apply Alembic migrations to the live database."""
    config = load_config()
    env = os.environ.copy()
    env.update(
        {
            "DB_HOST": LIVE_DB_HOST,
            "DB_PORT": str(LIVE_DB_PORT),
            "DB_USER": config.database.user,
            "DB_PASSWORD": config.database.password.get_secret_value(),
            "DB_NAME": LIVE_DB_NAME,
        }
    )
    _run_command(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        env=env,
    )


@pytest.fixture(scope="session", autouse=True)
def live_database_config() -> DatabaseConfig:
    """Prepare the live Docker Postgres instance and expose it through env vars."""
    _run_command(["docker", "compose", "up", "-d", "db"])
    _wait_for_database()
    _run_alembic_upgrade()

    config = load_config()
    live_config = DatabaseConfig(
        host=LIVE_DB_HOST,
        port=LIVE_DB_PORT,
        user=config.database.user,
        password=SecretStr(config.database.password.get_secret_value()),
        database=LIVE_DB_NAME,
    )
    overridden_keys = ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")
    original_env = {key: os.environ.get(key) for key in overridden_keys}
    os.environ.update(
        {
            "DB_HOST": live_config.host,
            "DB_PORT": str(live_config.port),
            "DB_USER": live_config.user,
            "DB_PASSWORD": live_config.password.get_secret_value(),
            "DB_NAME": live_config.database,
        }
    )
    try:
        yield live_config
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

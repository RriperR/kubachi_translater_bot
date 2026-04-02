"""Pytest helpers for integration-test selection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT_DIR = Path(__file__).resolve().parents[1]
_SRC_DIR = _ROOT_DIR / "src"

if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the flag used to opt into live integration tests."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run tests under tests/integration against live PostgreSQL and pgvector.",
    )


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    """Skip integration tests unless the dedicated flag is enabled."""
    if config.getoption("--integration"):
        return False
    normalized_path = collection_path.as_posix()
    return "/tests/integration/" in normalized_path or normalized_path.endswith(
        "/tests/integration"
    )

"""Общий bootstrap для интеграционных тестов."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _skip_unless_enabled() -> None:
    """Пропустить интеграционные тесты без явного флага."""
    if os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to run integration tests.")

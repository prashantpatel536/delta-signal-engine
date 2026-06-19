"""Shared test fixtures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.database import init_db


def utc_now_iso(offset_seconds: float = 0) -> str:
    """ISO timestamp for tests; offset_seconds makes older signals for ordering."""
    return (datetime.now(timezone.utc) - timedelta(seconds=offset_seconds)).isoformat()


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_signals.db"
    monkeypatch.setattr(settings, "database_path", db_path)
    init_db()
    return db_path

"""Shared pytest fixtures.

Sets up an isolated SQLite DB and Fernet key per test session so tests never
touch the real data.db or .secret.key.
"""
import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

# Point env vars at a throwaway dir BEFORE importing the app.
_TMP = Path(tempfile.mkdtemp(prefix="api-dashboard-test-"))
os.environ["DASHBOARD_DB_PATH"] = str(_TMP / "test.db")
os.environ["DASHBOARD_SECRET_KEY"] = Fernet.generate_key().decode()
os.environ.pop("GITHUB_CLIENT_ID", None)  # ensure auth middleware is disabled

# Make backend/ importable as a top-level package from tests/.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def app():
    import main
    return main.app


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_db():
    """Wipe all tables between tests so each runs against a fresh DB."""
    import database
    import models  # noqa: F401  — ensures tables are registered
    from sqlalchemy import text
    yield
    with database.engine.begin() as conn:
        for tbl in reversed(database.Base.metadata.sorted_tables):
            conn.execute(text(f"DELETE FROM {tbl.name}"))

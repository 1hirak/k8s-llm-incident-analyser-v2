import os
import tempfile

# Point the service at a throwaway database before app modules are imported.
_TMP_DIR = tempfile.mkdtemp(prefix="reports-svc-test-")
os.environ["DATABASE_PATH"] = os.path.join(_TMP_DIR, "test.db")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def clean_tables():
    """Isolate each test by emptying both tables."""
    from app.main import db

    yield
    with db._lock:
        db._conn.execute("DELETE FROM analysis_jobs")
        db._conn.execute("DELETE FROM incidents")
        db._conn.commit()

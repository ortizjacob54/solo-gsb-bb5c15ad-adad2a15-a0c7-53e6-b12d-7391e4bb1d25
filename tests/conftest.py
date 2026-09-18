import os
import tempfile

import pytest

# Point the app at an isolated DB before any app module is imported.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["LUX_DB_PATH"] = _tmp.name
os.environ["LUX_SEED_SAMPLE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import connect  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db():
    """Wipe all rows before each test so cases/exhibit IDs stay reusable."""
    conn = connect()
    try:
        conn.execute("DELETE FROM lighting_intervals")
        conn.execute("DELETE FROM exhibits")
        conn.execute("DELETE FROM showcases")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def showcase(client, clean_db):
    resp = client.post(
        "/api/showcases",
        json={"id": "case-1", "name": "测试展柜"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def make_exhibit(client, *, eid="ex-1", limit=None,
                 sensitivity="high_sensitivity", showcase_id="case-1"):
    body = {
        "id": eid,
        "showcase_id": showcase_id,
        "name": "绢本扇面",
        "sensitivity": sensitivity,
    }
    if limit is not None:
        body["annual_limit_lux_hour"] = limit
    resp = client.post("/api/exhibits", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()

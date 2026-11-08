import json
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["STORAGE_DIR"] = f"{_tmp}/storage"
os.environ["DEMO_SEED"] = "true"
os.environ["ICEYE_ENABLED"] = "true"
os.environ["TASKING_MONTHLY_BUDGET_EUR"] = "100000"

import pytest  # noqa: E402
from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(client, email, pw):
    r = client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return login(client, "admin@example.com", "change-me-admin")


@pytest.fixture(scope="session")
def analyst(client):
    return login(client, "analyst@example.com", "demo-analyst")


@pytest.fixture(scope="session")
def buyer(client):
    return login(client, "buyer@example.com", "demo-buyer")


@pytest.fixture(scope="session")
def field(client):
    return login(client, "field@example.com", "demo-field")


def square(lon, lat, size=0.01, scenario=None, **props):
    ring = [[lon, lat], [lon + size, lat], [lon + size, lat + size], [lon, lat + size], [lon, lat]]
    p = {"id": props.pop("id", f"P-{lon}-{lat}")}
    if scenario:
        p["scenario"] = scenario
    p.update(props)
    return {"type": "Feature", "properties": p, "geometry": {"type": "Polygon", "coordinates": [ring]}}


def fc(*feats):
    return json.dumps({"type": "FeatureCollection", "features": list(feats)}).encode()

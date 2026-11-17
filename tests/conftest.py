import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.main import create_app  # noqa: E402

SAMPLE_DIR = ROOT / "sample_data"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture()
def settings(tmp_path):
    return config.Settings(
        db_path=str(tmp_path / "ledgerbank.sqlite"),
        sample_dir=str(SAMPLE_DIR),
    )


@pytest.fixture()
def client(settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def demo(client):
    response = client.post("/api/demo/run")
    assert response.status_code == 200, response.text
    return response.json()


def read_sample(name: str) -> bytes:
    return (SAMPLE_DIR / name).read_bytes()


def read_fixture(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()

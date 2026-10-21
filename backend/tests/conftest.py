"""Test setup: offline demo prices, no news, no LLM, and a fresh database per test run."""
import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
# Tests use a throwaway SQLite file. To run them on Postgres instead, set TEST_DATABASE_URL
# to an EMPTY database, e.g.  TEST_DATABASE_URL=postgresql://postgres@localhost:5432/copilot_test
os.environ.update({
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.db",
    "PRICE_SOURCE": "demo",
    "NEWS_SOURCE": "off",
    "LLM_PROVIDER": "offline",
    "ENABLE_SCHEDULER": "false",
    "ADMIN_EMAILS": "admin@example.com",
    "TELEGRAM_BOT_TOKEN": "",
    "JWT_SECRET": "test-secret-that-is-long-enough-for-hs256",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


_counter = {"n": 0}


@pytest.fixture
def make_user(client):
    """Create a new user and return (headers, user_json)."""

    def _make(email: str | None = None):
        _counter["n"] += 1
        email = email or f"user{_counter['n']}@example.com"
        r = client.post("/api/auth/signup", json={"email": email, "password": "password123", "name": "Test"})
        assert r.status_code == 201, r.text
        data = r.json()
        return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]

    return _make


@pytest.fixture
def user_with_portfolio(client, make_user):
    headers, user = make_user()
    with open(SAMPLE_DIR / "zerodha_kite_holdings.csv", "rb") as f:
        r = client.post("/api/portfolio/upload", headers=headers,
                        files={"file": ("holdings.csv", f, "text/csv")})
    assert r.status_code == 200, r.text
    return headers, user

"""
Test configuration.

Uses mongomock (in-memory MongoDB substitute) so tests run without a
live MongoDB deployment.  The mock client is injected into
``util.databaseManager`` *before* ``app`` is imported, so the Flask app
uses the mock for all collection access.
"""
import os

# Set test env vars BEFORE any project imports so ``config.from_env()``
# picks them up.
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-production-32bytes!")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")  # unused in tests
os.environ.setdefault("MONGO_DB", "testTruePriceDb")
os.environ.setdefault("PLATFORM", "ebay")

import mongomock
import pytest

from util.databaseManager import init_db, get_db

# Initialise the DB with a mongomock client BEFORE importing the app.
# ``init_db`` is idempotent — the call inside app.py will be a no-op.
_mock_client = mongomock.MongoClient()
init_db(client=_mock_client, db_name="testTruePriceDb")

from app import app  # noqa: E402


@pytest.fixture()
def myApp():
    """Flask test client with a clean database for each test."""
    db = get_db()
    for col_name in db.list_collection_names():
        db[col_name].delete_many({})
    with app.test_client() as client:
        yield client


@pytest.fixture()
def registered_client(myApp):
    """Register a client and return (client_id, access_token, refresh_token)."""
    resp = myApp.post("/api/registerClient")
    assert resp.status_code == 200
    data = resp.get_json()
    return data["clientId"], data["accessToken"], data["refreshToken"]


@pytest.fixture()
def auth_headers():
    """Return a callable that builds Authorization headers from a token."""
    def _make(token):
        return {"Authorization": f"Bearer {token}"}
    return _make

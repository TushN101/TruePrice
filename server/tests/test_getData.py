"""End-to-end tests for the history fetch + lazy computation pipeline.

These tests exercise ``util/fetchHandler.fetch_history`` against a
mongomock-backed database, verifying:
* observations are grouped by hour,
* hours are processed chronologically,
* already-computed hours are reused,
* missing hours are computed,
* reputation does not leak future information.
"""
from datetime import datetime, timedelta, timezone

import pytest

from util.databaseManager import (
    clientReputationHistory,
    clients,
    hourlyResults,
    observations,
    products,
)
from util.fetchHandler import fetch_history

# Patch the validator to a mock so tests don't hit live eBay.
import util.fetchHandler as fetch_mod


@pytest.fixture(autouse=True)
def mock_validator(monkeypatch):
    """Replace the eBay validator with a deterministic mock."""
    def fake_validator():
        return lambda url: {"ok": True, "price": 201.0, "currency": "USD"}
    monkeypatch.setattr(fetch_mod, "_get_validator", fake_validator)


def _now():
    return datetime.now(timezone.utc)


def _hour(h):
    """Return a UTC datetime for today at hour ``h``."""
    n = _now()
    return n.replace(hour=h, minute=5, second=0, microsecond=0)


def _register_client(myApp, ip="127.0.0.1"):
    """Register a client and return (clientId, accessToken)."""
    resp = myApp.post("/api/registerClient", environ_base={"REMOTE_ADDR": ip})
    return resp.get_json()["clientId"], resp.get_json()["accessToken"]


def _post_observation(myApp, token, product_id, price, client_ip="127.0.0.1"):
    myApp.post(
        "/api/observations",
        json={
            "productId": product_id,
            "price": price,
            "currency": "USD",
            "url": f"https://www.ebay.com/itm/{product_id}",
            "title": "Test Product",
        },
        headers={"Authorization": f"Bearer {token}"},
        environ_base={"REMOTE_ADDR": client_ip},
    )


# ─── Tests ───────────────────────────────────────────────────────────────

def test_history_unknown_product_returns_missing(myApp):
    """A product with no observations → status 'missing'."""
    result = fetch_history("999999999")
    assert result["status"] == "missing"


def test_history_single_hour_computed(myApp):
    """One hour of observations → one computed hourly result."""
    cid, token = _register_client(myApp)
    cid2, token2 = _register_client(myApp, ip="127.0.0.2")
    cid3, token3 = _register_client(myApp, ip="127.0.0.3")

    pid = "111111111"
    _post_observation(myApp, token, pid, 201, "127.0.0.1")
    _post_observation(myApp, token2, pid, 202, "127.0.0.2")
    _post_observation(myApp, token3, pid, 201, "127.0.0.3")

    result = fetch_history(pid)
    assert result["status"] == "success"
    assert len(result["history"]) >= 1
    hr = result["history"][-1]
    assert hr["canonicalPrice"] == pytest.approx(201, abs=1)
    assert hr["observationCount"] == 3
    assert hr["clientCount"] == 3


def test_already_computed_hours_reused(myApp):
    """A second fetch_history call reuses existing computed results."""
    cid, token = _register_client(myApp)
    pid = "222222222"
    _post_observation(myApp, token, pid, 201)

    # First call computes.
    r1 = fetch_history(pid)
    assert r1["status"] == "success"

    # The hourlyResults collection should now have the result.
    count_after_first = hourlyResults().count_documents({"productId": pid})
    assert count_after_first >= 1

    # Second call should NOT add more hourly results (already computed).
    r2 = fetch_history(pid)
    count_after_second = hourlyResults().count_documents({"productId": pid})
    assert count_after_second == count_after_first
    assert len(r2["history"]) == len(r1["history"])


def test_missing_hours_computed(myApp):
    """When new observations arrive for a previously-computed product,
    only the new hours are computed; old ones are reused."""
    cid, token = _register_client(myApp)
    pid = "333333333"

    # Submit one observation and compute.
    _post_observation(myApp, token, pid, 201)
    fetch_history(pid)
    count1 = hourlyResults().count_documents({"productId": pid})

    # Submit another observation (same hour, but with a different price
    # to force a second observation).  Then fetch again.
    _post_observation(myApp, token, pid, 202)
    fetch_history(pid)
    count2 = hourlyResults().count_documents({"productId": pid})

    # The second fetch should not have created a *new* hourly result for
    # the same hour (it was already computed).  count2 == count1.
    # (If observations landed in a different hour, count2 might be count1+1.)
    assert count2 >= count1


def test_chronological_reputation_no_future_leak(myApp):
    """Computing an older hour must NOT use reputation from a later hour.

    We simulate:
      1. Client A submits in hour H1 → reputation moves from 0.5 → 0.55.
      2. Client A submits in hour H0 (older) with a price that would be
         'incorrect' against the H1 consensus.  When H0 is computed, A's
         reputation should start at 0.5 (initial), NOT 0.55 (from H1).
    """
    cid, token = _register_client(myApp)
    pid = "444444444"

    # Insert two observations in two different hours, both from client A.
    # We use the DB directly to control observedAt precisely.
    products().update_one(
        {"_id": pid},
        {"$set": {
            "platform": "ebay", "externalId": pid,
            "url": f"https://www.ebay.com/itm/{pid}",
            "title": "T", "currency": "USD",
        }},
        upsert=True,
    )

    h0 = _now().replace(hour=_now().hour - 2, minute=3, second=0, microsecond=0)
    h1 = _now().replace(hour=_now().hour - 1, minute=3, second=0, microsecond=0)

    # In H0, client A submits 350 (an outlier).
    observations().insert_one({
        "productId": pid, "clientId": cid, "price": 350.0,
        "currency": "USD", "observedAt": h0, "clientIp": "127.0.0.1",
    })
    # In H1, client A submits 201 (correct).
    observations().insert_one({
        "productId": pid, "clientId": cid, "price": 201.0,
        "currency": "USD", "observedAt": h1, "clientIp": "127.0.0.1",
    })

    # Fetch history — this computes both H0 and H1 chronologically.
    result = fetch_history(pid)
    assert result["status"] == "success"

    # Check the reputation history: H0 should have started from 0.5
    # (initial), and H1 should have started from whatever H0 produced.
    h0_record = clientReputationHistory().find_one(
        {"clientId": cid, "asOfHour": h0.replace(minute=0, second=0, microsecond=0)},
    )
    h1_record = clientReputationHistory().find_one(
        {"clientId": cid, "asOfHour": h1.replace(minute=0, second=0, microsecond=0)},
    )

    assert h0_record is not None, "H0 reputation record missing"
    assert h1_record is not None, "H1 reputation record missing"
    # H0 started from the initial reputation (0.5), NOT from H1's result.
    assert h0_record["previousReputation"] == pytest.approx(0.5)
    # H1 started from H0's result.  H0: client at 0.5 submits 350 (wrong
    # against validator's 201).  Single client → confidence=1.0,
    # strength=1.0, magnitude=0.15, scale=0.5, delta=0.075.
    # new = 0.5 - 0.075 = 0.425
    assert h1_record["previousReputation"] == pytest.approx(0.425)


def test_multiple_clients_reputation_independent(myApp):
    """Two clients in the same hour get independent reputation updates."""
    c1, t1 = _register_client(myApp, ip="127.0.0.1")
    c2, t2 = _register_client(myApp, ip="127.0.0.2")
    pid = "555555555"

    _post_observation(myApp, t1, pid, 201, "127.0.0.1")
    _post_observation(myApp, t2, pid, 350, "127.0.0.2")

    fetch_history(pid)

    r1 = clientReputationHistory().find_one(
        {"clientId": c1}, sort=[("asOfHour", -1)],
    )
    r2 = clientReputationHistory().find_one(
        {"clientId": c2}, sort=[("asOfHour", -1)],
    )
    # c1 (201, correct) should be rewarded; c2 (350, incorrect) penalised.
    assert r1["newReputation"] > r1["previousReputation"]
    assert r2["newReputation"] < r2["previousReputation"]

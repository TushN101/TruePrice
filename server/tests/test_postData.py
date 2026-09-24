"""Tests for the observation ingestion endpoint."""


def _register(myApp):
    resp = myApp.post("/api/registerClient")
    return resp.get_json()["accessToken"]


def test_post_observation_success(myApp):
    """Valid token + valid payload → observation stored."""
    token = _register(myApp)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "productId": "123456789",
        "price": 201.50,
        "currency": "USD",
        "url": "https://www.ebay.com/itm/123456789",
        "title": "Test Product",
    }
    resp = myApp.post("/api/observations", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "refreshToken" in data


def test_post_observation_missing_fields(myApp):
    """Missing required fields → 400."""
    token = _register(myApp)
    headers = {"Authorization": f"Bearer {token}"}
    resp = myApp.post(
        "/api/observations",
        json={"productId": "123456789"},  # missing price
        headers=headers,
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["status"] == "error"
    assert "Missing required fields" in data["message"]


def test_post_observation_non_numeric_price(myApp):
    """Non-numeric price → 400."""
    token = _register(myApp)
    headers = {"Authorization": f"Bearer {token}"}
    resp = myApp.post(
        "/api/observations",
        json={"productId": "123456789", "price": "not-a-number"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "numeric" in resp.get_json()["message"]


def test_post_observation_string_price_coerced(myApp):
    """A numeric string price is accepted (coerced to float)."""
    token = _register(myApp)
    headers = {"Authorization": f"Bearer {token}"}
    resp = myApp.post(
        "/api/observations",
        json={"productId": "123456789", "price": "201"},
        headers=headers,
    )
    assert resp.status_code == 200


def test_duplicate_observation_accepted(myApp):
    """Repeated observations from the same client are all stored (dedup
    happens at computation time, not ingestion time)."""
    token = _register(myApp)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"productId": "123456789", "price": 201}

    r1 = myApp.post("/api/observations", json=payload, headers=headers)
    r2 = myApp.post("/api/observations", json=payload, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200

    # Verify two observations were stored.
    from util.databaseManager import observations
    count = observations().count_documents({"productId": "123456789"})
    assert count == 2

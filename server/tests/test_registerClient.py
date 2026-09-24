"""Tests for client registration and authentication."""
import time


def test_valid_user_creation(myApp):
    """Registration with a valid IP succeeds and returns tokens."""
    response = myApp.post(
        "/api/registerClient",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert data["message"] == "Client registered successfully"
    assert "clientId" in data
    assert "accessToken" in data
    assert "refreshToken" in data
    # access_token cookie should also be set
    assert "access_token" in response.headers.get("Set-Cookie", "")


def test_invalid_user_creation(myApp):
    """Registration with an invalid IP returns 400."""
    response = myApp.post(
        "/api/registerClient",
        environ_base={"REMOTE_ADDR": "999.999.999.999"},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["status"] == "error"
    assert "Invalid IP address" in data["message"]


def test_valid_authentication(myApp):
    """A valid access token allows access to a protected route."""
    reg = myApp.post("/api/registerClient")
    token = reg.get_json()["accessToken"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = myApp.post(
        "/api/observations",
        json={"productId": "123456789", "price": 201},
        headers=headers,
    )
    assert resp.status_code == 200


def test_invalid_token_rejected(myApp):
    """A malformed token is rejected by protected routes."""
    headers = {"Authorization": "Bearer definitely-not-a-token"}
    resp = myApp.post(
        "/api/observations",
        json={"productId": "123456789", "price": 201},
        headers=headers,
    )
    assert resp.status_code in (401, 422)


def test_missing_token_rejected(myApp):
    """No token at all → 401."""
    resp = myApp.post(
        "/api/observations",
        json={"productId": "123456789", "price": 201},
    )
    assert resp.status_code == 401


def test_refresh_flow(myApp):
    """A refresh token can be exchanged for a new access+refresh pair."""
    reg = myApp.post("/api/registerClient")
    reg_data = reg.get_json()
    refresh_token = reg_data["refreshToken"]

    resp = myApp.post(
        "/api/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "accessToken" in data
    assert "refreshToken" in data
    # The new access token should work on a protected route.
    resp2 = myApp.post(
        "/api/observations",
        json={"productId": "123456789", "price": 201},
        headers={"Authorization": f"Bearer {data['accessToken']}"},
    )
    assert resp2.status_code == 200


def test_refresh_with_access_token_fails(myApp):
    """An access token should NOT work on the /api/refresh endpoint."""
    reg = myApp.post("/api/registerClient")
    access_token = reg.get_json()["accessToken"]

    resp = myApp.post(
        "/api/refresh",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code in (401, 422)

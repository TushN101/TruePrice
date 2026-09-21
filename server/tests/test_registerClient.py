"""
Tests registration
"""

def test_valid_user_creation(myApp):
    response = myApp.post(
        "/api/registerClient",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert data["message"] == "Client registered successfully"
    assert "access_token" in data
    assert "refresh_token" in data  # New check for refresh token
    # access_token should also be set as a cookie
    assert "access_token" in response.headers.get("Set-Cookie", "")

def test_invvalid_user_creation(myApp):
    response = myApp.post(
        "/api/registerClient",
        environ_base={"REMOTE_ADDR": "999.999.999.999"},
    )

    assert response.status_code == 400
    data = response.get_json()
    assert data["status"] == "error"
    assert data["message"] == "Invalid IP address. Rejecting registration attempt."

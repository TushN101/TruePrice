import pytest

def test_postData_success(myApp):
    """
    1. Check if the valid token + valid details works
    """
    register_response = myApp.post('/api/registerClient')
    assert register_response.status_code == 200
    token = register_response.get_json().get('access_token')
    assert token is not None
    headers = {
        'Authorization': f'Bearer {token}'
    }
    payload = {
        "itemKey": "laptop",
        "itemValue": 1200
    }
    response = myApp.post('/api/postData',
                          json=payload,
                          headers=headers)

    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert data['message'] == 'Frame ingested successfully'
    assert "refresh_token" in data  # New check for refresh token

def test_postData_invalid_details(myApp):
    """
    2. Check if valid token + invalid or badly formatted details returns error
    """
    # Get a valid token from the registerClient
    register_response = myApp.post('/api/registerClient')
    token = register_response.get_json().get('access_token')

    headers = {
        'Authorization': f'Bearer {token}'
    }

    # Missing 'itemValue'
    payload = {
        "itemKey": "laptop"
    }

    response = myApp.post('/api/postData',
                          json=payload,
                          headers=headers)

    assert response.status_code == 400
    data = response.get_json()
    assert data['status'] == 'error'
    assert "Missing paramters" in data['message']
    assert "refresh_token" in data  # Refresh token should be present even on error as per app.py

def test_postData_invalid_token(myApp):
    """
    3. Check if invalid token gets rejected or no
    """
    payload = {
        "itemKey": "laptop",
        "itemValue": 1200
    }

    # Case 1: No token
    response = myApp.post('/api/postData',
                          json=payload)
    assert response.status_code == 401

    # Case 2: Invalid/Malformed token
    headers = {
        'Authorization': 'Bearer definitely-not-a-token'
    }
    response = myApp.post('/api/postData',
                          json=payload,
                          headers=headers)
    # Flask-JWT-Extended usually returns 422 for malformed tokens
    assert response.status_code in [401, 422]

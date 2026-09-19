
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
    assert response.get_json()['status'] == 'success'
    assert response.get_json()['message'] == 'Frame ingested successfully'

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
    assert response.get_json()['status'] == 'error'
    assert "Missing paramters" in response.get_json()['message']

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

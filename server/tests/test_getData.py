import pytest

def test_getData_no_token(myApp):
    """
    Test without token (should return 401)
    """
    payload = {"itemKey": "laptop"}
    response = myApp.post('/api/getData', json=payload)
    assert response.status_code == 401

def test_getData_missing_key(myApp):
    """
    Test with valid token but missing key in the post data (should return 400)
    """
    register_response = myApp.post('/api/registerClient')
    token = register_response.get_json().get('access_token')
    headers = {'Authorization': f'Bearer {token}'}

    # Missing itemKey
    payload = {}
    response = myApp.post('/api/getData', json=payload, headers=headers)

    assert response.status_code == 400
    data = response.get_json()
    assert data['status'] == 'error'
    assert "Missing itemKey paramter" in data['message']
    assert "refresh_token" in data  # New check for refresh token

def test_getData_non_existent_key(myApp):
    """
    Test with valid token on a non-existent key (should return 204)
    """
    register_response = myApp.post('/api/registerClient')
    token = register_response.get_json().get('access_token')
    headers = {'Authorization': f'Bearer {token}'}

    payload = {"itemKey": "non_existent_item_12345"}
    response = myApp.post('/api/getData', json=payload, headers=headers)

    # According to app.py, response["status"] == "missing" returns 204
    # Note: Flask's jsonify on 204 won't return a body to check refresh_token
    assert response.status_code == 204

def test_getData_existing_key(myApp):
    """
    Test with valid token and an existing key (should return 200 and data)
    """
    # 1. Register and get token
    register_response = myApp.post('/api/registerClient')
    token = register_response.get_json().get('access_token')
    headers = {'Authorization': f'Bearer {token}'}

    # 2. Post some data first to ensure it exists
    item_key = "test_item"
    post_payload = {
        "itemKey": item_key,
        "itemValue": 500
    }
    myApp.post('/api/postData', json=post_payload, headers=headers)

    # 3. Fetch the data
    get_payload = {"itemKey": item_key}
    response = myApp.post('/api/getData', json=get_payload, headers=headers)

    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'sucess'
    assert isinstance(data['message'], list)
    assert len(data['message']) > 0
    assert data['message'][0]['itemValue'] == 500
    assert "refresh_token" in data  # New check for refresh token

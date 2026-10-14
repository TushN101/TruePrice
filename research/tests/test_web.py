"""Tests for Flask web application endpoints and UI workflows."""
import pytest
from web.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_index_redirects_to_configure(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/configure" in resp.headers["Location"]


def test_configure_page_renders(client):
    resp = client.get("/configure")
    assert resp.status_code == 200
    assert b"Crowd-Consensus Simulation Setup" in resp.data
    assert b"Start with Defaults" in resp.data
    assert b"imposter_count" in resp.data


def test_simulation_api_lifecycle(client):
    # 1. Start simulation
    create_payload = {
        "seed": 42,
        "total_users": 50,
        "imposter_count": 5,
        "sleeper_cell_count": 5,
        "sleeper_activation_day": 2,
        "seed_history_days": 1,
        "simulation_days": 2,
        "consensus_threshold": 0.8,
    }
    resp = client.post("/api/simulations", json=create_payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "run_id" in data
    run_id = data["run_id"]

    # 2. Live page renders
    live_resp = client.get(f"/live/{run_id}")
    assert live_resp.status_code == 200
    assert b"Live Simulation Dashboard" in live_resp.data

    # 3. Tick API advances simulation
    tick_resp = client.get(f"/api/simulations/{run_id}/tick?batch=5")
    assert tick_resp.status_code == 200
    tick_data = tick_resp.get_json()
    assert tick_data["current_tick"] == 5
    assert len(tick_data["ticks"]) == 5
    assert "actual_price" in tick_data["latest"]
    assert "top_20_users" in tick_data["latest"]
    assert len(tick_data["latest"]["top_20_users"]) <= 20

    # 4. Fast forward
    ff_resp = client.post(f"/api/simulations/{run_id}/fast_forward")
    assert ff_resp.status_code == 200
    assert ff_resp.get_json()["is_complete"] is True

    # 5. Report page renders
    report_resp = client.get(f"/report/{run_id}")
    assert report_resp.status_code == 200
    assert b"Simulation Audit Report" in report_resp.data

    # 6. Report JSON API
    rep_json_resp = client.get(f"/api/simulations/{run_id}/report")
    assert rep_json_resp.status_code == 200
    rep_json = rep_json_resp.get_json()
    assert "defense_held" in rep_json
    assert "conclusion" in rep_json
    assert "honest_punished_count" in rep_json
    assert "bad_clients_trusted_percent" in rep_json

    # 7. History JSON API
    hist_resp = client.get(f"/api/simulations/{run_id}/history")
    assert hist_resp.status_code == 200
    hist_data = hist_resp.get_json()
    assert len(hist_data["history"]) == (1 + 2) * 24


def test_docs_page_renders(client):
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert b"How TruePrice Works" in resp.data
    assert b"Price Clustering Formula" in resp.data
    assert b"Reputation Adjustment" in resp.data


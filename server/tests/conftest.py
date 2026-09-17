import pytest
from app import app

@pytest.fixture
def flask_app():
    return app

@pytest.fixture()
def database():

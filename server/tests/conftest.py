
import pytest
import pymongo
import uuid
from app import app


@pytest.fixture()
def myApp():
    with app.test_client() as appHandler:
        yield appHandler

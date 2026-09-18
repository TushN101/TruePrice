
import pytest
import pymongo
import uuid
from app import app


@pytest.fixture()
def myApp():
    with app.test_client() as appHandler:
        yield appHandler

@pytest.fixture()
def databaseHandler():
    test_db_name = f"test_database_{uuid.uuid4().hex[:8]}"
    mongo_client = pymongo.MongoClient("mongodb://localhost:27017/")
    test_db = mongo_client[test_db_name]
    clients_collection = test_db["clients"]
    yield {
        "database": test_db,
        "collection": clients_collection,
        "client": mongo_client
    }
    mongo_client.drop_database(test_db)
    mongo_client.close()

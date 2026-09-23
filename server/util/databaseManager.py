
from pymongo import MongoClient

mongoClient = MongoClient(
    "mongodb://localhost:27017",
    serverSelectionTimeoutMS=5000,  # 5 seconds
    connectTimeoutMS=5000,           # connection timeout
    socketTimeoutMS=5000,            # socket operations timeout
)

truePriceDb = mongoClient["truePriceDb"]
myClients = truePriceDb["truePriceClients"]
myData = truePriceDb["truePriceData"]
myObservation = truePriceDb["truePriceObservation"]

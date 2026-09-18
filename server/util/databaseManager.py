
from pymongo import MongoClient

mongoClient = MongoClient("mongodb://localhost:27017/")
truePriceDb = mongoClient["mydatabase"]

myClients = truePriceDb["myClients"]
myData = truePriceDb["myData"]

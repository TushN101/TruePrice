
from pymongo import MongoClient

mongoClient = MongoClient("mongodb://localhost:27017/")
truePriceDb = mongoClient["truePriceDb"]

myClients = truePriceDb["truePriceClients"]
myData = truePriceDb["truePriceData"]

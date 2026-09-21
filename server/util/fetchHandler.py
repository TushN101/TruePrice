

from .databaseManager import myData

def fetchData(postData , clientId):
    response = {}
    itemKey = postData.get("itemKey")

    if not itemKey:
        response["status"] = "error"
        response["message"] =  "Missing itemKey paramter"
        return response

    cursor = myData.find({"itemKey": f"{itemKey}"}).sort("itemTime", 1)
    items = [{"itemValue": doc["itemValue"], "itemTime": doc["itemTime"]} for doc in cursor]

    if not items:
        response["status"] = "missing"
        response["message"] =  "No data exist for the particular item yet."
        return response

    else:
        response["status"] = "sucess"
        response["message"] = items
        return response

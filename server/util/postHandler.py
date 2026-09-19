
"""

Project-specific implementation for processing on the data

"""

from .databaseManager import myData
from datetime import datetime, timezone

def processData(postData , clientId):
    response =  {}
    itemKey = postData.get("itemKey")
    itemValue = postData.get("itemValue")
    itemTime = datetime.now(timezone.utc)
    if not itemKey or not itemValue:
        response["status"] = "error"
        response["message"] =  "Missing paramters required for a valid frame"
        return response

    frame = {
        "itemKey" : itemKey,
        "itemValue" : itemValue,
        "itemTime" : itemTime,
        "clientId" : clientId
    }
    _ = myData.insert_one(frame)
    response["status"] =  "success"
    response["message"] =  "Frame ingested successfully"
    return response



from .databaseManager import myData
from .databaseManager import myObservation
from .logicHandler import computeData
from datetime import datetime , timezone , timedelta


def responseMaker(itemKey):
    return ""

def fetchData(postData , clientId):
    response = {}
    itemKey = postData.get("itemKey")

    if not itemKey:
        response["status"] = "error"
        response["message"] =  "Missing itemKey paramter"
        return response

    lastObs = myObservation.find_one(
        {"itemKey":itemKey},
        sort=[("itemTime"),-1]
    )

    entires = None
    lastKnownTime = None

    if lastObs:
        lastKnownTime = lastObs["itemTime"]
        entires = myData.find({
            "itemKey": itemKey,
            "itemTime": {f"$gte": lastKnownTime}
        }).sort("itemTime",1)
    else:
        entires = list(myData.find({
            "itemKey": itemKey,
        }).sort("itemTime",1))
        if not entires or len(entires) < 10:
            response["status"] = "missing"
            response["message"] = "Not enough information"
            return response

    if lastKnownTime:
        if datetime.now(timezone.utc) - lastKnownTime >= timedelta(hours=24):
            computeData(entires)

    response["status"] = "success"
    response["message"] = responseMaker(itemKey)
    return response


"""

Project-specific implementation for processing on the data

"""

from .databaseManager import myData
from datetime import datetime, timezone


def processData(postData , clientId , clientIp):
    itemKey = postData.get("itemIdentifier","")
    itemValue = postData.get("itemValue","")
    itemTime = datetime.now(timezone.utc)

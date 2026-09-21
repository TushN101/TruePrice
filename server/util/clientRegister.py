

from .databaseManager import myClients
from .clientIpValidator import validateIp
from datetime import datetime, timezone
import uuid

from flask_jwt_extended import (
    create_access_token,
)

def createUser(ipAddress):
    response = {}

    if not validateIp(ipAddress):
        response["status"] = "error"
        response["message"] =  "Invalid IP address. Rejecting registration attempt."

    else:
        try:
            user_id = str(uuid.uuid4())
            client_data = {
                "_id": user_id,
                "ipAddress": ipAddress,
                "createdAt": datetime.now(timezone.utc),
                "trustScore": 0.5
            }
            _ = myClients.insert_one(client_data)

            access_token = create_access_token(identity=user_id)
            response["status"] =  "success"
            response["message"] =  "Client registered successfully"
            response["clientId"] = user_id
            response["access_token"] =  access_token
        except Exception as e:
            print(e)
            response["status"] = "error"
            response["message"] = "Internal Database Error occured"

    return response

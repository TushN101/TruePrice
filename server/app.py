

from flask import Flask
from flask import request
from flask import jsonify
from flask import make_response

from flask_jwt_extended import create_access_token


import pymongo
import uuid
from datetime import datetime , timezone

from .util.ipValidator import validateIp

app = Flask(__name__)
mongoClient = pymongo.MongoClient("mongodb://localhost:27017/")
truePriceDb = mongoClient["mydatabase"]

myClients = truePriceDb["clients"]


@app.route('/')
def index():
    return "Hello World",200

@app.route('/api/registerUser' , methods=["POST"])
def registerUser():
    data = request.get_json()
    ipAddress = data.get('ipAddress')
    country = data.get('country')
    response = {}

    # -- wrong registration --
    if not ipAddress:
        response["status"] = "error"
        response["message"] = "IP address not found in the post data"
        return jsonify(response), 400
    elif not country:
        response["status"] = "error"
        response["message"] = "Country not found in the post data"
        return jsonify(response), 400
    elif not validateIp(ipAddress):
        response["status"] = "error"
        response["message"] = "Invalid IP address found in the post data"
        return jsonify(response), 400

    # -- correct registration --
    else:
        user_id = str(uuid.uuid4())

        # Insert client into database
        try:
            client_data = {
                "_id": user_id,
                "ipAddress": ipAddress,
                "country": country,
                "createdAt": datetime.now(timezone.utc)
            }
            myClients.insert_one(client_data)

            # Create response with UUID as cookie
            access_token = create_access_token(identity=user_id)
            response_obj = make_response(jsonify({
                "status": "success",
                "message": "Client registered successfully",
                "access_token": access_token
            }))
            response_obj.set_cookie('access_token', access_token, max_age=60*60*24*30)
            return response_obj
        except Exception as e:
            print(e)
            response["status"] = "error"
            response["message"] = "Internal Database Error occured"
            return jsonify(response), 400



if __name__ == '__main__':
    app.run(debug=True,host="0.0.0.0",port=5000)

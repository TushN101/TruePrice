


from flask import Flask, jsonify, make_response, request
from flask_jwt_extended import (
    JWTManager,
    get_jwt_identity,
    jwt_required,
)
from util.clientRegister import createUser
from util.postHandler import processData
from util.fetchHandler import fetchData
import secrets


app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = secrets.token_hex(32)
jwt = JWTManager(app)

@app.route('/')
def index():
    return "Hello World",200

@app.route('/api/registerClient',methods=["POST"])
def registerClient():
    ipAddress = str(request.remote_addr)
    response = createUser(ipAddress)
    if response["status"] == "error":
        return jsonify(response),400
    else:
        response_obj = make_response(jsonify(response))
        response_obj.set_cookie('access_token', response["access_token"], max_age=60*60*24*30)
        return response_obj,200

@app.route('/api/postData' , methods=["POST"])
@jwt_required()
def postData():
    clientId = get_jwt_identity()
    clientIp = request.remote_addr
    postData = request.get_json()
    response = processData(postData , clientId)
    if response["status"] == "error":
        return jsonify(response),400
    else:
        return jsonify(response),200

@app.route('/api/getData' , methods=["POST"])
@jwt_required()
def getData():
    clientId = get_jwt_identity()
    clientIp = request.remote_addr
    postData = request.get_json()
    response = fetchData(postData , clientId)
    if response["status"] == "error":
        return jsonify(response),400
    else:
        return jsonify(response),200

if __name__ == '__main__':
    app.run(debug=True,host="0.0.0.0",port=5000)

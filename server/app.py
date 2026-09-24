"""Flask application — TruePrice backend.

Routes
------

* ``GET  /``                        — health check.
* ``POST /api/registerClient``      — anonymous registration, returns
                                       ``clientId`` + access/refresh tokens.
* ``POST /api/refresh``             — exchange a refresh token for a new
                                       access/refresh pair.
* ``POST /api/observations``        — store a raw price observation (JWT).
* ``POST /api/history``             — get computed price history (JWT),
                                       lazily computing missing hours.

All authenticated responses rotate the refresh token (brief §5).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from flask import Flask, jsonify, make_response, request
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    jwt_required,
)

from config import config
from util.clientRegister import createUser
from util.databaseManager import init_db
from util.fetchHandler import fetch_history
from util.postHandler import process_observation

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("trueprice")

# ── Flask + JWT setup ───────────────────────────────────────────────────
app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = config.jwt_secret
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(seconds=config.jwt_access_expires)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(seconds=config.jwt_refresh_expires)
jwt = JWTManager(app)

# Initialise MongoDB (uses mongomock in tests — see tests/conftest.py).
init_db(config.mongo_uri, config.mongo_db)


# ── Routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return jsonify({"name": "TruePrice API", "status": "ok"}), 200


@app.route("/api/registerClient", methods=["POST"])
def registerClient():
    ip_address = request.remote_addr or "0.0.0.0"
    result = createUser(ip_address)
    if result["status"] == "error":
        return jsonify(result), 400

    # Issue a refresh token alongside the access token.
    result["refreshToken"] = create_refresh_token(identity=result["clientId"])
    response = make_response(jsonify(result))
    response.set_cookie(
        "access_token",
        result["accessToken"],
        max_age=config.jwt_access_expires,
        httponly=True,
        samesite="Lax",
    )
    return response, 200


@app.route("/api/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh_token():
    """Exchange a valid refresh token for a new access+refresh pair."""
    client_id = get_jwt_identity()
    access = create_access_token(identity=client_id)
    new_refresh = create_refresh_token(identity=client_id)
    return jsonify({
        "status": "success",
        "accessToken": access,
        "refreshToken": new_refresh,
    }), 200


@app.route("/api/observations", methods=["POST"])
@jwt_required()
def post_observation():
    client_id = get_jwt_identity()
    client_ip = request.remote_addr
    data = request.get_json(silent=True) or {}
    result = process_observation(data, client_id, client_ip)
    # Always rotate the refresh token (brief §5).
    result["refreshToken"] = create_refresh_token(identity=client_id)
    if result["status"] == "error":
        return jsonify(result), 400
    return jsonify(result), 200


@app.route("/api/history", methods=["POST"])
@jwt_required()
def get_history():
    client_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    product_id = data.get("productId")
    from_time = data.get("from")
    to_time = data.get("to")

    if not product_id:
        return jsonify({
            "status": "error",
            "message": "Missing required field: productId",
            "refreshToken": create_refresh_token(identity=client_id),
        }), 400

    result = fetch_history(str(product_id), from_time, to_time)
    result["refreshToken"] = create_refresh_token(identity=client_id)

    if result["status"] == "error":
        return jsonify(result), 400
    # "missing" and "success" both return 200 — the body's ``status``
    # field tells the client whether history exists.
    return jsonify(result), 200


if __name__ == "__main__":
    app.run(
        host=config.flask_host,
        port=config.flask_port,
        debug=config.flask_debug,
    )

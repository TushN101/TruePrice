"""Client registration.

Preserves the original registration logic (UUID generation, IP
validation, JWT access token) while:
* using ``config`` for the initial reputation value,
* renaming the response fields to camelCase to match the new API
  contract (``accessToken`` instead of ``access_token``),
* using the ``clients()`` collection accessor instead of a module-level
  object,
* using ``logging`` instead of bare ``print``.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from flask_jwt_extended import create_access_token

from config import config
from .clientIpValidator import validateIp
from .databaseManager import clients

logger = logging.getLogger(__name__)


def createUser(ipAddress: str) -> dict:
    """Register a new anonymous client.

    Returns a response dict with ``status`` of ``"success"`` or
    ``"error"``.  On success the dict also contains ``clientId``,
    ``accessToken``, and ``message``.
    """
    response: dict = {}

    if not validateIp(ipAddress):
        response["status"] = "error"
        response["message"] = "Invalid IP address. Rejecting registration attempt."
        return response

    try:
        user_id = str(uuid.uuid4())
        client_data = {
            "_id": user_id,
            "ipAddress": ipAddress,
            "createdAt": datetime.now(timezone.utc),
            "reputation": config.reputation_initial,
        }
        clients().insert_one(client_data)

        access_token = create_access_token(identity=user_id)
        response["status"] = "success"
        response["message"] = "Client registered successfully"
        response["clientId"] = user_id
        response["accessToken"] = access_token
        logger.info("Registered new client %s from %s", user_id, ipAddress)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Database error during client registration: %s", exc)
        response["status"] = "error"
        response["message"] = "Internal database error occurred during registration"

    return response

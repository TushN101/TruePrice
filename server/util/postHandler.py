"""Raw observation ingestion.

Accepts an observation from an authenticated client, validates it,
upserts the product record, and stores the raw observation.

Stored observation shape (brief §7):
    {
        "_id":         ObjectId,
        "productId":   "<ebay item id>",
        "clientId":    "<uuid from JWT>",
        "price":       201.0,
        "currency":    "USD",
        "observedAt":  <server-set UTC datetime>,
        "clientIp":    "<requester IP>",
    }

The server sets ``observedAt`` itself (ignoring any client-supplied
timestamp) to prevent backdating.  This is safer and aligns with the
original implementation's behaviour.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from config import config
from .databaseManager import observations, products

logger = logging.getLogger(__name__)


def process_observation(
    post_data: dict,
    clientId: str,
    clientIp: str | None,
) -> dict:
    """Validate and store a single price observation.

    Returns a response dict with ``status`` of ``"success"`` or
    ``"error"``.
    """
    response: dict = {}

    product_id = post_data.get("productId")
    price = post_data.get("price")
    currency = post_data.get("currency") or "USD"
    url = post_data.get("url")
    title = post_data.get("title")

    if not product_id or price is None:
        response["status"] = "error"
        response["message"] = "Missing required fields: productId, price"
        return response

    # Coerce price to float; reject non-numeric values.
    try:
        price = float(price)
    except (TypeError, ValueError):
        response["status"] = "error"
        response["message"] = "price must be numeric"
        return response
    if price < 0:
        response["status"] = "error"
        response["message"] = "price must be non-negative"
        return response

    product_id = str(product_id)

    now = datetime.now(timezone.utc)

    # Upsert the product record so the validator has a URL to work with
    # later.  Using the eBay item ID as ``_id`` keeps the document small
    # and lookup O(1).
    try:
        products().update_one(
            {"_id": product_id},
            {
                "$set": {
                    "platform": config.platform,
                    "externalId": product_id,
                    "url": url,
                    "title": title,
                    "currency": currency,
                    "lastSeenAt": now,
                },
                "$setOnInsert": {"firstSeenAt": now},
            },
            upsert=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Product upsert failed: %s", exc)
        response["status"] = "error"
        response["message"] = "Internal database error during product upsert"
        return response

    # Insert the raw observation.
    try:
        observations().insert_one({
            "productId": product_id,
            "clientId": clientId,
            "price": price,
            "currency": currency,
            "observedAt": now,
            "clientIp": clientIp,
        })
    except Exception as exc:  # noqa: BLE001
        logger.exception("Observation insert failed: %s", exc)
        response["status"] = "error"
        response["message"] = "Internal database error during observation insert"
        return response

    logger.info(
        "Observation stored: product=%s client=%s price=%.2f %s",
        product_id, clientId, price, currency,
    )
    response["status"] = "success"
    response["message"] = "Observation stored"
    return response

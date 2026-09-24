"""MongoDB connection and collection access.

Collections (brief §17):
------------------------------------------------------------------------

``clients``
    Registered clients.  ``{_id: uuid, ipAddress, createdAt, reputation}``.
    ``reputation`` is the *live* reputation (latest across all hours).
    Chronological reconstruction uses ``clientReputationHistory``.

``products``
    Known products.  ``{_id: ebayItemId, platform, externalId, url,
    title, currency, firstSeenAt, lastSeenAt}``.  Using the eBay item
    ID as ``_id`` keeps the document small and lookup O(1).

``observations``
    Raw price observations — the **source of truth**.  ``{productId,
    clientId, price, currency, observedAt, clientIp}``.  Indexed on
    ``(productId, observedAt)`` for efficient range scans.

``hourlyResults``
    Computed per-hour canonical prices — **derived data**.  One document
    per ``(productId, hour)`` pair (unique index).  Never grows into a
    giant array; each hour is a queryable, updateable document.

``clientReputationHistory``
    Reputation change log for chronological correctness (brief §9, §11).
    ``{clientId, productId, hour, asOfHour, previousReputation,
    newReputation, reason, delta, recordedAt}``.  Indexed on
    ``(clientId, asOfHour desc)`` so we can efficiently find a client's
    reputation *as of just before* any given hour — without leaking
    information from later hours.

Design rules enforced here:
* Raw observations and computed results live in separate collections
  (brief §7).
* No giant product document with an ever-growing history array (brief §17).
* Appropriate indexes for product+time and product+hour queries.
"""
from __future__ import annotations

import logging
from typing import Optional

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database

logger = logging.getLogger(__name__)

_client: Optional[MongoClient] = None
_db: Optional[Database] = None


# ─── Initialisation ──────────────────────────────────────────────────────

def init_db(
    mongo_uri: Optional[str] = None,
    db_name: str = "truePriceDb",
    *,
    client: Optional[MongoClient] = None,
) -> None:
    """Initialise the MongoDB connection and ensure indexes.

    Call once at app startup.  Safe to call multiple times (subsequent
    calls are no-ops).  For tests, pass ``client=mongomock.MongoClient()``
    to use an in-memory substitute instead of a real MongoDB.

    Raises if neither ``mongo_uri`` nor ``client`` is provided and the
    DB has not yet been initialised.
    """
    global _client, _db
    if _db is not None:
        return

    if client is not None:
        _client = client
    elif mongo_uri:
        _client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000,
        )
    else:
        raise ValueError("init_db: provide mongo_uri or client=")

    _db = _client[db_name]
    try:
        _ensure_indexes(_db)
    except Exception as exc:
        logger.error(
            "Failed to connect to MongoDB / create indexes at %s: %s",
            mongo_uri or "(injected client)", exc,
        )
        raise
    logger.info("MongoDB initialised: db=%s", db_name)


def reset_db() -> None:
    """Reset the module-level connection.  Intended for tests only."""
    global _client, _db
    _client = None
    _db = None


def _ensure_indexes(db: Database) -> None:
    db["clients"].create_index("ipAddress")
    db["products"].create_index(
        [("platform", ASCENDING), ("externalId", ASCENDING)], unique=True,
    )
    db["products"].create_index("url")
    db["observations"].create_index(
        [("productId", ASCENDING), ("observedAt", ASCENDING)],
    )
    db["observations"].create_index(
        [("clientId", ASCENDING), ("observedAt", DESCENDING)],
    )
    db["hourlyResults"].create_index(
        [("productId", ASCENDING), ("hour", ASCENDING)], unique=True,
    )
    db["clientReputationHistory"].create_index(
        [("clientId", ASCENDING), ("asOfHour", DESCENDING)],
    )


# ─── Collection accessors ───────────────────────────────────────────────

def get_db() -> Database:
    if _db is None:
        raise RuntimeError("database not initialised — call init_db() first")
    return _db


def clients():
    return get_db()["clients"]


def products():
    return get_db()["products"]


def observations():
    return get_db()["observations"]


def hourlyResults():
    return get_db()["hourlyResults"]


def clientReputationHistory():
    return get_db()["clientReputationHistory"]

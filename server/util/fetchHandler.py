"""Lazy historical price-history computation.

This module is the bridge between the **pure** computation engine in
``core.history`` and **MongoDB** persistence.  It implements the lazy
materialisation strategy (brief §8, §10):

    Request product history
        ↓
    Find already-computed hourly results
        ↓
    Identify missing hours (those with observations but no result yet)
        ↓
    Process missing hours **chronologically** (brief §9)
        ↓
    For each hour:
        load client reputations *as of just before* this hour
        → cluster → consensus → (validate if needed)
        → classify → update reputations → persist
        ↓
    Return the full computed history

Chronological correctness (brief §9, §11):
    A client's reputation at hour H is loaded from
    ``clientReputationHistory`` using ``asOfHour < H`` — this *excludes*
    any reputation changes learned at hour H or later.  If no history
    record exists before H, the initial reputation (0.5) is used.  We
    deliberately do **not** fall back to ``clients.reputation`` because
    that field may reflect computations from *later* hours (future
    information).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from config import config
from core.consensus import PricedObservation
from core.history import HourComputationConfig, compute_hour
from core.reputation import ReputationConfig
from util.databaseManager import (
    clientReputationHistory,
    clients,
    hourlyResults,
    observations,
    products,
)
from validators.ebay_validator import EbayValidator

logger = logging.getLogger(__name__)


# ─── Helpers ─────────────────────────────────────────────────────────────

def _hour_floor(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def _build_hour_config() -> HourComputationConfig:
    rep_cfg = ReputationConfig(
        initial=config.reputation_initial,
        minimum=config.reputation_min,
        maximum=config.reputation_max,
        reward=config.reputation_reward,
        penalty=config.reputation_penalty,
        strength_factor=config.reputation_strength_factor,
    )
    return HourComputationConfig(
        tolerance=config.price_tolerance,
        trusted_threshold=config.trusted_client_threshold,
        reputation=rep_cfg,
        validation_random_rate=config.validation_random_rate,
        validation_min_observations=config.validation_min_observations,
    )


def _get_validator():
    """Return a validator callable based on ``config.platform``.

    Returns ``None`` if the platform is unknown — the core engine
    handles this gracefully by falling back to internal consensus.
    """
    if config.platform == "ebay":
        v = EbayValidator(
            base_url=config.ebay_base_url,
            timeout=config.validator_timeout,
            user_agent=config.validator_user_agent,
        )
        # Return a callable that produces a plain dict (the shape
        # expected by core.history.compute_hour).
        return lambda url: v.validate(url).as_dict()
    logger.warning("No validator configured for platform=%s", config.platform)
    return None


def _get_client_reputations_before(
    client_ids: list[str],
    hour: datetime,
) -> dict[str, float]:
    """For each client, find their reputation *as of just before* ``hour``.

    Queries ``clientReputationHistory`` for the latest record with
    ``asOfHour < hour``.  If no such record exists, the client's first
    participation is at this hour or later, so we use the **initial**
    reputation from config.

    We deliberately do NOT fall back to ``clients.reputation`` because
    that field may include reputation changes from *later* hours
    (future-information leakage — brief §11).
    """
    reps: dict[str, float] = {}
    for cid in client_ids:
        record = clientReputationHistory().find_one(
            {"clientId": cid, "asOfHour": {"$lt": hour}},
            sort=[("asOfHour", -1)],
        )
        if record:
            reps[cid] = record["newReputation"]
        else:
            reps[cid] = config.reputation_initial
    return reps


def _persist_hour_result(product_id: str, result, currency: str) -> None:
    """Persist a ``HourResult`` to MongoDB.

    1. Upsert the hourly result document (idempotent on ``(productId, hour)``).
    2. For each participating client:
       a. Check whether any *later* computation already exists.  If not,
          this hour is the client's latest → update ``clients.reputation``.
       b. Insert a ``clientReputationHistory`` record.
    """
    now = datetime.now(timezone.utc)

    # 1 — hourly result
    hourlyResults().update_one(
        {"productId": product_id, "hour": result.hour},
        {"$set": {
            "productId": product_id,
            "hour": result.hour,
            "canonicalPrice": result.canonical_price,
            "currency": currency,
            "confidence": result.confidence,
            "observationCount": result.observation_count,
            "clientCount": result.client_count,
            "validationPerformed": result.validation_performed,
            "validatorPrice": result.validator_price,
            "clientReputationsBefore": result.client_reputations_before,
            "clientReputationsAfter": result.client_reputations_after,
            "correctClients": result.correct_clients,
            "incorrectClients": result.incorrect_clients,
            "clusterCount": result.cluster_count,
            "winningClusterSize": result.winning_cluster_size,
            "computedAt": now,
        }},
        upsert=True,
    )

    # 2 — reputation history + live reputation update
    for cid, rep_after in result.client_reputations_after.items():
        rep_before = result.client_reputations_before.get(cid, config.reputation_initial)
        reason = "correct" if cid in result.correct_clients else "incorrect"

        # Check if any *later* computation already exists for this client.
        # If so, this hour is historical — do NOT overwrite the live
        # reputation (that would regress it with older information).
        later = clientReputationHistory().find_one(
            {"clientId": cid, "asOfHour": {"$gt": result.hour}},
            projection={"_id": 1},
        )
        is_latest = later is None

        clientReputationHistory().insert_one({
            "clientId": cid,
            "productId": product_id,
            "hour": result.hour,
            "asOfHour": result.hour,
            "previousReputation": rep_before,
            "newReputation": rep_after,
            "reason": reason,
            "delta": rep_after - rep_before,
            "recordedAt": now,
        })

        if is_latest:
            clients().update_one(
                {"_id": cid},
                {"$set": {"reputation": rep_after}},
            )


def _serialize_hourly(doc: dict) -> dict:
    """Convert a Mongo ``hourlyResults`` doc to the API response shape."""
    hour = doc["hour"]
    computed_at = doc.get("computedAt")
    return {
        "hour": hour.isoformat() if isinstance(hour, datetime) else str(hour),
        "canonicalPrice": doc["canonicalPrice"],
        "currency": doc.get("currency", "USD"),
        "confidence": doc.get("confidence", 0.0),
        "observationCount": doc.get("observationCount", 0),
        "clientCount": doc.get("clientCount", 0),
        "validationPerformed": doc.get("validationPerformed", False),
        "validatorPrice": doc.get("validatorPrice"),
        "computedAt": (
            computed_at.isoformat()
            if isinstance(computed_at, datetime)
            else str(computed_at)
        ),
    }


# ─── Public entry point ─────────────────────────────────────────────────

def fetch_history(
    product_id: str,
    from_time: Optional[datetime] = None,
    to_time: Optional[datetime] = None,
) -> dict:
    """Return computed price history for ``product_id``, computing any
    missing hourly periods first.

    Returns a response dict:
        {status: "success"|"missing"|"error", productId, currency?, history?}
    """
    if not product_id:
        return {"status": "error", "message": "Missing productId"}

    product = products().find_one({"_id": str(product_id)})
    if not product:
        return {"status": "missing", "message": "Unknown product — no observations yet"}

    currency = product.get("currency", "USD")
    product_url = product.get("url")

    # Load all observations for this product (sorted ascending by time).
    all_obs = list(
        observations().find({"productId": str(product_id)}).sort("observedAt", 1)
    )
    if not all_obs:
        return {"status": "missing", "message": "No observations for this product yet"}

    first_obs_time = all_obs[0]["observedAt"]
    last_obs_time = all_obs[-1]["observedAt"]

    # Apply optional time-window filters.
    if from_time:
        first_obs_time = max(first_obs_time, from_time)
    if to_time:
        last_obs_time = min(last_obs_time, to_time)
    if first_obs_time > last_obs_time:
        return {
            "status": "success",
            "productId": str(product_id),
            "currency": currency,
            "history": [],
        }

    # Group observations by hour (top-of-hour UTC).
    obs_by_hour: dict[datetime, list] = {}
    for obs in all_obs:
        h = _hour_floor(obs["observedAt"])
        if h < _hour_floor(first_obs_time):
            continue
        if to_time and h > _hour_floor(to_time):
            continue
        obs_by_hour.setdefault(h, []).append(obs)

    if not obs_by_hour:
        return {
            "status": "success",
            "productId": str(product_id),
            "currency": currency,
            "history": [],
        }

    # Find which hours are already computed.
    computed_hours: set[datetime] = set()
    for doc in hourlyResults().find(
        {"productId": str(product_id)},
        projection={"hour": 1},
    ):
        computed_hours.add(_hour_floor(doc["hour"]))

    missing_hours = sorted(h for h in obs_by_hour if h not in computed_hours)

    # Cap the number of hours computed in a single request to bound latency.
    if len(missing_hours) > config.max_hours_per_request:
        logger.warning(
            "product %s: %d hours missing, truncating to %d (MAX_HOURS_PER_REQUEST)",
            product_id, len(missing_hours), config.max_hours_per_request,
        )
        missing_hours = missing_hours[: config.max_hours_per_request]

    # Build the computation config + validator.
    hour_cfg = _build_hour_config()
    validator = _get_validator()

    # Process missing hours **chronologically** (brief §9).
    for hour in missing_hours:
        hour_obs = obs_by_hour[hour]

        priced_obs = [
            PricedObservation(
                clientId=o["clientId"],
                price=float(o["price"]),
                observedAt=o["observedAt"],
            )
            for o in hour_obs
        ]

        client_ids = list({o["clientId"] for o in hour_obs})
        reps_before = _get_client_reputations_before(client_ids, hour)

        result = compute_hour(
            hour=hour,
            observations=priced_obs,
            client_reputations_before=reps_before,
            cfg=hour_cfg,
            validator=validator,
            product_url=product_url,
        )

        _persist_hour_result(str(product_id), result, currency)

        logger.info(
            "Computed hour %s for product %s: canonical=%.2f conf=%.2f "
            "obs=%d clients=%d validated=%s",
            hour, product_id, result.canonical_price, result.confidence,
            result.observation_count, result.client_count,
            result.validation_performed,
        )

    # Return all computed results in the requested range.
    history_docs = list(
        hourlyResults().find({
            "productId": str(product_id),
            "hour": {"$gte": _hour_floor(first_obs_time),
                      "$lte": _hour_floor(last_obs_time)},
        }).sort("hour", 1)
    )

    return {
        "status": "success",
        "productId": str(product_id),
        "currency": currency,
        "history": [_serialize_hourly(d) for d in history_docs],
    }

"""Hourly price-history computation — pure orchestration.

This module contains the per-hour computation pipeline.  It takes
observations + client reputations as input and returns a computed
``HourResult``.  No Flask, no MongoDB — the caller handles persistence.

Processing order per hour (brief §15):

    1. Load all observations for the hour
    2. Dedupe to one effective observation per client (latest by time)
    3. Determine price clusters
    4. Determine weighted consensus
    5. Determine canonical / reference price
    6. Determine whether external validation is required
    7. If validation is required, obtain reference price
    8. Determine correct / incorrect status of observations
    9. Update reputations  ← AFTER consensus, never before
   10. Build result

Reputations are updated *after* consensus so that processing order
within an hour cannot influence the consensus calculation.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from .consensus import PricedObservation, weighted_consensus
from .reputation import ReputationConfig, is_trusted, update_reputation

logger = logging.getLogger(__name__)


# A validator is any callable that takes a product URL and returns a dict
# with at least: ``{ok: bool, price: float | None, currency: str | None,
# error: str | None}``.  This decoupling lets us inject a mock validator
# in tests without importing the real eBay validator here.
ValidatorFn = Callable[[str], dict]


@dataclass(frozen=True)
class HourComputationConfig:
    tolerance: float                       # relative price tolerance for clustering
    trusted_threshold: float               # fraction of clients that must be trusted
    reputation: ReputationConfig
    validation_random_rate: float = 0.0    # fraction of hours validated at random (0.3 = 30 %)
    validation_min_observations: int = 0   # hours with fewer observations always validate


@dataclass
class HourResult:
    hour: datetime
    canonical_price: float
    confidence: float
    observation_count: int          # raw observation count (before dedup)
    client_count: int               # unique clients after dedup
    validation_performed: bool
    validator_price: Optional[float]
    client_reputations_before: dict[str, float]
    client_reputations_after: dict[str, float]
    correct_clients: list[str]
    incorrect_clients: list[str]
    cluster_count: int
    winning_cluster_size: int


# ─── Internal helpers ────────────────────────────────────────────────────

def _dedupe_per_client(
    observations: list[PricedObservation],
) -> list[PricedObservation]:
    """Keep only the latest observation per client (by ``observedAt``).

    Policy for multiple observations from the same client within one hour
    (brief §16): one effective observation per client per hour, taking the
    latest submission.  This prevents a single client from gaining
    disproportionate voting power by submitting many times.
    """
    latest: dict[str, PricedObservation] = {}
    for obs in observations:
        existing = latest.get(obs.clientId)
        if existing is None or obs.observedAt >= existing.observedAt:
            latest[obs.clientId] = obs
    return list(latest.values())


# ─── Public entry point ─────────────────────────────────────────────────

def compute_hour(
    hour: datetime,
    observations: list[PricedObservation],
    client_reputations_before: dict[str, float],
    cfg: HourComputationConfig,
    validator: Optional[ValidatorFn] = None,
    product_url: Optional[str] = None,
) -> HourResult:
    """Compute the canonical result for a single hour.

    Args:
        hour: Top-of-hour datetime (UTC).
        observations: All raw observations whose ``observedAt`` falls in
            this hour.
        client_reputations_before: ``{clientId: reputation}`` reflecting
            each participating client's reputation *as of just before*
            this hour (chronologically correct — never includes info from
            this or later hours).
        cfg: Computation config (tolerance, threshold, reputation params).
        validator: Optional external price validator callable.  Injected
            to keep this module decoupled from the validator implementation.
        product_url: Product URL, passed to the validator when validation
            is required.

    Returns:
        A ``HourResult`` with the canonical price, confidence, and
        updated reputations.  The caller is responsible for persisting
        the result and the reputation updates.
    """
    raw_count = len(observations)
    if raw_count == 0:
        raise ValueError("cannot compute an hour with zero observations")

    # 2 — dedupe per client
    deduped = _dedupe_per_client(observations)
    client_count = len(deduped)

    # 3 + 4 — cluster + weighted consensus
    consensus = weighted_consensus(
        deduped, client_reputations_before, cfg.tolerance,
    )

    # 5 — canonical price starts as the consensus result
    canonical_price = consensus.canonical_price

    # 6 — validation triggers
    # Four reasons to validate:
    #   a) trusted_ratio < threshold  (untrusted crowd)
    #   b) random validation          (catches sleepers that built trust)
    #   c) low observation count      (consensus unreliable with few clients)
    #   d) tied weighted support      (crowd genuinely split — can't decide)
    trusted_count = sum(
        1 for cid in client_reputations_before
        if is_trusted(client_reputations_before[cid])
    )
    trusted_ratio = trusted_count / client_count if client_count else 0.0

    not_enough_trusted = trusted_ratio < cfg.trusted_threshold
    random_validate = (
        cfg.validation_random_rate > 0
        and random.random() < cfg.validation_random_rate
    )
    too_few_observations = (
        cfg.validation_min_observations > 0
        and client_count < cfg.validation_min_observations
    )

    # Detect tied weighted support between the top two clusters.
    # If two clusters have (near-)equal weighted support, the crowd is
    # genuinely split and internal consensus cannot decide — validate.
    tied_support = False
    if len(consensus.all_clusters) >= 2:
        supports = sorted(consensus.weighted_supports.values(), reverse=True)
        if supports[0] > 0 and abs(supports[0] - supports[1]) < 1e-9:
            tied_support = True

    needs_validation = (
        not_enough_trusted
        or random_validate
        or too_few_observations
        or tied_support
    )

    if needs_validation:
        reasons = []
        if not_enough_trusted:
            reasons.append(f"trusted_ratio={trusted_ratio:.2f}<{cfg.trusted_threshold}")
        if random_validate:
            reasons.append("random")
        if too_few_observations:
            reasons.append(f"clients={client_count}<{cfg.validation_min_observations}")
        if tied_support:
            reasons.append("tied_support")
        logger.debug(
            "hour %s: validation triggered (%s)",
            hour, ", ".join(reasons),
        )

    # 7 — external validation when the internal crowd is not trusted enough
    validation_performed = False
    validator_price: Optional[float] = None

    if needs_validation and validator is not None and product_url:
        try:
            vr = validator(product_url)
            if vr.get("ok") and vr.get("price") is not None:
                validation_performed = True
                validator_price = float(vr["price"])
                canonical_price = validator_price
                logger.info(
                    "hour %s: external validation performed, "
                    "validator_price=%.2f (consensus was %.2f)",
                    hour, validator_price, consensus.canonical_price,
                )
            else:
                logger.warning(
                    "hour %s: validation requested but validator returned "
                    "ok=False (%s); falling back to internal consensus",
                    hour, vr.get("error"),
                )
        except Exception as exc:  # noqa: BLE001 — validator must not crash the hour
            logger.warning(
                "hour %s: validator raised %s; falling back to internal consensus",
                hour, exc,
            )
    elif needs_validation:
        logger.info(
            "hour %s: validation needed but no validator/url available "
            "(trusted_ratio=%.2f, random=%s, few_obs=%s, tied=%s); "
            "using internal consensus",
            hour, trusted_ratio, random_validate, too_few_observations,
            tied_support,
        )

    # 8 — correct / incorrect classification (relative tolerance)
    correct_clients: list[str] = []
    incorrect_clients: list[str] = []
    reps_after = dict(client_reputations_before)

    # Consensus strength in [0.5, 1.0] — drives the strength-based update.
    # confidence is winning_support / total_support, already in [0, 1].
    consensus_strength = max(0.5, consensus.confidence)

    for obs in deduped:
        ref = canonical_price
        if ref <= 0:
            is_correct = False
        else:
            diff = abs(obs.price - ref) / ref
            is_correct = diff <= cfg.tolerance

        cid = obs.clientId
        (correct_clients if is_correct else incorrect_clients).append(cid)

        # 9 — update reputation *after* consensus is fully determined.
        # Strength-based: wrong answers against strong consensus are
        # punished harder.  Bounded-proportional: high-rep clients fall
        # fast, low-rep clients rise fast.  No loopholes — only uses the
        # consensus outcome, never the "true" price.
        reps_after[cid] = update_reputation(
            reps_after[cid], is_correct, cfg.reputation,
            consensus_strength=consensus_strength,
        )

    # 10 — build result
    return HourResult(
        hour=hour,
        canonical_price=canonical_price,
        confidence=consensus.confidence,
        observation_count=raw_count,
        client_count=client_count,
        validation_performed=validation_performed,
        validator_price=validator_price,
        client_reputations_before=dict(client_reputations_before),
        client_reputations_after=reps_after,
        correct_clients=correct_clients,
        incorrect_clients=incorrect_clients,
        cluster_count=len(consensus.all_clusters),
        winning_cluster_size=len(consensus.winning_cluster.observations),
    )

"""Price clustering and reputation-weighted consensus.

Pure functions — no Flask, no MongoDB.

The consensus algorithm (brief §11–§13):

1. **Cluster** observations into price groups using *relative* tolerance.
   Two prices ``p1 < p2`` belong to the same cluster when
   ``(p2 - p1) / p1 <= tolerance``.  Clustering is single-linkage on the
   sorted price sequence, so a chain of near-equal prices (201, 202, 203)
   forms one cluster while a large jump (201, 350) starts a new one.

2. **Weight each cluster** by the sum of participating client reputations.
   A cluster of 100 low-reputation clients should not automatically
   outweigh a smaller group of highly trusted clients.

3. **Pick the winner** — the cluster with the highest weighted support.
   Ties are broken by higher client count, then by lower representative
   price (deterministic).

4. **Representative price** of the winning cluster is the *weighted median*
   of its observations (weighted by client reputation).  The weighted
   median is less sensitive to extreme outliers than a weighted mean.

5. **Confidence** = winning support / total support across all clusters.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ─── Data containers ──────────────────────────────────────────────────────

@dataclass
class PricedObservation:
    """A single observation used by the consensus engine."""
    clientId: str
    price: float
    observedAt: object  # datetime; opaque to this module


@dataclass
class Cluster:
    representative: float                      # seed price
    observations: list[PricedObservation] = field(default_factory=list)

    @property
    def client_count(self) -> int:
        return len({o.clientId for o in self.observations})

    @property
    def prices(self) -> list[float]:
        return [o.price for o in self.observations]


@dataclass
class ConsensusResult:
    canonical_price: float
    confidence: float
    winning_cluster: Cluster
    all_clusters: list[Cluster]
    weighted_supports: dict[int, float]   # {cluster_index: support}


# ─── Clustering ───────────────────────────────────────────────────────────

def cluster_prices(
    observations: list[PricedObservation],
    tolerance: float,
) -> list[Cluster]:
    """Group observations into price clusters by relative tolerance.

    Single-linkage on the sorted price sequence: walk ascending, start a
    new cluster only when the gap from the immediately preceding (lower)
    price exceeds ``tolerance`` relative to that preceding price.

    Deterministic, O(n log n).
    """
    if not observations:
        return []
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")

    sorted_obs = sorted(observations, key=lambda o: o.price)
    clusters: list[Cluster] = []
    current = Cluster(representative=sorted_obs[0].price)
    current.observations.append(sorted_obs[0])

    for obs in sorted_obs[1:]:
        prev_price = current.observations[-1].price
        gap = (obs.price - prev_price) / prev_price if prev_price > 0 else 0.0
        if gap <= tolerance:
            current.observations.append(obs)
        else:
            clusters.append(current)
            current = Cluster(representative=obs.price)
            current.observations.append(obs)
    clusters.append(current)
    return clusters


# ─── Weighted median ──────────────────────────────────────────────────────

def weighted_median(prices: list[float], weights: list[float]) -> float:
    """Return the weighted median of ``prices`` given per-price ``weights``."""
    if not prices:
        raise ValueError("cannot compute weighted median of an empty list")
    if len(prices) != len(weights):
        raise ValueError("prices and weights must have the same length")

    pairs = sorted(zip(prices, weights), key=lambda p: p[0])
    total = sum(weights)
    if total <= 0:
        # All-zero weights — fall back to the plain median.
        mid = len(pairs) // 2
        return pairs[mid][0]

    half = total / 2.0
    cumulative = 0.0
    for price, weight in pairs:
        cumulative += weight
        if cumulative >= half:
            return price
    return pairs[-1][0]


# ─── Weighted consensus ──────────────────────────────────────────────────

def weighted_consensus(
    observations: list[PricedObservation],
    client_reputations: dict[str, float],
    tolerance: float,
) -> ConsensusResult:
    """Determine the canonical price via reputation-weighted consensus.

    ``client_reputations`` maps ``clientId → reputation``.  Clients not
    present in the map are treated as having the neutral reputation 0.5.
    """
    if not observations:
        raise ValueError("cannot compute consensus with no observations")

    clusters = cluster_prices(observations, tolerance)

    # Weighted support per cluster
    supports: list[float] = []
    for cluster in clusters:
        support = 0.0
        for obs in cluster.observations:
            support += client_reputations.get(obs.clientId, 0.5)
        supports.append(support)

    total_support = sum(supports)

    # Pick the winner — highest support; tie-break by higher client count,
    # then by *lower* representative price (deterministic).
    winner_index = max(
        range(len(clusters)),
        key=lambda i: (
            supports[i],
            clusters[i].client_count,
            -clusters[i].representative,
        ),
    )
    winning = clusters[winner_index]

    # Weighted median of the winning cluster
    prices = [o.price for o in winning.observations]
    weights = [client_reputations.get(o.clientId, 0.5) for o in winning.observations]
    canonical = weighted_median(prices, weights)

    confidence = (supports[winner_index] / total_support) if total_support > 0 else 0.0

    logger.debug(
        "consensus: clusters=%d winner_rep=%.2f canonical=%.2f confidence=%.3f",
        len(clusters), winning.representative, canonical, confidence,
    )

    return ConsensusResult(
        canonical_price=canonical,
        confidence=confidence,
        winning_cluster=winning,
        all_clusters=clusters,
        weighted_supports={i: s for i, s in enumerate(supports)},
    )

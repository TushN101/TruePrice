"""Price clustering and reputation-weighted consensus engine.

Provides pure functions for clustering price observations, calculating
reputation-weighted cluster support, computing the weighted median, and
determining consensus confidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass
class Observation:
    """A price observation submitted by a simulated user."""
    user_id: str
    price: float


@dataclass
class Cluster:
    """A cluster of close price observations within relative tolerance."""
    representative: float
    observations: list[Observation] = field(default_factory=list)

    @property
    def user_count(self) -> int:
        return len({o.user_id for o in self.observations})

    @property
    def prices(self) -> list[float]:
        return [o.price for o in self.observations]


@dataclass
class ConsensusResult:
    """Outcome of weighted consensus calculation."""
    canonical_price: float
    confidence: float
    winning_cluster: Cluster
    all_clusters: list[Cluster]
    weighted_supports: dict[int, float]


def cluster_prices(observations: list[Observation], tolerance: float) -> list[Cluster]:
    """Cluster observations by relative price tolerance.

    Uses single-linkage on sorted prices:
    Walk ascending, starting a new cluster only when the relative difference
    (p - prev) / prev > tolerance.
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


def weighted_median(prices: list[float], weights: list[float]) -> float:
    """Calculate the weighted median of prices given per-observation weights."""
    if not prices:
        raise ValueError("cannot compute weighted median of an empty list")
    if len(prices) != len(weights):
        raise ValueError("prices and weights must have the same length")

    pairs = sorted(zip(prices, weights), key=lambda p: p[0])
    total = sum(weights)
    if total <= 0:
        mid = len(pairs) // 2
        return pairs[mid][0]

    half = total / 2.0
    cumulative = 0.0
    for price, weight in pairs:
        cumulative += weight
        if cumulative >= half:
            return price
    return pairs[-1][0]


def weighted_consensus(
    observations: list[Observation],
    user_reputations: Mapping[str, float],
    tolerance: float,
) -> ConsensusResult:
    """Determine the canonical crowd price via reputation-weighted consensus.

    Each cluster's strength is the sum of reputations of its contributing users.
    Winner is chosen by highest weighted support, with ties broken by higher
    unique user count, then lower representative price.
    """
    if not observations:
        raise ValueError("cannot compute consensus with no observations")

    clusters = cluster_prices(observations, tolerance)

    # Compute weighted support per cluster
    supports: list[float] = []
    for cluster in clusters:
        support = sum(user_reputations.get(o.user_id, 0.5) for o in cluster.observations)
        supports.append(support)

    total_support = sum(supports)

    # Determine winning cluster
    winner_idx = max(
        range(len(clusters)),
        key=lambda i: (
            supports[i],
            clusters[i].user_count,
            -clusters[i].representative,
        ),
    )
    winning = clusters[winner_idx]

    # Weighted median within winning cluster
    prices = [o.price for o in winning.observations]
    weights = [user_reputations.get(o.user_id, 0.5) for o in winning.observations]
    canonical = weighted_median(prices, weights)

    confidence = (supports[winner_idx] / total_support) if total_support > 0 else 0.0

    return ConsensusResult(
        canonical_price=canonical,
        confidence=confidence,
        winning_cluster=winning,
        all_clusters=clusters,
        weighted_supports={i: s for i, s in enumerate(supports)},
    )

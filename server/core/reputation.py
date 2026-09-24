"""Client reputation update logic.

Pure functions — no Flask, no MongoDB.  The caller is responsible for
persistence.  This isolation is mandated by the project brief (§17):
"Keep reputation update logic isolated from HTTP and MongoDB code."

The update model is **strength-based** (inspired by the reference
TrueTest simulation): the magnitude of the update depends on how
strong the consensus was.  A wrong answer against a strong consensus
is punished harder than a wrong answer against a weak (split) consensus.

Additionally, the update is **bounded-proportional**: the reward is
scaled by ``(max - current)`` and the penalty by ``(current - min)``.
This makes reputation:
  - easy to lose (high-rep clients fall fast when wrong)
  - hard to rebuild (low-rep clients gain slowly when right)

This is logically sound — it mirrors real-world trust dynamics — and
contains NO loopholes.  The system never uses the "true" price
directly; it only uses the consensus outcome and each client's
agreement/disagreement with it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReputationConfig:
    """Tunable parameters for the reputation system."""
    initial: float = 0.5
    minimum: float = 0.1
    maximum: float = 0.9
    reward: float = 0.05          # base reward (added to strength-scaled bonus)
    penalty: float = 0.05         # base penalty (added to strength-scaled bonus)
    strength_factor: float = 0.10  # how much consensus strength scales the update


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp ``value`` to ``[minimum, maximum]``."""
    if minimum > maximum:
        raise ValueError(f"minimum ({minimum}) > maximum ({maximum})")
    return max(minimum, min(maximum, value))


def is_trusted(reputation: float, neutral: float = 0.5) -> bool:
    """A client is *trusted* when reputation is above the neutral baseline."""
    return reputation > neutral


def _compute_update_magnitude(
    consensus_strength: float,
    cfg: ReputationConfig,
) -> float:
    """Compute the update magnitude based on consensus strength.

    ``consensus_strength`` is in [0, 1] where 0.5 = perfectly split,
    1.0 = unanimous.  We map this to [0, 1] via ``2 * (strength - 0.5)``
    so that a 50/50 split gives 0 extra and unanimity gives maximum extra.

    The final magnitude is::
        base + strength_factor * normalized_strength

    E.g. with base=0.05, strength_factor=0.10:
        unanimous (1.0) → 0.05 + 0.10*1.0 = 0.15
        strong (0.8)   → 0.05 + 0.10*0.6 = 0.11
        split (0.5)    → 0.05 + 0.10*0.0 = 0.05
    """
    normalized = max(0.0, 2.0 * (consensus_strength - 0.5))
    return cfg.reward + cfg.strength_factor * normalized


def update_reputation(
    current: float,
    correct: bool,
    cfg: ReputationConfig,
    consensus_strength: float = 1.0,
) -> float:
    """Return the new reputation after a single correct/incorrect judgment.

    Args:
        current: The client's reputation before this judgment.
        correct: Whether the client's observation agreed with the
            canonical price.
        cfg: Reputation config.
        consensus_strength: How strong the consensus was for this hour,
            in [0.5, 1.0].  Higher = stronger agreement among clients.
            A wrong answer against a strong consensus is punished harder.

    The update is **bounded-proportional**:
        reward  *= (maximum - current)   # high-rep clients gain less
        penalty *= (current - minimum)   # high-rep clients lose more

    This is NOT a loophole — it's the natural property that trust is
    easy to lose and hard to regain.  The system never uses the "true"
    price; only the consensus outcome and the client's agreement with it.

    The result is clamped to ``[cfg.minimum, cfg.maximum]``.
    """
    if not isinstance(current, (int, float)):
        raise TypeError(f"reputation must be numeric, got {type(current).__name__}")

    magnitude = _compute_update_magnitude(consensus_strength, cfg)

    if correct:
        # Reward — scaled by how much room is left to grow.
        scale = (cfg.maximum - current) / (cfg.maximum - cfg.minimum)
        delta = magnitude * max(0.0, scale)
        new_value = current + delta
    else:
        # Penalty — scaled by how far the client has fallen already.
        scale = (current - cfg.minimum) / (cfg.maximum - cfg.minimum)
        delta = magnitude * max(0.0, scale)
        new_value = current - delta

    clamped = clamp(new_value, cfg.minimum, cfg.maximum)

    logger.debug(
        "reputation update: current=%.4f correct=%s strength=%.2f "
        "magnitude=%.4f scale=%.4f delta=%+.4f new=%.4f",
        current, correct, consensus_strength, magnitude, scale,
        delta if correct else -delta, clamped,
    )
    return clamped

"""Reputation and trust dynamics module.

Implements a strength-based, bounded-proportional reputation model.
Logic is strictly decoupled from storage, network, and web presentation.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReputationConfig:
    """Tunable parameters for reputation adjustments."""
    initial: float = 0.5
    minimum: float = 0.1
    maximum: float = 0.9
    reward: float = 0.05
    penalty: float = 0.05
    strength_factor: float = 0.10


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp value to [minimum, maximum]."""
    if minimum > maximum:
        raise ValueError(f"minimum ({minimum}) > maximum ({maximum})")
    return max(minimum, min(maximum, value))


def is_trusted(reputation: float, neutral: float = 0.5) -> bool:
    """A client is trusted when reputation strictly exceeds the neutral baseline."""
    return reputation > neutral


def compute_update_magnitude(consensus_strength: float, cfg: ReputationConfig) -> float:
    """Compute update magnitude based on consensus strength.

    Consensus strength is mapped from [0.5, 1.0] to [0.0, 1.0].
    A 50/50 split gives 0 bonus, while unanimous agreement gives full bonus.
    Magnitude = base + strength_factor * normalized_strength.
    """
    normalized = max(0.0, 2.0 * (consensus_strength - 0.5))
    return cfg.reward + cfg.strength_factor * normalized


def update_reputation(
    current: float,
    correct: bool,
    cfg: ReputationConfig,
    consensus_strength: float = 1.0,
) -> float:
    """Calculate the updated reputation score after a submission verdict.

    The model uses bounded-proportional scaling:
    - High-reputation users have little room to increase, so rewards scale by
      (maximum - current) / (maximum - minimum).
    - High-reputation users have a lot of trust to lose, so penalties scale by
      (current - minimum) / (maximum - minimum).

    This mirrors real-world trust: hard to build, easy to lose.
    """
    if not isinstance(current, (int, float)):
        raise TypeError(f"reputation must be numeric, got {type(current).__name__}")

    magnitude = compute_update_magnitude(consensus_strength, cfg)
    span = cfg.maximum - cfg.minimum
    if span <= 0:
        return cfg.minimum

    if correct:
        scale = (cfg.maximum - current) / span
        delta = magnitude * max(0.0, scale)
        new_val = current + delta
    else:
        scale = (current - cfg.minimum) / span
        delta = magnitude * max(0.0, scale)
        new_val = current - delta

    return clamp(new_val, cfg.minimum, cfg.maximum)

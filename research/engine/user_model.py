"""Crowd user model and behavioral archetypes.

Defines the base User and specific archetypes: Honest, Imposter, and Sleeper Cell.
Follows the Open/Closed Principle to allow future attack variants.
"""
from __future__ import annotations

import enum
import random
from dataclasses import dataclass
from typing import Optional

from .config import SimulationConfig
from .consensus import Observation


class UserArchetype(str, enum.Enum):
    HONEST = "honest"
    IMPOSTER = "imposter"
    SLEEPER = "sleeper"


@dataclass
class User:
    """Represents a simulated crowd participant."""
    user_id: str
    archetype: UserArchetype
    reputation: float = 0.5
    submissions_count: int = 0
    correct_count: int = 0
    incorrect_count: int = 0

    def is_sleeper_activated(self, current_tick: int, config: SimulationConfig) -> bool:
        """Check if this user is a sleeper cell that has passed activation day."""
        if self.archetype != UserArchetype.SLEEPER:
            return False
        return current_tick >= config.sleeper_activation_tick

    def get_status_tag(self, current_tick: int, config: SimulationConfig) -> str:
        """Return the display status for color coding in UI:

        - honest -> 'honest' (green)
        - imposter -> 'imposter' (red)
        - sleeper before activation -> 'sleeper_dormant' (yellow)
        - sleeper after activation -> 'sleeper_active' (red)
        """
        if self.archetype == UserArchetype.HONEST:
            return "honest"
        if self.archetype == UserArchetype.IMPOSTER:
            return "imposter"
        if self.is_sleeper_activated(current_tick, config):
            return "sleeper_active"
        return "sleeper_dormant"

    def decide_participation(self, config: SimulationConfig, rng: random.Random) -> bool:
        """Check if this user decides to participate in this hourly tick."""
        return rng.random() < config.participation_factor

    def generate_observation(
        self,
        current_tick: int,
        actual_price: float,
        config: SimulationConfig,
        rng: random.Random,
    ) -> Optional[Observation]:
        """Generate a price observation for this hour based on archetype."""
        if not self.decide_participation(config, rng):
            return None

        # Determine whether to submit fake data
        is_attack = False
        if self.archetype == UserArchetype.IMPOSTER:
            # Imposters are adversarial from tick 1 unconditionally
            is_attack = True
        elif self.archetype == UserArchetype.SLEEPER and self.is_sleeper_activated(current_tick, config):
            # Sleepers remain honest until their activation schedule
            is_attack = True

        if is_attack:
            # Attacker submission: fake price with small noise
            noise = rng.uniform(-0.005, 0.005)
            price = round(config.fake_product_price * (1.0 + noise), 2)
            return Observation(user_id=self.user_id, price=price)

        # Honest submission: actual price with human error model
        if rng.random() < config.honest_error_rate:
            # Human mistake: outside normal price tolerance
            sign = rng.choice([-1, 1])
            err = rng.uniform(config.price_tolerance + 0.01, config.honest_error_margin_percent)
            price = round(actual_price * (1.0 + sign * err), 2)
        else:
            # Accurate submission: natural small variation within tolerance
            noise = rng.uniform(-config.honest_base_noise_percent, config.honest_base_noise_percent)
            price = round(actual_price * (1.0 + noise), 2)

        return Observation(user_id=self.user_id, price=price)

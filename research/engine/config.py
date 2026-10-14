"""Simulation configuration model and parameter validation."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SimulationConfig:
    """Tunable parameters for the crowd-consensus simulation."""

    # Random seed for byte-for-byte reproducibility
    seed: int = 42

    # Crowd composition
    total_users: int = 200
    imposter_count: int = 30
    sleeper_cell_count: int = 20
    sleeper_activation_day: int = 10  # Day (from simulation start) when sleepers turn malicious

    # Behavioral probabilities and margins
    participation_factor: float = 0.70       # Probability a user participates in any hourly tick
    honest_error_rate: float = 0.15          # Probability an honest submission contains error
    honest_error_margin_percent: float = 0.10  # How far off a wrong honest submission can be (e.g. 10%)
    honest_base_noise_percent: float = 0.01   # Natural noise for accurate honest submissions (±1%)

    # Product and attack payloads
    fake_product_name: str = "SuperWidget Pro Max"
    fake_product_price: float = 99.0
    base_price: float = 200.0
    daily_price_drift: float = 0.01          # Daily drift of ground truth price (±1%)

    # Protocol & timeline settings
    price_tolerance: float = 0.02            # 2% relative tolerance for clustering and correctness
    seed_history_days: int = 7               # Honest warm-up period before attack window
    simulation_days: int = 14                # Length of attack phase
    consensus_threshold: float = 0.80        # Minimum weighted agreement among trusted submissions to accept without validation
    min_trusted_ratio: float = 0.50          # Minimum fraction of participating users that must be trusted (>0.5)

    # Reputation dynamics (matching server/core/reputation.py)
    reputation_initial: float = 0.5
    reputation_min: float = 0.1
    reputation_max: float = 0.9
    reputation_reward: float = 0.05
    reputation_penalty: float = 0.05
    reputation_strength_factor: float = 0.10

    @property
    def honest_users(self) -> int:
        """Derived count of honest users."""
        return self.total_users - self.imposter_count - self.sleeper_cell_count

    @property
    def total_days(self) -> int:
        """Total days across seed period and attack simulation."""
        return self.seed_history_days + self.simulation_days

    @property
    def total_ticks(self) -> int:
        """Total hours in simulation."""
        return self.total_days * 24

    @property
    def attack_start_tick(self) -> int:
        """Tick at which the attack window begins."""
        return self.seed_history_days * 24

    @property
    def sleeper_activation_tick(self) -> int:
        """Tick at which sleeper cells activate."""
        return (self.seed_history_days + self.sleeper_activation_day) * 24

    def validate(self) -> None:
        """Validate parameter ranges."""
        if self.total_users <= 0:
            raise ValueError("total_users must be positive")
        if self.imposter_count < 0 or self.sleeper_cell_count < 0:
            raise ValueError("imposter_count and sleeper_cell_count must be non-negative")
        if self.honest_users < 0:
            raise ValueError(
                f"imposter_count ({self.imposter_count}) + sleeper_cell_count ({self.sleeper_cell_count}) "
                f"exceeds total_users ({self.total_users})"
            )
        if not (0.0 <= self.participation_factor <= 1.0):
            raise ValueError("participation_factor must be in [0, 1]")
        if not (0.0 <= self.honest_error_rate <= 1.0):
            raise ValueError("honest_error_rate must be in [0, 1]")
        if not (0.0 <= self.consensus_threshold <= 1.0):
            raise ValueError("consensus_threshold must be in [0, 1]")
        if not (0.0 <= self.min_trusted_ratio <= 1.0):
            raise ValueError("min_trusted_ratio must be in [0, 1]")
        if self.seed_history_days < 0 or self.simulation_days <= 0:
            raise ValueError("simulation_days must be positive and seed_history_days non-negative")
        if self.base_price <= 0:
            raise ValueError("base_price must be positive")

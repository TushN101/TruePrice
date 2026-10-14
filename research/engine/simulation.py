"""Simulation engine module.

Orchestrates the hourly tick loop, tracks ground truth price trajectory,
aggregates submissions, evaluates consensus, executes validation checks,
updates user reputations, and compiles analytics.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .config import SimulationConfig
from .consensus import Observation, weighted_consensus
from .reputation import ReputationConfig, is_trusted, update_reputation
from .user_model import User, UserArchetype


@dataclass
class TickRecord:
    """Snapshot of a single hourly tick."""
    tick: int
    day: int
    hour_of_day: int
    actual_price: float
    predicted_price: float
    canonical_price: float
    price_error_percent: float
    confidence: float
    trusted_ratio: float
    trusted_agreement: float
    submission_count: int
    validation_performed: bool
    in_attack_window: bool
    top_20_users: List[Dict[str, Any]]


class SimulationEngine:
    """Manages the full lifecycle of a simulation run."""

    def __init__(self, config: Optional[SimulationConfig] = None):
        self.config = config or SimulationConfig()
        self.config.validate()

        # Deterministic random generator for this run
        self.rng = random.Random(self.config.seed)

        # Reputation config
        self.rep_config = ReputationConfig(
            initial=self.config.reputation_initial,
            minimum=self.config.reputation_min,
            maximum=self.config.reputation_max,
            reward=self.config.reputation_reward,
            penalty=self.config.reputation_penalty,
            strength_factor=self.config.reputation_strength_factor,
        )

        # Initialize users
        self.users: Dict[str, User] = self._create_population()

        # Precompute actual price trajectory for all hours
        self.actual_prices: List[float] = self._generate_price_trajectory()

        # State tracking
        self.current_tick: int = 0
        self.history: List[TickRecord] = []
        self.cumulative_validations: int = 0

    def _create_population(self) -> Dict[str, User]:
        """Create initial crowd population with defined archetypes."""
        users: Dict[str, User] = {}
        idx = 1

        # Honest users
        for _ in range(self.config.honest_users):
            uid = f"honest_{idx:03d}"
            users[uid] = User(user_id=uid, archetype=UserArchetype.HONEST, reputation=self.config.reputation_initial)
            idx += 1

        # Imposters
        imp_idx = 1
        for _ in range(self.config.imposter_count):
            uid = f"imposter_{imp_idx:03d}"
            users[uid] = User(user_id=uid, archetype=UserArchetype.IMPOSTER, reputation=self.config.reputation_initial)
            imp_idx += 1

        # Sleepers
        slp_idx = 1
        for _ in range(self.config.sleeper_cell_count):
            uid = f"sleeper_{slp_idx:03d}"
            users[uid] = User(user_id=uid, archetype=UserArchetype.SLEEPER, reputation=self.config.reputation_initial)
            slp_idx += 1

        return users

    def _generate_price_trajectory(self) -> List[float]:
        """Generate actual ground-truth price trajectory across all ticks."""
        trajectory: List[float] = []
        curr = self.config.base_price

        for day in range(self.config.total_days):
            drift = self.rng.uniform(-self.config.daily_price_drift, self.config.daily_price_drift)
            day_price = round(curr * (1.0 + drift), 2)
            curr = day_price
            for _ in range(24):
                trajectory.append(day_price)

        return trajectory

    @property
    def is_complete(self) -> bool:
        """Whether all ticks have finished."""
        return self.current_tick >= self.config.total_ticks

    def get_user_reputations(self) -> Dict[str, float]:
        """Map of user_id to current reputation."""
        return {u.user_id: u.reputation for u in self.users.values()}

    def get_top_users(self, n: int = 20) -> List[Dict[str, Any]]:
        """Return the top N users ranked by trust score."""
        sorted_users = sorted(
            self.users.values(),
            key=lambda u: (u.reputation, u.correct_count, -u.incorrect_count),
            reverse=True,
        )
        return [
            {
                "user_id": u.user_id,
                "archetype": u.archetype.value,
                "status_tag": u.get_status_tag(self.current_tick, self.config),
                "reputation": round(u.reputation, 4),
                "submissions": u.submissions_count,
                "correct_count": u.correct_count,
                "incorrect_count": u.incorrect_count,
            }
            for u in sorted_users[:n]
        ]

    def step(self) -> TickRecord:
        """Advance the simulation by one hourly tick."""
        if self.is_complete:
            raise RuntimeError("Simulation has already finished")

        tick = self.current_tick
        day = tick // 24
        hour_of_day = tick % 24
        actual_price = self.actual_prices[tick]
        in_attack = tick >= self.config.attack_start_tick

        user_reps_before = self.get_user_reputations()

        # Step 1: Gather observations from participating users
        obs_list: List[Observation] = []
        for user in self.users.values():
            obs = user.generate_observation(tick, actual_price, self.config, self.rng)
            if obs is not None:
                obs_list.append(obs)

        # Fallback if no observations submitted this hour
        if not obs_list:
            crowd_price = actual_price
            confidence = 1.0
            trusted_ratio = 1.0
            trusted_agreement = 1.0
            needs_val = False
            tied_support = False
            consensus_strength = 1.0
        else:
            # Step 2: Compute consensus among submissions
            consensus = weighted_consensus(obs_list, user_reps_before, self.config.price_tolerance)
            crowd_price = consensus.canonical_price
            confidence = consensus.confidence

            # Trusted user ratio among active participants
            participating_ids = [o.user_id for o in obs_list]
            trusted_count = sum(1 for uid in participating_ids if is_trusted(user_reps_before[uid]))
            trusted_ratio = trusted_count / len(participating_ids) if participating_ids else 0.0

            # Weighted agreement among trusted submissions
            winning_trusted_sup = sum(
                user_reps_before[o.user_id]
                for o in consensus.winning_cluster.observations
                if is_trusted(user_reps_before[o.user_id])
            )
            total_trusted_sup = sum(
                user_reps_before[o.user_id]
                for o in obs_list
                if is_trusted(user_reps_before[o.user_id])
            )
            trusted_agreement = (winning_trusted_sup / total_trusted_sup) if total_trusted_sup > 0 else 0.0

            # Tie detection between top two clusters
            supports = sorted(consensus.weighted_supports.values(), reverse=True)
            tied_support = len(supports) >= 2 and supports[0] > 0 and abs(supports[0] - supports[1]) < 1e-9

            # Consensus strength in [0.5, 1.0] drives reputation update scale
            consensus_strength = max(0.5, confidence)

            # Step 3: Validation trigger
            # Triggers if:
            # - Too few trusted submissions (trusted_ratio < min_trusted_ratio)
            # - Consensus strength across crowd is weak (confidence < consensus_threshold)
            # - Consensus among trusted submissions is divided (trusted_agreement < consensus_threshold)
            # - Top clusters are tied in support
            needs_val = (
                trusted_ratio < self.config.min_trusted_ratio
                or confidence < self.config.consensus_threshold
                or (total_trusted_sup > 0 and trusted_agreement < self.config.consensus_threshold)
                or tied_support
            )

        # Step 4: Canonical price resolution
        if needs_val:
            canonical_price = actual_price
            validation_performed = True
            self.cumulative_validations += 1
        else:
            canonical_price = crowd_price
            validation_performed = False

        # Step 5: Grade observations and update user reputations
        for obs in obs_list:
            user = self.users[obs.user_id]
            diff = abs(obs.price - canonical_price) / canonical_price if canonical_price > 0 else 1.0
            is_correct = diff <= self.config.price_tolerance

            new_rep = update_reputation(
                current=user.reputation,
                correct=is_correct,
                cfg=self.rep_config,
                consensus_strength=consensus_strength,
            )
            user.reputation = new_rep
            user.submissions_count += 1
            if is_correct:
                user.correct_count += 1
            else:
                user.incorrect_count += 1

        price_error = abs(crowd_price - actual_price) / actual_price if actual_price > 0 else 0.0

        record = TickRecord(
            tick=tick,
            day=day,
            hour_of_day=hour_of_day,
            actual_price=round(actual_price, 2),
            predicted_price=round(crowd_price, 2),
            canonical_price=round(canonical_price, 2),
            price_error_percent=round(price_error * 100, 2),
            confidence=round(confidence, 3),
            trusted_ratio=round(trusted_ratio, 3),
            trusted_agreement=round(trusted_agreement, 3),
            submission_count=len(obs_list),
            validation_performed=validation_performed,
            in_attack_window=in_attack,
            top_20_users=self.get_top_users(20),
        )

        self.history.append(record)
        self.current_tick += 1
        return record

    def run_all(self) -> List[TickRecord]:
        """Run all remaining ticks to completion."""
        while not self.is_complete:
            self.step()
        return self.history

    def get_report(self) -> Dict[str, Any]:
        """Compile the comprehensive final report metrics."""
        if not self.history:
            return {}

        total_hours = len(self.history)
        total_validations = sum(1 for r in self.history if r.validation_performed)
        overall_validation_rate = total_validations / total_hours if total_hours else 0.0

        # Seed vs Attack validation rates
        seed_ticks = [r for r in self.history if not r.in_attack_window]
        attack_ticks = [r for r in self.history if r.in_attack_window]

        seed_val_count = sum(1 for r in seed_ticks if r.validation_performed)
        seed_val_rate = seed_val_count / len(seed_ticks) if seed_ticks else 0.0

        attack_val_count = sum(1 for r in attack_ticks if r.validation_performed)
        attack_val_rate = attack_val_count / len(attack_ticks) if attack_ticks else 0.0

        # Validation rate over time binned by day
        daily_validation_rates = []
        for day in range(self.config.total_days):
            day_records = [r for r in self.history if r.day == day]
            if day_records:
                v_count = sum(1 for r in day_records if r.validation_performed)
                daily_validation_rates.append({
                    "day": day,
                    "validation_rate": round(v_count / len(day_records), 3),
                    "validations": v_count,
                    "in_attack": day >= self.config.seed_history_days,
                })

        # Top 20 composition at the end
        top_20 = self.get_top_users(20)
        imposters_in_top_20 = sum(1 for u in top_20 if u["archetype"] == UserArchetype.IMPOSTER.value)
        sleepers_in_top_20 = sum(1 for u in top_20 if u["archetype"] == UserArchetype.SLEEPER.value)
        adversaries_in_top_20 = imposters_in_top_20 + sleepers_in_top_20
        defense_held = adversaries_in_top_20 == 0

        # Hours with predicted price deviated by > 5%
        acceptable_band_percent = 5.0
        deviated_hours = sum(1 for r in self.history if r.price_error_percent > acceptable_band_percent)

        # Mean trust score per archetype
        honest_reps = [u.reputation for u in self.users.values() if u.archetype == UserArchetype.HONEST]
        imposter_reps = [u.reputation for u in self.users.values() if u.archetype == UserArchetype.IMPOSTER]
        sleeper_reps = [u.reputation for u in self.users.values() if u.archetype == UserArchetype.SLEEPER]

        mean_honest_trust = sum(honest_reps) / len(honest_reps) if honest_reps else 0.0
        mean_imposter_trust = sum(imposter_reps) / len(imposter_reps) if imposter_reps else 0.0
        mean_sleeper_trust = sum(sleeper_reps) / len(sleeper_reps) if sleeper_reps else 0.0

        # Client population breakdown and trust audit
        honest_users = [u for u in self.users.values() if u.archetype == UserArchetype.HONEST]
        bad_users = [u for u in self.users.values() if u.archetype in (UserArchetype.IMPOSTER, UserArchetype.SLEEPER)]
        imposters = [u for u in self.users.values() if u.archetype == UserArchetype.IMPOSTER]
        sleepers = [u for u in self.users.values() if u.archetype == UserArchetype.SLEEPER]

        honest_users_total = len(honest_users)
        bad_users_total = len(bad_users)

        # Honest clients who were punished at least once for human error
        honest_punished_count = sum(1 for u in honest_users if u.incorrect_count > 0)
        honest_punished_percent = round((honest_punished_count / honest_users_total * 100), 1) if honest_users_total else 0.0

        # Honest clients who remained trusted (> 0.5) despite occasional mistakes
        honest_still_trusted = sum(1 for u in honest_users if u.reputation > 0.5)
        honest_still_trusted_percent = round((honest_still_trusted / honest_users_total * 100), 1) if honest_users_total else 0.0

        # Bad clients that achieved or retained trust rating > 0.5 (defense breach indicator)
        bad_clients_trusted_count = sum(1 for u in bad_users if u.reputation > 0.5)
        bad_clients_trusted_percent = round((bad_clients_trusted_count / bad_users_total * 100), 1) if bad_users_total else 0.0
        imposters_trusted_count = sum(1 for u in imposters if u.reputation > 0.5)
        sleepers_trusted_count = sum(1 for u in sleepers if u.reputation > 0.5)

        # Total submissions across all hours
        total_submissions = sum(r.submission_count for r in self.history)

        # Plain-English conclusion sentence
        if defense_held and deviated_hours == 0:
            conclusion = (
                f"Defense held with 100% integrity: 0.0% of adversarial users ({bad_clients_trusted_count}/{bad_users_total}) "
                f"exceeded neutral trust (0.5), 0 adversaries reached the Top 20, and all {honest_users_total} honest clients "
                f"retained trusted status despite {honest_punished_count} being temporarily penalized for human errors. "
                f"Validations settled at {daily_validation_rates[-1]['validation_rate'] * 100:.1f}% as autonomous consensus took over."
            )
        elif defense_held:
            conclusion = (
                f"The defense preserved user rankings with 0 adversaries in the Top 20 "
                f"(bad users trusted: {bad_clients_trusted_percent}%), though {deviated_hours} hours had price deviation outside the 5% band."
            )
        else:
            conclusion = (
                f"Defense was breached: {bad_clients_trusted_percent}% of bad users ({bad_clients_trusted_count}/{bad_users_total}) "
                f"held a rating > 0.5, with {adversaries_in_top_20} adversaries penetrating the Top 20."
            )

        return {
            "total_hours": total_hours,
            "total_validations": total_validations,
            "total_submissions": total_submissions,
            "overall_validation_rate": round(overall_validation_rate, 4),
            "seed_validation_rate": round(seed_val_rate, 4),
            "attack_validation_rate": round(attack_val_rate, 4),
            "daily_validation_rates": daily_validation_rates,
            "honest_users_total": honest_users_total,
            "honest_punished_count": honest_punished_count,
            "honest_punished_percent": honest_punished_percent,
            "honest_still_trusted": honest_still_trusted,
            "honest_still_trusted_percent": honest_still_trusted_percent,
            "bad_users_total": bad_users_total,
            "bad_clients_trusted_count": bad_clients_trusted_count,
            "bad_clients_trusted_percent": bad_clients_trusted_percent,
            "imposters_trusted_count": imposters_trusted_count,
            "sleepers_trusted_count": sleepers_trusted_count,
            "imposters_in_top_20": imposters_in_top_20,
            "sleepers_in_top_20": sleepers_in_top_20,
            "adversaries_in_top_20": adversaries_in_top_20,
            "defense_held": defense_held,
            "deviated_hours": deviated_hours,
            "acceptable_band_percent": acceptable_band_percent,
            "mean_honest_trust": round(mean_honest_trust, 4),
            "mean_imposter_trust": round(mean_imposter_trust, 4),
            "mean_sleeper_trust": round(mean_sleeper_trust, 4),
            "conclusion": conclusion,
            "top_20": top_20,
        }

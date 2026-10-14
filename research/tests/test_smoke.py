"""Smoke tests verifying core simulation dynamics and defense properties."""
import pytest
from engine.config import SimulationConfig
from engine.simulation import SimulationEngine


def test_smoke_1_benign_crowd_validation_rate_drops():
    """Smoke test #1:

    Zero imposters, zero sleepers -> validation rate trends to ~0 after the seed
    period; prediction error stays low.
    """
    config = SimulationConfig(
        seed=123,
        total_users=100,
        imposter_count=0,
        sleeper_cell_count=0,
        participation_factor=0.75,
        honest_error_rate=0.10,
        honest_error_margin_percent=0.08,
        seed_history_days=5,
        simulation_days=7,
        consensus_threshold=0.75,
    )
    engine = SimulationEngine(config)
    engine.run_all()
    report = engine.get_report()

    # Validations should occur during seed period while initial trust builds
    assert report["seed_validation_rate"] > 0.0

    # In benign crowd, after seed period trust is established (trusted_ratio > 0.75),
    # so validation rate during the simulation days drops significantly (near 0)
    assert report["attack_validation_rate"] < 0.10

    # Prediction error should remain very low (no deviated hours > 5%)
    assert report["deviated_hours"] == 0

    # Mean honest trust should be high (above 0.8)
    assert report["mean_honest_trust"] > 0.80

    # Defense held trivially
    assert report["defense_held"] is True


def test_smoke_2_heavy_imposters_downgraded_defense_holds():
    """Smoke test #2:

    Heavy imposter ratio -> imposters get downgraded, never dominate the top 20 at the end.
    """
    config = SimulationConfig(
        seed=999,
        total_users=200,
        imposter_count=70,       # Heavy imposter ratio (35% pure attackers)
        sleeper_cell_count=20,   # 10% sleepers
        sleeper_activation_day=3,
        participation_factor=0.70,
        honest_error_rate=0.15,
        honest_error_margin_percent=0.10,
        seed_history_days=7,
        simulation_days=10,
        consensus_threshold=0.80,
    )
    engine = SimulationEngine(config)
    engine.run_all()
    report = engine.get_report()

    # Imposters must have been downgraded significantly (near minimum 0.1)
    assert report["mean_imposter_trust"] < 0.20

    # Imposters must NEVER dominate the Top 20 at the end (should be 0 or heavily suppressed)
    assert report["imposters_in_top_20"] == 0

    # Total adversaries in top 20 should be 0
    assert report["adversaries_in_top_20"] == 0

    # Honest users should maintain strong trust
    assert report["mean_honest_trust"] > 0.75

    # Overall defense held
    assert report["defense_held"] is True


def test_reproducibility_same_seed_identical_run():
    """Same seed + same config = identical run."""
    cfg1 = SimulationConfig(seed=42, total_users=50, imposter_count=10, seed_history_days=2, simulation_days=2)
    cfg2 = SimulationConfig(seed=42, total_users=50, imposter_count=10, seed_history_days=2, simulation_days=2)

    engine1 = SimulationEngine(cfg1)
    engine2 = SimulationEngine(cfg2)

    engine1.run_all()
    engine2.run_all()

    rep1 = engine1.get_report()
    rep2 = engine2.get_report()

    assert rep1["total_validations"] == rep2["total_validations"]
    assert rep1["overall_validation_rate"] == rep2["overall_validation_rate"]
    assert rep1["mean_honest_trust"] == rep2["mean_honest_trust"]
    assert rep1["mean_imposter_trust"] == rep2["mean_imposter_trust"]

    for r1, r2 in zip(engine1.history, engine2.history):
        assert r1.actual_price == r2.actual_price
        assert r1.predicted_price == r2.predicted_price
        assert r1.validation_performed == r2.validation_performed

"""Unit tests for consensus, clustering, and reputation mechanics in research/engine."""
import pytest
from engine.consensus import Observation, cluster_prices, weighted_consensus, weighted_median
from engine.reputation import ReputationConfig, clamp, is_trusted, update_reputation


def test_reputation_basics():
    cfg = ReputationConfig(initial=0.5, minimum=0.1, maximum=0.9, reward=0.05, penalty=0.05, strength_factor=0.10)
    assert not is_trusted(0.5)
    assert is_trusted(0.51)
    assert clamp(0.05, 0.1, 0.9) == 0.1
    assert clamp(0.95, 0.1, 0.9) == 0.9


def test_reputation_bounded_proportional_updates():
    cfg = ReputationConfig(initial=0.5, minimum=0.1, maximum=0.9, reward=0.05, penalty=0.05, strength_factor=0.10)
    # At 0.5, correct with strength 1.0 -> magnitude 0.15, scale (0.9-0.5)/0.8 = 0.5 -> delta 0.075 -> 0.575
    new_rep = update_reputation(0.5, correct=True, cfg=cfg, consensus_strength=1.0)
    assert new_rep == pytest.approx(0.575)

    # At 0.5, incorrect with strength 1.0 -> magnitude 0.15, scale (0.5-0.1)/0.8 = 0.5 -> delta 0.075 -> 0.425
    new_rep_bad = update_reputation(0.5, correct=False, cfg=cfg, consensus_strength=1.0)
    assert new_rep_bad == pytest.approx(0.425)


def test_cluster_prices_single_linkage():
    obs = [
        Observation("u1", 200.0),
        Observation("u2", 202.0),
        Observation("u3", 203.0),
        Observation("u4", 300.0),
    ]
    clusters = cluster_prices(obs, tolerance=0.02)
    assert len(clusters) == 2
    assert len(clusters[0].observations) == 3
    assert len(clusters[1].observations) == 1


def test_weighted_median_logic():
    prices = [100.0, 200.0, 300.0]
    weights = [1.0, 10.0, 1.0]
    assert weighted_median(prices, weights) == 200.0

    # Skewed weight on lowest price
    weights_skewed = [10.0, 1.0, 1.0]
    assert weighted_median(prices, weights_skewed) == 100.0


def test_weighted_consensus_winner():
    obs = [
        Observation("good_1", 200.0),
        Observation("good_2", 201.0),
        Observation("bad_1", 99.0),
        Observation("bad_2", 99.0),
    ]
    reps = {
        "good_1": 0.8,
        "good_2": 0.8,
        "bad_1": 0.2,
        "bad_2": 0.2,
    }
    result = weighted_consensus(obs, reps, tolerance=0.02)
    # Good cluster has support 1.6, bad cluster has support 0.4
    assert result.canonical_price == pytest.approx(200.0, abs=2.0)
    assert result.confidence == pytest.approx(1.6 / 2.0)

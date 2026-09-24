"""Tests for the hourly computation pipeline (core/history.py).

These tests verify the per-hour computation logic in isolation — no
MongoDB, no Flask.  The validator is injected as a mock callable.
"""
from datetime import datetime, timezone

import pytest

from core.consensus import PricedObservation
from core.history import HourComputationConfig, compute_hour, _dedupe_per_client
from core.reputation import ReputationConfig


@pytest.fixture()
def cfg():
    rep = ReputationConfig(
        initial=0.5, minimum=0.1, maximum=0.9,
        reward=0.05, penalty=0.05,
    )
    return HourComputationConfig(
        tolerance=0.02, trusted_threshold=0.6, reputation=rep,
    )


def _obs(cid, price, ts):
    return PricedObservation(clientId=cid, price=price, observedAt=ts)


HOUR = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


# ─── Dedup ───────────────────────────────────────────────────────────────

def test_dedupe_keeps_latest_per_client():
    """Multiple observations from the same client → only the latest."""
    obs = [
        _obs("A", 201, 1),
        _obs("A", 202, 5),   # later → this one wins
        _obs("A", 200, 3),
        _obs("B", 350, 2),
    ]
    deduped = _dedupe_per_client(obs)
    by_client = {o.clientId: o for o in deduped}
    assert by_client["A"].price == 202
    assert by_client["B"].price == 350
    assert len(deduped) == 2


def test_dedupe_single_per_client():
    obs = [_obs("A", 201, 1), _obs("B", 202, 2)]
    assert len(_dedupe_per_client(obs)) == 2


# ─── Basic computation ───────────────────────────────────────────────────

def test_compute_hour_basic_consensus(cfg):
    """3 clients at ~201, 1 at 350 → canonical ~201, 350 client incorrect."""
    obs = [
        _obs("A", 201, 1), _obs("B", 202, 2), _obs("C", 201, 3),
        _obs("D", 350, 4),
    ]
    reps_before = {"A": 0.5, "B": 0.5, "C": 0.5, "D": 0.5}
    result = compute_hour(HOUR, obs, reps_before, cfg)

    assert result.canonical_price == pytest.approx(201, abs=1)
    assert result.observation_count == 4
    assert result.client_count == 4
    assert result.validation_performed is False
    # A, B, C correct; D incorrect
    assert set(result.correct_clients) == {"A", "B", "C"}
    assert set(result.incorrect_clients) == {"D"}
    # Reputations updated after consensus
    assert result.client_reputations_after["A"] == pytest.approx(0.55)
    assert result.client_reputations_after["D"] == pytest.approx(0.45)


def test_compute_hour_no_validator_when_trusted(cfg):
    """When the trusted threshold is met, no validation is performed."""
    obs = [_obs("A", 201, 1), _obs("B", 202, 2)]
    reps_before = {"A": 0.8, "B": 0.7}  # both trusted → 100% ≥ 60%
    result = compute_hour(HOUR, obs, reps_before, cfg,
                          validator=lambda url: {"ok": True, "price": 999})
    assert result.validation_performed is False
    assert result.canonical_price == pytest.approx(201, abs=1)


def test_compute_hour_validation_below_threshold(cfg):
    """When trusted ratio < threshold, validation is performed."""
    obs = [_obs("A", 201, 1), _obs("B", 350, 2)]
    # Both at 0.5 → 0% trusted < 60% → validation needed.
    reps_before = {"A": 0.5, "B": 0.5}

    call_count = {"n": 0}

    def mock_validator(url):
        call_count["n"] += 1
        return {"ok": True, "price": 201, "currency": "USD"}

    result = compute_hour(
        HOUR, obs, reps_before, cfg,
        validator=mock_validator, product_url="https://www.ebay.com/itm/123",
    )
    assert call_count["n"] == 1
    assert result.validation_performed is True
    assert result.validator_price == 201
    # Canonical price should be the validator's price, not the consensus.
    assert result.canonical_price == 201


def test_compute_hour_validation_failure_falls_back(cfg):
    """If the validator returns ok=False, fall back to internal consensus."""
    obs = [_obs("A", 201, 1), _obs("B", 350, 2)]
    reps_before = {"A": 0.5, "B": 0.5}

    result = compute_hour(
        HOUR, obs, reps_before, cfg,
        validator=lambda url: {"ok": False, "price": None, "error": "blocked"},
        product_url="https://www.ebay.com/itm/123",
    )
    assert result.validation_performed is False
    # Falls back to internal consensus (support for 201 = 0.5, for 350 = 0.5
    # → tie → lower price wins → 201).
    assert result.canonical_price == pytest.approx(201, abs=1)


def test_compute_hour_validation_determines_correctness(cfg):
    """When validation sets the reference price, correctness follows it."""
    obs = [_obs("A", 201, 1), _obs("B", 350, 2)]
    reps_before = {"A": 0.5, "B": 0.5}

    # Validator says the true price is 201.
    result = compute_hour(
        HOUR, obs, reps_before, cfg,
        validator=lambda url: {"ok": True, "price": 201},
        product_url="https://www.ebay.com/itm/123",
    )
    # A (201) is correct; B (350) is incorrect.
    assert "A" in result.correct_clients
    assert "B" in result.incorrect_clients
    # With 2 clients at 0.5, confidence = 0.5, strength = 0.5
    # magnitude = 0.05 + 0.10*0.0 = 0.05
    # scale at 0.5 = 0.5, delta = 0.05*0.5 = 0.025
    # correct: 0.5 + 0.025 = 0.525, incorrect: 0.5 - 0.025 = 0.475
    assert result.client_reputations_after["A"] == pytest.approx(0.525)
    assert result.client_reputations_after["B"] == pytest.approx(0.475)


def test_compute_hour_reputation_not_updated_before_consensus(cfg):
    """Reputation updates must not influence the consensus for the same hour.

    This is verified by checking that ``client_reputations_before`` is
    unchanged (it's the input) and ``client_reputations_after`` reflects
    post-consensus updates.
    """
    obs = [_obs("A", 201, 1), _obs("B", 350, 2)]
    reps_before = {"A": 0.5, "B": 0.5}
    result = compute_hour(HOUR, obs, reps_before, cfg)

    # The "before" dict should be the original input.
    assert result.client_reputations_before == reps_before
    # The "after" dict should differ (reputations moved).
    assert result.client_reputations_after != reps_before


def test_compute_hour_multiple_obs_same_client_deduped(cfg):
    """A client submitting multiple prices in one hour → only latest counts."""
    obs = [
        _obs("A", 201, 1),
        _obs("A", 350, 5),   # latest → this one is used
        _obs("B", 202, 2),
    ]
    reps_before = {"A": 0.5, "B": 0.5}
    result = compute_hour(HOUR, obs, reps_before, cfg)
    # client_count should be 2 (A and B), not 3.
    assert result.client_count == 2
    assert result.observation_count == 3  # raw count


def test_compute_hour_replay_attack_no_double_count(cfg):
    """Replay attack: a client submits the same observation 1000 times.

    The system must count this as ONE observation, not 1000.  This
    prevents a single client from gaining disproportionate voting
    power by replaying requests.

    Setup:
      - Client A submits price 201 a thousand times (replay attack)
      - Client B submits price 350 once
      - Client C submits price 202 once

    Expected:
      - client_count = 3 (not 1002)
      - A's 1000 replays count as 1 vote
      - The consensus should reflect 2 votes for ~201 vs 1 vote for 350
    """
    # 1000 replays from client A, all at the same price 201
    replays = [_obs("A", 201, i) for i in range(1000)]
    obs = replays + [_obs("B", 350, 1001), _obs("C", 202, 1002)]

    reps_before = {"A": 0.5, "B": 0.5, "C": 0.5}
    result = compute_hour(HOUR, obs, reps_before, cfg)

    # Only 3 unique clients, despite 1002 raw observations.
    assert result.client_count == 3
    assert result.observation_count == 1002  # raw count includes replays
    # The winning cluster should be {201, 202} (2 clients) not {350} (1 client).
    assert result.canonical_price == pytest.approx(201, abs=1)


def test_compute_hour_same_client_same_price_replay(cfg):
    """Even if the replayed price is the 'wrong' one, it still counts once."""
    obs = [
        _obs("A", 350, 1),  # A submits wrong price
        _obs("A", 350, 2),  # A replays same wrong price
        _obs("A", 350, 3),  # A replays again
        _obs("B", 201, 1),
        _obs("C", 202, 1),
    ]
    reps_before = {"A": 0.5, "B": 0.5, "C": 0.5}
    result = compute_hour(HOUR, obs, reps_before, cfg)
    assert result.client_count == 3  # not 5
    # 2 good clients vs 1 bad → canonical should be ~201
    assert result.canonical_price == pytest.approx(201, abs=1)


def test_compute_hour_empty_observations_rejected(cfg):
    with pytest.raises(ValueError):
        compute_hour(HOUR, [], {}, cfg)


def test_compute_hour_cluster_count(cfg):
    obs = [_obs("A", 201, 1), _obs("B", 202, 2), _obs("C", 350, 3)]
    reps_before = {"A": 0.5, "B": 0.5, "C": 0.5}
    result = compute_hour(HOUR, obs, reps_before, cfg)
    assert result.cluster_count == 2  # {201,202} and {350}


def test_compute_hour_reputation_bounds_respected(cfg):
    """A client near max reputation barely moves on a correct observation.

    With bounded-proportional updates, the reward is scaled by
    (max - current), so a client at 0.89 gains very little.
    magnitude = 0.15 (unanimous, 1 client)
    scale = (0.9 - 0.89) / 0.8 = 0.0125
    delta = 0.15 * 0.0125 = 0.001875
    new = 0.89 + 0.001875 = 0.891875  (under the max)
    """
    obs = [_obs("A", 201, 1)]
    reps_before = {"A": 0.89}  # near max
    result = compute_hour(HOUR, obs, reps_before, cfg)
    assert result.client_reputations_after["A"] < cfg.reputation.maximum
    assert result.client_reputations_after["A"] == pytest.approx(0.891875)


def test_compute_hour_no_validator_when_needed(cfg):
    """If validation is needed but no validator is provided, the hour
    still computes (falls back to internal consensus)."""
    obs = [_obs("A", 201, 1), _obs("B", 350, 2)]
    reps_before = {"A": 0.5, "B": 0.5}
    result = compute_hour(HOUR, obs, reps_before, cfg,
                          validator=None, product_url=None)
    assert result.validation_performed is False
    assert result.canonical_price == pytest.approx(201, abs=1)

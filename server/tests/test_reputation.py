"""Tests for the reputation update logic (core/reputation.py)."""
import pytest

from core.reputation import (
    ReputationConfig,
    clamp,
    is_trusted,
    update_reputation,
)


@pytest.fixture()
def cfg():
    return ReputationConfig(
        initial=0.5, minimum=0.1, maximum=0.9,
        reward=0.05, penalty=0.05, strength_factor=0.10,
    )


def test_initial_reputation_is_neutral(cfg):
    """A fresh client starts at 0.5 — neither trusted nor untrusted."""
    assert cfg.initial == 0.5
    assert not is_trusted(cfg.initial)
    assert not is_trusted(0.5)


def test_correct_observation_increases_reputation(cfg):
    """A correct observation raises the reputation.

    With strength=1.0 (unanimous): magnitude = 0.05 + 0.10*1.0 = 0.15
    scale at 0.5 = (0.9-0.5)/(0.9-0.1) = 0.5
    delta = 0.15 * 0.5 = 0.075
    new = 0.5 + 0.075 = 0.575
    """
    new = update_reputation(0.5, correct=True, cfg=cfg, consensus_strength=1.0)
    assert new == pytest.approx(0.575)


def test_incorrect_observation_decreases_reputation(cfg):
    """An incorrect observation lowers the reputation.

    magnitude = 0.15, scale at 0.5 = 0.5, delta = 0.075
    new = 0.5 - 0.075 = 0.425
    """
    new = update_reputation(0.5, correct=False, cfg=cfg, consensus_strength=1.0)
    assert new == pytest.approx(0.425)


def test_reputation_lower_bound(cfg):
    """Reputation never drops below the configured minimum.

    The bounded-proportional formula approaches the minimum
    asymptotically (each update is scaled by (current - min)), so it
    gets very close but never reaches it exactly.  This matches the
    reference TrueTest script's behaviour.
    """
    rep = 0.11
    for _ in range(30):
        rep = update_reputation(rep, correct=False, cfg=cfg, consensus_strength=1.0)
    assert rep < 0.101  # very close to minimum
    assert rep >= cfg.minimum  # never below


def test_reputation_upper_bound(cfg):
    """Reputation never exceeds the configured maximum.

    Same asymptotic behaviour as the lower bound — approaches but
    never reaches the maximum exactly.
    """
    rep = 0.89
    for _ in range(30):
        rep = update_reputation(rep, correct=True, cfg=cfg, consensus_strength=1.0)
    assert rep > 0.899  # very close to maximum
    assert rep <= cfg.maximum  # never above


def test_is_trusted_above_neutral():
    assert is_trusted(0.51)
    assert is_trusted(0.9)
    assert not is_trusted(0.5)
    assert not is_trusted(0.49)
    assert not is_trusted(0.1)


def test_clamp():
    assert clamp(0.5, 0.1, 0.9) == 0.5
    assert clamp(0.0, 0.1, 0.9) == 0.1
    assert clamp(1.0, 0.1, 0.9) == 0.9


def test_clamp_invalid_range():
    with pytest.raises(ValueError):
        clamp(0.5, 0.9, 0.1)


def test_update_reputation_rejects_non_numeric(cfg):
    with pytest.raises(TypeError):
        update_reputation("high", correct=True, cfg=cfg)


def test_reputation_persists_across_updates(cfg):
    """Multiple updates chain correctly (simulating multiple hours)."""
    rep = 0.5
    # Hour 1: correct (unanimous)
    rep = update_reputation(rep, True, cfg, consensus_strength=1.0)
    assert rep == pytest.approx(0.575)
    # Hour 2: incorrect (unanimous)
    rep = update_reputation(rep, False, cfg, consensus_strength=1.0)
    # scale at 0.575 = (0.575-0.1)/0.8 = 0.59375
    # delta = 0.15 * 0.59375 = 0.0890625
    # new = 0.575 - 0.0890625 = 0.4859375
    assert rep == pytest.approx(0.4859375)
    # Hour 3: correct
    rep = update_reputation(rep, True, cfg, consensus_strength=1.0)
    # scale at 0.4859375 = (0.9-0.4859375)/0.8 = 0.517578125
    # delta = 0.15 * 0.517578125 = 0.07763671875
    # new = 0.4859375 + 0.07763671875 = 0.56357421875
    assert rep == pytest.approx(0.56357421875)


def test_weak_consensus_smaller_update(cfg):
    """A weak (split) consensus produces a smaller update than a strong one."""
    strong = update_reputation(0.5, True, cfg, consensus_strength=1.0)
    weak = update_reputation(0.5, True, cfg, consensus_strength=0.5)
    # strong: magnitude = 0.05 + 0.10*1.0 = 0.15
    # weak:   magnitude = 0.05 + 0.10*0.0 = 0.05
    assert strong > weak
    assert strong == pytest.approx(0.575)
    # weak: scale at 0.5 = 0.5, delta = 0.05*0.5 = 0.025, new = 0.525
    assert weak == pytest.approx(0.525)


def test_high_rep_falls_fast(cfg):
    """A high-reputation client loses more than a low-rep client when wrong.

    This is the key property that catches sleepers: they climb to high
    reputation, then one wrong answer drops them significantly.
    """
    high_rep = update_reputation(0.8, False, cfg, consensus_strength=1.0)
    low_rep = update_reputation(0.3, False, cfg, consensus_strength=1.0)
    # high: scale = (0.8-0.1)/0.8 = 0.875, delta = 0.15*0.875 = 0.13125
    # new = 0.8 - 0.13125 = 0.66875  → dropped by 0.13125
    # low:  scale = (0.3-0.1)/0.8 = 0.25, delta = 0.15*0.25 = 0.0375
    # new = 0.3 - 0.0375 = 0.2625    → dropped by only 0.0375
    assert (0.8 - high_rep) > (0.3 - low_rep)
    assert high_rep == pytest.approx(0.66875)
    assert low_rep == pytest.approx(0.2625)


def test_low_rep_rises_fast(cfg):
    """A low-reputation client gains more than a high-rep client when right.

    This is the mirror of test_high_rep_falls_fast — trust is easy to
    lose (high falls fast) and hard to regain (low rises fast relative
    to high, which barely moves).
    """
    low_rep = update_reputation(0.3, True, cfg, consensus_strength=1.0)
    high_rep = update_reputation(0.8, True, cfg, consensus_strength=1.0)
    # low:  scale = (0.9-0.3)/0.8 = 0.75, delta = 0.15*0.75 = 0.1125
    # new = 0.3 + 0.1125 = 0.4125   → gained 0.1125
    # high: scale = (0.9-0.8)/0.8 = 0.125, delta = 0.15*0.125 = 0.01875
    # new = 0.8 + 0.01875 = 0.81875 → gained only 0.01875
    assert (low_rep - 0.3) > (high_rep - 0.8)
    assert low_rep == pytest.approx(0.4125)
    assert high_rep == pytest.approx(0.81875)

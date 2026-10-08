"""
Unit tests for compute_incremental_score() — the shared pure scoring function
used by both the batch path and the real-time CDC scoring consumer.

Constants under test:
    HALF_LIFE_DAYS = 7.0
    SCORING_K_FACTOR = 50.0
"""

import datetime
import pytest

from agentic_tools.recommendation_system.interest_score import (
    HALF_LIFE_DAYS,
    SCORING_K_FACTOR,
    compute_incremental_score,
)


UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


# --- Basic cases ---

def test_first_event_no_history():
    """Brand new profile+ticker: raw = incoming, interest = raw/(raw+K)."""
    raw, interest = compute_incremental_score(
        current_raw=0.0,
        incoming_points=10.0,
        prev_interaction=None,
        last_event_time=T0,
    )
    assert raw == 10.0
    assert interest == pytest.approx(10.0 / (10.0 + SCORING_K_FACTOR))


def test_same_moment_no_decay():
    """Event at exact same time as last interaction → zero decay."""
    raw, interest = compute_incremental_score(
        current_raw=20.0,
        incoming_points=5.0,
        prev_interaction=T0,
        last_event_time=T0,
    )
    # decay_factor = 0.5^(0/7) = 1.0 → raw = 20*1 + 5 = 25
    assert raw == pytest.approx(25.0)
    assert interest == pytest.approx(25.0 / (25.0 + SCORING_K_FACTOR))


# --- Decay behavior ---

def test_half_life_exact():
    """After exactly HALF_LIFE_DAYS, existing score is halved before adding new."""
    prev = T0
    event = T0 + datetime.timedelta(days=HALF_LIFE_DAYS)

    raw, _ = compute_incremental_score(
        current_raw=100.0,
        incoming_points=0.0,
        prev_interaction=prev,
        last_event_time=event,
    )
    # decay = 0.5^(7/7) = 0.5 → raw = 100*0.5 + 0 = 50
    assert raw == pytest.approx(50.0)


def test_two_half_lives():
    """After 2x half-life, score decays to 25%."""
    prev = T0
    event = T0 + datetime.timedelta(days=2 * HALF_LIFE_DAYS)

    raw, _ = compute_incremental_score(
        current_raw=100.0,
        incoming_points=10.0,
        prev_interaction=prev,
        last_event_time=event,
    )
    # decay = 0.5^(14/7) = 0.25 → raw = 100*0.25 + 10 = 35
    assert raw == pytest.approx(35.0)


def test_one_day_decay():
    """1 day elapsed → decay_factor = 0.5^(1/7)."""
    prev = T0
    event = T0 + datetime.timedelta(days=1)
    expected_decay = 0.5 ** (1.0 / HALF_LIFE_DAYS)

    raw, _ = compute_incremental_score(
        current_raw=50.0,
        incoming_points=5.0,
        prev_interaction=prev,
        last_event_time=event,
    )
    assert raw == pytest.approx(50.0 * expected_decay + 5.0)


# --- Normalization ---

def test_normalization_bounds():
    """Interest score is always in (0, 1) for positive raw."""
    _, interest_low = compute_incremental_score(0.0, 0.001, None, T0)
    _, interest_high = compute_incremental_score(0.0, 100000.0, None, T0)

    assert 0 < interest_low < 1
    assert 0 < interest_high < 1
    assert interest_high > interest_low


def test_normalization_at_k_factor():
    """When raw == K, interest should be exactly 0.5."""
    raw, interest = compute_incremental_score(0.0, SCORING_K_FACTOR, None, T0)
    assert raw == pytest.approx(SCORING_K_FACTOR)
    assert interest == pytest.approx(0.5)


# --- Edge cases ---

def test_timezone_naive_prev_interaction():
    """Timezone-naive prev_interaction should be treated as UTC."""
    naive_prev = datetime.datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo
    event = T0 + datetime.timedelta(days=7)

    raw, _ = compute_incremental_score(
        current_raw=100.0,
        incoming_points=0.0,
        prev_interaction=naive_prev,
        last_event_time=event,
    )
    # Should still apply correct 7-day decay
    assert raw == pytest.approx(50.0)


def test_zero_current_raw_with_prev_interaction():
    """current_raw=0 skips decay even if prev_interaction exists."""
    raw, interest = compute_incremental_score(
        current_raw=0.0,
        incoming_points=10.0,
        prev_interaction=T0,
        last_event_time=T0 + datetime.timedelta(days=30),
    )
    # current_raw=0 → goes to else branch → raw = incoming_points
    assert raw == 10.0
    assert interest == pytest.approx(10.0 / (10.0 + SCORING_K_FACTOR))


def test_negative_time_diff_clamped():
    """If event_time < prev_interaction (clock skew), days_elapsed is clamped to 0."""
    prev = T0 + datetime.timedelta(hours=1)
    event = T0  # earlier than prev

    raw, _ = compute_incremental_score(
        current_raw=100.0,
        incoming_points=5.0,
        prev_interaction=prev,
        last_event_time=event,
    )
    # days_elapsed = max(negative, 0) = 0 → decay = 1.0 → raw = 100 + 5
    assert raw == pytest.approx(105.0)


def test_zero_incoming_points():
    """Zero incoming points: only decay is applied."""
    raw, _ = compute_incremental_score(
        current_raw=80.0,
        incoming_points=0.0,
        prev_interaction=T0,
        last_event_time=T0 + datetime.timedelta(days=7),
    )
    assert raw == pytest.approx(40.0)

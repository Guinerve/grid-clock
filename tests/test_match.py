import numpy as np
import pytest
from scipy.ndimage import gaussian_filter1d

from grid_clock.match import InsufficientHumError, match_traces
from grid_clock.trace import FrequencyTrace, TraceConfig


def make_trace(frequency, valid=None):
    frequency = np.asarray(frequency, dtype=float)
    valid = np.ones(frequency.size, dtype=bool) if valid is None else valid
    return FrequencyTrace(
        np.arange(frequency.size, dtype=float) + 8,
        np.where(valid, frequency, np.nan),
        np.full(frequency.size, 30.0),
        valid,
        TraceConfig(),
    )


def test_recovers_offset_with_b_starting_later_and_ignores_invalid_frames():
    drift = 50 + gaussian_filter1d(np.random.default_rng(7).normal(0, 0.07, 700), 4)
    valid = np.ones(420, dtype=bool)
    valid[70:80] = False
    result = match_traces(make_trace(drift[:600]), make_trace(drift[37:457], valid))
    assert result.offset_s == 37
    assert result.correlation > 0.999
    assert result.accepted
    assert result.valid_overlap_s == 410


def test_recovers_negative_offset_when_a_starts_later():
    drift = 50 + gaussian_filter1d(np.random.default_rng(11).normal(0, 0.07, 700), 4)
    result = match_traces(make_trace(drift[42:642]), make_trace(drift[:520]))
    assert result.offset_s == -42
    assert result.accepted


def test_does_not_accept_unrelated_frequency_patterns():
    rng = np.random.default_rng(99)
    a = 50 + gaussian_filter1d(rng.normal(0, 0.1, 600), 4)
    b = 50 + gaussian_filter1d(rng.normal(0, 0.1, 600), 4)
    result = match_traces(make_trace(a), make_trace(b))
    assert not result.accepted
    assert result.correlation < 0.9


def test_repeating_drift_is_ambiguous():
    drift = 50 + 0.04 * np.sin(2 * np.pi * np.arange(600) / 40)
    result = match_traces(make_trace(drift), make_trace(drift))
    assert not result.accepted
    assert "ambiguous" in result.reason


def test_bounded_search_does_not_claim_a_distinct_peak_without_competitors():
    drift = 50 + 0.04 * np.sin(2 * np.pi * np.arange(300) / 40)
    result = match_traces(make_trace(drift), make_trace(drift), max_offset_s=0)
    assert result.accepted
    assert result.competing_correlation is None
    assert "No competing offset" in result.reason
    assert "distinct" not in result.reason.lower()


@pytest.mark.parametrize("frequency", [np.full(100, 50.0), np.full(100, np.nan)])
def test_constant_or_missing_hum_cannot_establish_an_offset(frequency):
    with pytest.raises(ValueError, match="Not enough valid, changing hum"):
        match_traces(make_trace(frequency), make_trace(frequency))


def test_respects_search_range_and_minimum_overlap():
    rng = np.random.default_rng(2)
    drift = 50 + gaussian_filter1d(rng.normal(0, 0.1, 700), 4)
    a, b = make_trace(drift[:500]), make_trace(drift[80:580])
    result = match_traces(a, b, max_offset_s=20)
    assert abs(result.offset_s) <= 20
    assert not result.accepted
    assert match_traces(a, b).offset_s == 80
    with pytest.raises(InsufficientHumError, match="Not enough"):
        match_traces(a, b, min_overlap_s=550)

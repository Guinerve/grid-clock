"""Compare frequency drift, not carrier phase or audio content."""

from dataclasses import dataclass

import numpy as np
from scipy import signal

from grid_clock.trace import FrequencyTrace

# Chosen on the odd-numbered ENF-WHU clips and checked on the even-numbered ones.
# See docs/validation.md. They are screening heuristics, not confidence levels.
MIN_OVERLAP_S = 300
MIN_CORRELATION = 0.97
MIN_PEAK_MARGIN = 0.05
MIN_DRIFT_STD_HZ = 0.002
MIN_VALID_FRACTION = 0.8


class InsufficientHumError(ValueError):
    """Valid input that lacks enough paired, changing hum to score any offset."""


@dataclass(frozen=True)
class MatchResult:
    offset_s: float
    correlation: float
    valid_overlap_s: float
    competing_correlation: float | None
    accepted: bool
    reason: str


def match_traces(
    a: FrequencyTrace,
    b: FrequencyTrace,
    *,
    min_overlap_s: float = MIN_OVERLAP_S,
    max_offset_s: float | None = None,
    min_correlation: float = MIN_CORRELATION,
    min_peak_margin: float = MIN_PEAK_MARGIN,
) -> MatchResult:
    """Positive offset means B started later than A.

    Compute Pearson correlation separately at each lag, using only paired
    valid estimates. Require 80% valid coverage and >= 0.002 Hz standard
    deviation on both sides. Compare competing lags beyond one window length.
    Short overlaps of slowly drifting hum correlate by chance, so the default
    overlap is five minutes. Thresholds are heuristics, not confidence levels.
    """
    if a.config.nominal_hz != b.config.nominal_hz:
        raise ValueError("Traces must use the same nominal grid frequency.")
    hop = a.config.hop_s
    if hop != b.config.hop_s or a.config.window_s != b.config.window_s:
        raise ValueError("Traces must use the same window and hop settings.")
    if not np.isfinite(min_overlap_s) or min_overlap_s <= 0:
        raise ValueError("Minimum overlap must be positive and finite.")
    if max_offset_s is not None and (not np.isfinite(max_offset_s) or max_offset_s < 0):
        raise ValueError("Maximum offset must be non-negative and finite.")
    if not 0 <= min_correlation <= 1 or not 0 <= min_peak_margin <= 2:
        raise ValueError("Invalid correlation or peak-margin threshold.")
    if a.time_s.size < 2 or b.time_s.size < 2:
        raise InsufficientHumError("Not enough trace frames to compare.")
    for trace in (a, b):
        if not np.allclose(np.diff(trace.time_s), hop, rtol=0, atol=1e-8):
            raise ValueError("Trace timestamps must have the configured regular hop.")
    mask_a = (a.valid & np.isfinite(a.frequency_hz)).astype(float)
    mask_b = (b.valid & np.isfinite(b.frequency_hz)).astype(float)
    x = np.where(mask_a, a.frequency_hz - a.config.nominal_hz, 0)
    y = np.where(mask_b, b.frequency_hz - b.config.nominal_hz, 0)

    def correlate(left, right):
        return signal.correlate(left, right, mode="full", method="fft")

    count = np.rint(correlate(mask_a, mask_b))
    possible = np.rint(correlate(np.ones_like(x), np.ones_like(y)))
    safe_count = np.maximum(count, 1)
    sum_x = correlate(x, mask_b)
    sum_y = correlate(mask_a, y)
    variance_x = np.maximum(correlate(x * x, mask_b) - sum_x**2 / safe_count, 0)
    variance_y = np.maximum(correlate(mask_a, y * y) - sum_y**2 / safe_count, 0)
    covariance = correlate(x, y) - sum_x * sum_y / safe_count
    denominator = np.sqrt(variance_x * variance_y)
    scores = np.divide(
        covariance,
        denominator,
        out=np.zeros_like(covariance),
        where=denominator > 0,
    )
    scores = np.clip(scores, -1, 1)
    offsets = signal.correlation_lags(x.size, y.size) * hop + a.time_s[0] - b.time_s[0]
    eligible = (
        (count * hop >= min_overlap_s)
        & (count >= MIN_VALID_FRACTION * possible)
        & (variance_x / safe_count >= MIN_DRIFT_STD_HZ**2)
        & (variance_y / safe_count >= MIN_DRIFT_STD_HZ**2)
    )
    if max_offset_s is not None:
        eligible &= np.abs(offsets) <= max_offset_s
    if not np.any(eligible):
        raise InsufficientHumError(
            "Not enough valid, changing hum for the required overlap and offset range."
        )
    best = int(np.argmax(np.where(eligible, scores, -np.inf)))
    competitors = eligible & (np.abs(offsets - offsets[best]) > a.config.window_s)
    competing = float(np.max(scores[competitors])) if np.any(competitors) else None
    accepted = scores[best] >= min_correlation and (
        competing is None or scores[best] - competing >= min_peak_margin
    )
    if scores[best] < min_correlation:
        reason = "The best correlation is below the threshold."
    elif not accepted:
        reason = "Another offset has a similar score; the result is ambiguous."
    elif competing is None:
        reason = (
            "Correlation passed. No competing offset was eligible in the search range; "
            "uniqueness was not assessed."
        )
    else:
        reason = "A distinct correlation peak passed within the eligible search range."
    return MatchResult(
        float(offsets[best]),
        float(scores[best]),
        float(count[best] * hop),
        competing,
        bool(accepted),
        reason,
    )

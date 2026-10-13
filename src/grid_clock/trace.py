"""Track the strongest narrow-band ENF candidate in each audio window."""

from dataclasses import dataclass
from math import gcd

import numpy as np
from numpy.typing import NDArray
from scipy import fft, signal


@dataclass(frozen=True)
class TraceConfig:
    nominal_hz: float = 50.0
    harmonic: int = 1
    window_s: float = 16.0
    hop_s: float = 1.0
    min_strength_db: float = 20.0

    def __post_init__(self):
        values = (self.nominal_hz, self.window_s, self.hop_s, self.min_strength_db)
        if not all(np.isfinite(values)):
            raise ValueError("Trace settings must be finite.")
        if self.nominal_hz not in (50, 60) or self.harmonic not in (1, 2):
            raise ValueError("Use a 50 or 60 Hz grid and harmonic 1 or 2.")
        if self.window_s < 4 or not 0 < self.hop_s <= self.window_s:
            raise ValueError(
                "Window must be at least 4 s. Hop must be above 0 and no longer than the window."
            )
        if self.min_strength_db < 0:
            raise ValueError("Minimum strength must be 0 dB or more.")
        for value in (self.window_s, self.hop_s):
            if value > np.iinfo(np.int64).max / 500:
                raise ValueError("Window and hop are too large to handle.")
            if not np.isclose(value * 500, round(value * 500), rtol=0, atol=1e-8):
                raise ValueError("Window and hop must be multiples of 0.002 s.")


@dataclass(frozen=True)
class FrequencyTrace:
    time_s: NDArray[np.float64]
    frequency_hz: NDArray[np.float64]
    strength_db: NDArray[np.float64]
    valid: NDArray[np.bool_]
    config: TraceConfig


def extract_trace(
    samples: NDArray[np.float64], sample_rate: int, config: TraceConfig | None = None
) -> FrequencyTrace:
    """Return grid-frequency estimates, even when tracking harmonic 2.

    Strength is peak power / median nearby noise power in dB. It is a
    screening metric, not a probability or proof that a tone comes from the grid.
    Invalid frequency estimates are NaN. Timestamps are window centres.
    """
    config = config or TraceConfig()
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim != 1 or not samples.size or not np.all(np.isfinite(samples)):
        raise ValueError("Audio must be one channel of finite samples, and not empty.")
    centre = config.nominal_hz * config.harmonic
    if not isinstance(sample_rate, (int, np.integer)) or sample_rate <= 2 * (centre + 2):
        raise ValueError("Sample rate is too low for the selected hum band.")
    if samples.size < round(config.window_s * sample_rate):
        raise ValueError(f"Audio must contain at least {config.window_s:g} seconds.")

    analysis_rate = 500
    divisor = gcd(sample_rate, analysis_rate)
    audio = signal.resample_poly(samples, analysis_rate // divisor, sample_rate // divisor)
    window = round(config.window_s * analysis_rate)
    hop = round(config.hop_s * analysis_rate)
    if hop < 1:
        raise ValueError("Hop is too short for the 500 Hz analysis sample rate.")
    sos = signal.butter(
        4,
        [centre - 1.25 * config.harmonic, centre + 1.25 * config.harmonic],
        btype="bandpass",
        fs=analysis_rate,
        output="sos",
    )
    filtered = signal.sosfiltfilt(sos, audio)
    nfft = 1 << (window * 8 - 1).bit_length()
    frequencies = fft.rfftfreq(nfft, 1 / analysis_rate)
    frames = np.lib.stride_tricks.sliding_window_view(filtered, window)[::hop]
    times = (np.arange(frames.shape[0]) * hop + window / 2) / analysis_rate
    taper = signal.windows.hann(window, sym=False)
    distance = np.abs(frequencies - centre) / config.harmonic
    candidates = np.flatnonzero(distance <= 0.2)
    noise_bins = (distance >= 0.35) & (distance <= 0.9)
    tiny = np.finfo(float).tiny
    estimates = np.empty(times.size)
    strength = np.empty(times.size)
    valid = np.empty(times.size, dtype=bool)
    # Bound FFT memory independently of recording length. The frames are views.
    for start in range(0, times.size, 32):
        stop = min(start + 32, times.size)
        spectrum = fft.rfft(frames[start:stop] * taper, n=nfft, axis=1).T / taper.sum()
        power = np.abs(spectrum) ** 2
        columns = np.arange(stop - start)
        peaks = candidates[np.argmax(power[candidates], axis=0)]
        left, mid, right = (
            np.log(np.maximum(power[peaks + shift, columns], tiny)) for shift in (-1, 0, 1)
        )
        curvature = left - 2 * mid + right
        delta = np.divide(
            0.5 * (left - right),
            curvature,
            out=np.zeros_like(mid),
            where=curvature < -1e-12,
        )
        delta = np.clip(delta, -0.5, 0.5)
        estimates[start:stop] = (
            frequencies[peaks] + delta * analysis_rate / nfft
        ) / config.harmonic
        peak_power = power[peaks, columns]
        noise_power = np.median(power[noise_bins], axis=0)
        strength[start:stop] = 10 * np.log10(
            np.maximum(peak_power, tiny) / np.maximum(noise_power, tiny),
        )
        valid[start:stop] = (
            (strength[start:stop] >= config.min_strength_db)
            & (peak_power > tiny)
            & (peaks > candidates[0])
            & (peaks < candidates[-1])
        )
    return FrequencyTrace(times, np.where(valid, estimates, np.nan), strength, valid, config)

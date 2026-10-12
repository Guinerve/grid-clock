"""Deterministic audio fixtures. These are not recordings of the power grid."""

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.ndimage import gaussian_filter1d

DEMO_OFFSET_S = 37


def create_demo(directory: Path, *, force: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Write two independently noisy hum clips and return the shared drift truth."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("a.wav", "b.wav"):
        path = directory / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"Demo destination must be a regular file: {path}")
        if path.exists() and not force:
            raise ValueError(f"Demo audio already exists: {path}. Use --force to replace it.")
    rng = np.random.default_rng(20261012)
    reference_times = np.arange(301, dtype=float)
    drift = gaussian_filter1d(rng.normal(0, 0.1, reference_times.size), 10)
    reference_frequency = 50 + drift - np.mean(drift)
    rate = 2000
    for name, start, phase_offset in [("a.wav", 0, 0), ("b.wav", DEMO_OFFSET_S, 1.7)]:
        times = start + np.arange(240 * rate) / rate
        frequency = np.interp(times, reference_times, reference_frequency)
        phase = phase_offset + 2 * np.pi * np.cumsum(frequency) / rate
        samples = 0.3 * np.sin(phase) + rng.normal(0, 0.5, times.size)
        sf.write(directory / name, samples, rate, subtype="FLOAT")
    return reference_times, reference_frequency

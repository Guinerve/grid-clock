import numpy as np
import pytest

from grid_clock.trace import TraceConfig, extract_trace


def test_recovers_known_drift_buried_in_noise():
    sample_rate = 2000
    time = np.arange(120 * sample_rate) / sample_rate
    frequency = 50 + 0.04 * np.sin(2 * np.pi * time / 90)
    phase = 2 * np.pi * np.cumsum(frequency) / sample_rate
    noise = np.random.default_rng(12).normal(0, 0.6, time.size)
    audio = 0.2 * np.sin(phase) + noise

    trace = extract_trace(audio, sample_rate, TraceConfig())

    expected = 50 + 0.04 * np.sin(2 * np.pi * trace.time_s / 90)
    assert np.max(np.abs(trace.frequency_hz - expected)) < 0.005
    assert np.mean(trace.valid) > 0.95
    assert trace.time_s[0] == 8
    assert trace.time_s[-1] == 112


@pytest.mark.parametrize("kind", ["silence", "noise"])
def test_rejects_audio_without_a_clear_hum(kind):
    samples = np.zeros(40 * 1000)
    if kind == "noise":
        samples = np.random.default_rng(3).normal(0, 1, samples.size)
    trace = extract_trace(samples, 1000)
    assert not np.any(trace.valid)
    assert np.all(np.isnan(trace.frequency_hz))


def test_reports_grid_frequency_when_tracking_the_second_harmonic():
    rate = 1000
    time = np.arange(90 * rate) / rate
    frequency = 60 + 0.035 * np.sin(2 * np.pi * time / 80)
    phase = 2 * np.pi * np.cumsum(2 * frequency) / rate
    trace = extract_trace(np.sin(phase), rate, TraceConfig(nominal_hz=60, harmonic=2))
    expected = 60 + 0.035 * np.sin(2 * np.pi * trace.time_s / 80)
    assert np.all(trace.valid)
    assert np.max(np.abs(trace.frequency_hz - expected)) < 0.005


@pytest.mark.parametrize(
    ("samples", "rate"),
    [(np.ones(100), 1000), (np.array([np.nan] * 20000), 1000), (np.ones(20000), 50)],
)
def test_rejects_invalid_audio(samples, rate):
    with pytest.raises(ValueError):
        extract_trace(samples, rate)


@pytest.mark.parametrize("rate", [44100, 48000])
def test_extracts_hum_at_microphone_sample_rates(rate):
    time = np.arange(30 * rate) / rate
    samples = 0.1 * np.sin(2 * np.pi * 50.035 * time)
    samples += 0.5 * np.sin(2 * np.pi * 450 * time)
    trace = extract_trace(samples, rate)
    assert np.all(trace.valid)
    assert np.max(np.abs(trace.frequency_hz - 50.035)) < 0.001

# grid-clock

> Compare audio recordings through the hum of the power grid.

[![Tests](https://github.com/Guinerve/grid-clock/actions/workflows/ci.yml/badge.svg)](https://github.com/Guinerve/grid-clock/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

![Two synthetic hum traces aligned at a known 37-second offset](assets/synthetic-match.png)

**Status:** v0.1 implemented; synthetic tests pass. Real-recording validation is pending.

Mains-powered devices can produce a faint 50 Hz hum in microphone recordings.
Grid frequency changes over time. Recordings from the same synchronous grid can
share that frequency pattern. This technique is called Electrical Network
Frequency (ENF) analysis.

`grid-clock` extracts the pattern and estimates the relative start time of two
clips. It does not give an absolute timestamp. That needs a dated reference log.

## Safety

Use acoustic or electromagnetic pickup from normal, enclosed equipment only.
A laptop on its charger, a fridge, or a desk lamp may produce usable hum.
**Never connect a microphone, probe, cable, or circuit directly to mains.**

## Run the demo

Install [uv](https://docs.astral.sh/uv/). Use Python 3.11 or later.
Clone the repository and run the demo:

```bash
git clone https://github.com/Guinerve/grid-clock.git
cd grid-clock
uv run grid-clock demo
```

`uv` installs the Python dependencies on the first run. The synthetic demo does
not need `ffmpeg`, a microphone, or a reference dataset.

This creates two four-minute synthetic WAV clips with independent noise.
Clip B starts 37 seconds after clip A. The command extracts both traces and
writes these files to `output/demo/`:

- `a.wav`, `b.wav`: generated audio, not real grid recordings.
- `a.trace.csv`, `b.trace.csv`: frequency, strength, and valid-frame flags.
- `match.png`: aligned traces and their signal strength.
- `match.json`: measured offset, scores, settings, and known synthetic truth.

The command prints JSON. In the local test run, it recovered `+37 s` with a
correlation of `0.9942`. The largest frequency error across both clips was
`0.00206 Hz`. These results apply to the fixed synthetic fixture only.

Open `output/demo/match.png` to view the result. To replace existing demo audio,
run `uv run grid-clock demo --force`. Without `--force`, the demo refuses to
overwrite `a.wav` or `b.wav`. Use `--output <directory>` for a separate run.

## Use your own recordings

```bash
uv run grid-clock trace clip.wav --output output/clip
uv run grid-clock match a.wav b.wav --output output/pair
```

`trace` writes `trace.csv`, `trace.png`, and `summary.json`.
When a candidate can be scored, `match` writes `a.trace.csv`, `b.trace.csv`,
`match.png`, and `match.json`. This includes candidates rejected by the screening
thresholds. An output directory can be changed with `--output`.
Repeating `trace` or `match` replaces its generated files in that directory.
An input or matching error can leave files from a previous run unchanged.
Check the exit code before using output files.

WAV and FLAC use `soundfile`. M4A/AAC and other unsupported formats need
`ffmpeg` on `PATH`. Install it separately if needed.

For example, use `brew install ffmpeg` on macOS, or
`sudo apt-get install ffmpeg` on Debian/Ubuntu.

If the 50 Hz fundamental is weak, try the 100 Hz harmonic:

```bash
uv run grid-clock trace clip.wav --harmonic 2 --output output/harmonic
```

Use `--nominal 60` for a 60 Hz grid. Use `--channel 1` to select the second audio
channel. By default, the loader selects the channel with the highest RMS level.
It does not average channels because opposite-phase hum could cancel.
The loudest channel is not always the one with the clearest hum. Use `trace`
with each channel if the default produces few valid frames.

For a bounded offset search, run:

```bash
uv run grid-clock match a.wav b.wav --max-offset 90 --min-overlap 60
```

A positive offset means B started later than A. For example, `+37` means
`a[37 seconds]` aligns with `b[0 seconds]`. The offset resolution is the trace
hop, which is one second by default.

Use at least 16 seconds of audio for a trace. Matching needs at least 60 valid
paired trace frames by default, so each clip needs at least 75 seconds of audio
even at zero offset. Record several minutes to allow overlap after alignment.

| Option | Default | Meaning |
| --- | --- | --- |
| `--nominal` | `50` | Grid frequency: `50` or `60` Hz |
| `--harmonic` | `1` | Track the fundamental (`1`) or second harmonic (`2`) |
| `--window` | `16` | Analysis window in seconds; minimum `4` |
| `--hop` | `1` | Trace step in seconds; positive and no larger than the window |
| `--min-strength` | `20` | Minimum peak-to-nearby-noise ratio in dB |
| `--channel` | Highest RMS | Zero-based audio channel; applies to both clips in `match` |
| `--min-overlap` | `60` | Minimum valid paired seconds; `match` only |
| `--max-offset` | Full range | Search within ±this many seconds; `match` only |

Window and hop values must be multiples of 0.002 seconds. Trace options apply
to `trace` and `match`; `demo` uses fixed settings.

Exit codes: `0` means usable trace frames or an accepted candidate match;
`1` means no usable trace frames or a rejected candidate match;
`2` means invalid input, a decode failure, or insufficient changing hum to compare.
Run `uv run grid-clock --help` for the command list.

## How it works

1. Decode one audio channel and resample it to 500 Hz with anti-alias filtering.
2. Band-pass around the selected fundamental or second harmonic.
3. Apply a Hann-window STFT with 16-second windows and one-second steps.
   Compute FFTs in small batches to bound spectral memory use.
4. Search within ±0.2 Hz of the nominal grid frequency. Use a zero-padded FFT
   and quadratic interpolation of log power to estimate the peak.
5. Divide harmonic estimates by the harmonic number. Report the grid frequency,
   not the 100/120 Hz carrier frequency. Trace times are window centres.
6. Screen each frame with the peak-to-nearby-noise power ratio. The default
   cutoff is 20 dB. Invalid frequency values are blank in CSV output.
7. Compare traces with overlap-normalised Pearson correlation at each offset.
   Missing frames do not contribute to the score.

Matching requires at least 60 paired valid frames at the default hop, 80% valid
coverage in the overlap, and at least 0.002 Hz drift standard deviation in each
trace. An accepted candidate needs correlation ≥0.9. Its score must exceed the
best competing offset outside one window length by at least 0.05.
`valid_overlap_s` is the paired valid frame count multiplied by the hop.
Acceptance applies only within the eligible search range. If no competing
offset is eligible, `competing_correlation` is `null` and the result states that
uniqueness was not assessed. A restricted search can hide other plausible offsets.

The strength band in the plot is a signal-screening aid. It is not an error band
or a confidence probability. Adjacent windows overlap and are not independent.
The match thresholds are heuristics, not forensic confidence levels.

## Stack

Python (uv), NumPy, SciPy, soundfile, matplotlib, pytest.
The CLI uses `argparse`. Plots use a headless backend; no web server is needed.

## Checks

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
```

Tests cover known drift buried
in noise, the second harmonic on a 60 Hz grid, silence, noise-only audio,
positive and negative offsets, missing frames, unrelated traces, periodic
ambiguity, stereo channel selection, CLI artifacts, and actual M4A decoding.
They also cover 44.1/48 kHz resampling, overwrite protection, invalid settings,
restricted searches, and unsuccessful match exit codes.
The M4A test is skipped when `ffmpeg` is absent. The noisy sinusoidal drift test
requires a maximum frequency error below 0.005 Hz.

`.github/workflows/ci.yml` runs lint, formatting, tests, and the demo on
Python 3.11–3.13. It retains demo artifacts. The badge above links to the latest run.

## How I know it's right

- Synthetic extraction and known-offset tests pass. See the measured demo result above.
- Real simultaneous recordings have not been tested. Record at least five minutes
  near enclosed appliances in two locations. Log their start times independently.
  Compare the measured offset with that log.
- A different-time recording is still needed as a real negative control.
- A Tasmania or WA recording could test a different synchronous grid against a
  mainland recording. This experiment has not been done. Do not treat a low score
  as proof of origin or a high score as proof that two recordings share a time.

## Limits

- Recordings need detectable hum. Many microphones remove low frequencies.
  Battery-powered recordings may have no usable signal.
- A constant tone gives no time fingerprint. An unrelated device oscillator can
  resemble hum. Strong tones are not proof of grid origin.
- Long windows smooth fast changes. The one-second hop does not give independent
  one-second frequency measurements.
- Repeating patterns can yield several plausible offsets. A high score alone
  does not establish a match. Searching many offsets can produce false matches.
- Compression, noise, local interference, and sample-clock drift can reduce
  accuracy. Clock-drift correction and automatic harmonic fusion are not implemented.
- Files are decoded into memory. FFT batching limits spectral memory, not audio
  file memory. This version is not a streaming recorder.
- Absolute timestamps need a dated reference log. This version has no reference
  data source and has not been validated for forensic use.

## Next steps

- Validate simultaneous recordings from two locations and a different-time control.
- Measure sensitivity to compression, interference, and sample-clock drift.
- Check whether a dated reference source, such as AEMO data, has sufficient
  resolution and coverage for absolute-time matching.

## Contributing

Use the checks above before opening a pull request. For a bug report, include
the command, Python version, audio format, sample rate, and error output.
Use a synthetic reproducer when possible. Do not upload private recordings.

## Licence

A licence has not been selected. This repository does not yet grant an
open-source licence for reuse or redistribution.

# grid-clock

> Line up audio recordings in time using the hum of the power grid.

[![Tests](https://github.com/Guinerve/grid-clock/actions/workflows/ci.yml/badge.svg)](https://github.com/Guinerve/grid-clock/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

![A real phone recording aligned with a mains frequency log made at the same time](assets/real-match.png)

*A real phone clip from the public ENF-WHU dataset (purple) against a direct
mains log made at the same time (green). grid-clock found the offset at 0 s
with r = 0.9998.*

Equipment on mains power can leave a faint hum in a microphone recording. The
grid frequency drifts a little all the time. Recordings made at the same time
on the same grid can share that drift. Reading time from the drift is called
Electrical Network Frequency (ENF) analysis.

I built grid-clock to find out if the hum in ordinary phone recordings is
enough to line up two clips. The tool extracts the drift pattern from
each clip and estimates how many seconds apart they started. It gives a
relative offset only. It cannot give a clock time, because that needs a dated
reference log, and none is integrated or tested.

**Status:** version 0.2. I tested it on 130 real phone and recorder clips. The
test with two microphones in two places is not done yet.

## Safety

Record the sound of normal, enclosed equipment only. A laptop on its charger,
a fridge or a desk lamp can give usable hum.
**Never connect a microphone, probe, cable or circuit directly to mains.**

## Run the demo

Install [uv](https://docs.astral.sh/uv/). You need Python 3.11 or later.

```bash
git clone https://github.com/Guinerve/grid-clock.git
cd grid-clock
uv run grid-clock demo
```

On the first run, `uv` installs the dependencies. The demo does not need
`ffmpeg`, a microphone or a dataset.

The demo makes two synthetic WAV clips, each 7 minutes long, with separate
noise. Clip B starts 37 seconds after clip A. The command writes these files
to `output/demo/`:

- `a.wav`, `b.wav`: generated audio. These are not grid recordings.
- `a.trace.csv`, `b.trace.csv`: frequency, strength and a valid flag per frame.
- `match.png`: the aligned traces and their signal strength.
- `match.json`: the measured offset, scores, settings and the known true offset.

It finds `+37 s` with a correlation of `0.9978`. The largest frequency error
is `0.0025 Hz`. Add `--force` to replace the demo audio, or use
`--output <directory>`.

![Two synthetic hum traces aligned at a known offset of 37 seconds](assets/synthetic-match.png)

## Use your own recordings

```bash
uv run grid-clock trace clip.wav --harmonic 2 --output output/clip
uv run grid-clock match a.m4a b.m4a --harmonic 2 --output output/pair
```

`trace` writes `trace.csv`, `trace.png` and `summary.json`. When at least one
offset can be scored, `match` writes `a.trace.csv`, `b.trace.csv`, `match.png`
and `match.json`. It writes them for rejected matches too. A new run replaces
the files in the output folder. A failed run can leave old files there, so
check the exit code.

**Start with `--harmonic 2`.** Phone microphones usually filter out 50 Hz. In
the benchmark on real recordings, the 100 Hz harmonic gave usable traces and
50 Hz gave none. Use `--nominal 60` on a 60 Hz grid.

**Record for at least 8 minutes.** By default a match needs 300 s of valid
hum that both clips share. At the default settings, each clip must be at least
315 s long, even when both start together. Shorter overlaps gave many false matches on real data.

WAV and FLAC load through `soundfile`. M4A, AAC and other formats need
`ffmpeg` on your `PATH`. Install it with `brew install ffmpeg` or
`sudo apt-get install ffmpeg`.

The loader uses the channel with the highest RMS level. It does not average
the channels, because hum in opposite phase would cancel out. Add
`--channel 1` to use the second channel.

A positive offset means B started later than A. For example, `+37` means
`a[37 s]` lines up with `b[0 s]`. The offset is in steps of the trace hop,
which is one second by default.

| Option | Default | Meaning |
| --- | --- | --- |
| `--nominal` | `50` | Grid frequency: `50` or `60` Hz |
| `--harmonic` | `1` | Track the fundamental (`1`) or the second harmonic (`2`) |
| `--window` | `16` | Analysis window in seconds; at least `4` |
| `--hop` | `1` | Trace step in seconds; above 0 and no longer than the window |
| `--min-strength` | `20` | Lowest ratio of peak to nearby noise, in dB |
| `--channel` | Highest RMS | Audio channel, counting from 0; used for every clip |
| `--min-overlap` | `300` | Valid seconds that both clips must share; `match` and `validate` |
| `--max-offset` | Full range | Search only within ± this many seconds; `match` and `validate` |

Window and hop must be multiples of 0.002 s. `demo` uses fixed settings.

Exit codes:

- `0`: the trace has usable frames, the match is accepted, or the validation passed.
- `1`: the trace has no usable frames, the match is rejected, or the validation failed.
- `2`: bad input, a decode failure, or not enough changing hum to compare.

## Test in two places

`grid-clock validate` checks the matcher against start times that people
wrote down themselves. List the recordings in a JSON manifest:

```json
{
  "recordings": [
    {"id": "home", "path": "home.m4a", "location": "home",
     "logged_start": "2026-10-18T19:00:04+11:00", "start_uncertainty_s": 2},
    {"id": "office", "path": "office.m4a", "location": "office",
     "logged_start": "2026-10-18T19:00:31+11:00", "start_uncertainty_s": 2},
    {"id": "control", "path": "control.m4a", "location": "home",
     "logged_start": "2026-10-19T08:15:00+11:00", "start_uncertainty_s": 2}
  ]
}
```

```bash
uv run grid-clock validate manifest.json --harmonic 2 --output output/two-location
```

When two logged recordings overlap in time, the tool scores the measured
offset against the logged difference. Pairs logged at different times are
negative controls. The tool writes offset errors and false matches to
`validation.json` and `pairs.csv`. It uses the logged times only as
differences and never writes them out.

The recording steps are in
[docs/two-location-protocol.md](docs/two-location-protocol.md). A full example
manifest is in
[examples/two-location.manifest.json](examples/two-location.manifest.json).

## Validation

All details and commands are in [docs/validation.md](docs/validation.md).

**Real recordings.** The public [ENF-WHU](https://github.com/ghua-ac/ENF-WHU-Dataset)
dataset has 130 phone and recorder clips. Each one has a mains frequency log
made at the same time. Clips from different days act as negative controls. I
chose the thresholds on the odd numbered clips and then checked them on the
even numbered clips.

| Test (100 Hz harmonic) | Result |
| --- | --- |
| Clip against its mains log | 44 of 130 correct, 0 wrong offsets, 82 too weak to score |
| Offset error of accepted pairs | median 2 s, max 4 s |
| Held out half only | 20 of 65 correct, 0 wrong offsets |
| Controls from different days | 0 false matches in 6,598 scored pairs |
| Clip searched across a full day's log (24 hours) | 41 of 113 found within 4 s, 0 wrong offsets |
| 50 Hz fundamental | 0 of 130 clips usable |

Version 0.1 needed only a 60 s overlap and r ≥ 0.9. On the same data it
accepted 1,815 of 7,495 scored controls from different days. Version 0.2 needs
300 s and r ≥ 0.97.

**Not tested yet.** Two microphone recordings made at the same time in two
places. Every ENF-WHU pair compares a microphone with a direct mains log. All
clips come from one city on one grid.

**Synthetic tests.** `uv run pytest` checks known drift in noise, both
harmonics, and 50 and 60 Hz grids. It also checks positive and negative
offsets, missing frames, unrelated and repeating traces, M4A decoding, the
manifest checks and the scoring rules.

## How it works

1. Decode one audio channel. Resample it to 500 Hz with an anti aliasing filter.
2. Apply a band pass filter around the fundamental or the second harmonic.
3. Run a short time Fourier transform with a Hann window. Windows are 16 s
   long and move 1 s at a time. Frames go in small batches to limit memory.
4. Search within ±0.2 Hz of the nominal frequency. Find the peak with a zero
   padded FFT and quadratic interpolation of the log power.
5. Divide harmonic estimates by the harmonic number, so every trace shows the
   grid frequency. Trace times are the window centres.
6. Mark a frame valid when the ratio of its peak to nearby noise is at least
   20 dB. Invalid frequencies are blank in the CSV output.
7. At every offset, compute the Pearson correlation over the frames that are
   valid in both clips.

An offset is eligible when it has:

- at least 300 s of frames that are valid in both clips,
- valid frames over at least 80% of the overlap, and
- a drift standard deviation of at least 0.002 Hz in each clip.

The best eligible offset is accepted when r ≥ 0.97. It must also beat the best
competitor by at least 0.05. Competitors are offsets more than one window away.
If no competitor is eligible, `competing_correlation` is `null` and the result
says that uniqueness was not checked. A small `--max-offset` can hide other
likely offsets.

The strength band in the plot helps you screen a clip. It is not an error band
or a probability. Windows next to each other overlap, so they are not
independent. The thresholds are rules of thumb, not forensic confidence levels.

## Limits

- Recordings need hum that the tool can detect. Many microphones remove low
  frequencies, and setups on battery power may pick up nothing. Most real clips were
  too weak to score.
- A constant tone carries no time information. An unrelated oscillator can look
  like hum, so a strong tone does not prove that it comes from the grid.
- Repeating or slowly drifting patterns can give several likely offsets.
  Searching more offsets raises the chance of a false match.
- Compression, noise, local interference and drift in the recorder's sample
  clock reduce accuracy. The tool does not correct clock drift or combine
  harmonics.
- The whole file is decoded into memory. This is not a streaming recorder.
- No dated reference source is integrated, so the tool gives no clock times.
  Nothing here is validated for forensic use.

## Roadmap

- Run the test with two microphones in two places, with a control recorded at a
  different time.
- Measure how compression, interference and sample clock drift change the
  results.
- Check if a dated public frequency log, such as AEMO data, is detailed enough
  to give clock times.

## Development

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
```

CI runs lint, the format check, the tests and the demo on Python 3.11, 3.12
and 3.13. The real benchmark downloads about 3.3 GB, so I run it by hand:

```bash
uv run python scripts/fetch_enf_whu.py --one-day
uv run python scripts/benchmark_enf_whu.py --one-day
```

## Contributing

Run the development checks before you open a pull request. In a bug report,
include the command, the Python version, the audio format, the sample rate and
the error output. Use a synthetic example if you can. Do not upload private
recordings.

## Licence

MIT. See [LICENSE](LICENSE). The ENF-WHU dataset is under the MIT licence from
its authors. The scripts download it when you need it. This repository does
not include it.

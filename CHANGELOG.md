# Changelog

## 0.2.0

### Added

- `grid-clock validate`: scores matches against independently logged start
  times from a JSON manifest. It counts offset errors, false matches, and
  different-time controls. Logged times are only used as differences.
- Benchmark on real recordings from the public ENF-WHU dataset
  (`scripts/fetch_enf_whu.py`, `scripts/benchmark_enf_whu.py`). Results are in
  [docs/validation.md](docs/validation.md).
- Recording protocol for a test in two places, and an example manifest.
- `valid_overlap_s` in pair outputs; `InsufficientHumError` for pairs that
  cannot be scored.

### Changed

- **Stricter default acceptance.** The minimum valid overlap rose from 60 s to
  300 s, and the minimum correlation from 0.9 to 0.97. With the old defaults,
  1,815 of 7,495 scored controls from different days on real recordings were
  accepted as matches. The new values were chosen on odd numbered clips and
  checked on even numbered clips.
- Each clip now needs at least 315 s of audio to match at the defaults.
  Record at least 8 minutes.
- The synthetic demo clips are 7 minutes long.

## 0.1.0

- First release: trace extraction, relative offset matching, and a synthetic
  demo.

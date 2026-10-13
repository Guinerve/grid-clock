# Validation

This page records what has been measured, how, and what is still untested.
All offsets are relative. No result here establishes an absolute timestamp.

## Real recordings: ENF-WHU

[ENF-WHU](https://github.com/ghua-ac/ENF-WHU-Dataset) (Hua et al., MIT
licence) holds 130 phone and voice-recorder clips from Wuhan University (H1).
They run 5 to 20 minutes on China's 50 Hz grid. For each clip, a separate
logger captured the mains frequency at the same time (H1_ref). The dataset
aligns each clip with its reference, so the expected offset is 0 s. H0 holds 10
clips recorded without grid hum. The dataset publishes no calendar dates.

The benchmark is pinned to commit `78ed7f3`. Every file is checked against its
git blob hash.

```bash
uv run python scripts/fetch_enf_whu.py --one-day      # ~3.3 GB into data/raw/
uv run python scripts/benchmark_enf_whu.py --one-day  # writes output/enf-whu/
```

Summaries from the runs below are saved in
[enf-whu-benchmark.json](enf-whu-benchmark.json) and
[enf-whu-benchmark-v0.1-thresholds.json](enf-whu-benchmark-v0.1-thresholds.json).
Per-pair CSV files are written to `output/enf-whu/`.

### Test sets

| Set | Pairs | Expected result |
| --- | --- | --- |
| Clip vs its simultaneous mains reference | 130 | Offset within 16 s of 0 |
| Clip vs every reference from a different day | 15,614 | No accepted match |
| Clip vs every clip from a different day | 7,807 | No accepted match |
| No-hum H0 clip vs every reference | 1,300 | No accepted match |
| Clip searched across its full 24-hour reference | 130 | Offset within 16 s of where the clean reference sits |

Day groups come from the dataset's `H1_ref_one_day` file names. Clips in
different groups were recorded on different days, so their grid patterns can't
overlap. These pairs are the different-time negative controls.

The 16 s tolerance equals one analysis window, the radius inside which the
matcher treats two offsets as the same peak. Measured errors are listed
separately and are much smaller.

### Threshold selection

Version 0.1 accepted a match with r ≥ 0.9 over at least 60 s of overlap. On
the second harmonic it accepted **1,815 of 7,495** scored different-day
reference controls and **312 of 1,552** scored different-day clip controls.
Four simultaneous pairs were accepted at the wrong offset. Grid frequency
drifts slowly, so a short overlap holds only a few independent values. Any two
gentle slopes then correlate strongly. To reproduce these numbers, run
`scripts/benchmark_enf_whu.py --min-overlap 60 --min-correlation 0.9`.

Thresholds were swept on the odd-numbered clips only (development half). The
sweep covered the minimum overlap (60–300 s), the minimum correlation
(0.9–0.99), the peak margin (0.05, 0.1), and optional trend removal. The
chosen rule is **at least 300 s of valid overlap and r ≥ 0.97**, with the peak
margin unchanged at 0.05. It had no development false matches and matched the
best development recall in the sweep (24 of 65). At 300 s it also had no false
matches at r ≥ 0.95, which leaves some margin. Trend removal gave no
improvement and was dropped.

The rule was then frozen and run on the even-numbered clips (held-out half).

### Results with the 0.2 defaults

Second harmonic (`--harmonic 2`) on the clips; fundamental on the references.

| Set | Split | Correct | Wrong offset | False match | Rejected | No decision |
| --- | --- | --- | --- | --- | --- | --- |
| Simultaneous reference | development | 24 / 65 | 0 | – | 1 | 40 |
| Simultaneous reference | held out | 20 / 65 | 0 | – | 3 | 42 |
| Simultaneous reference | all | 44 / 130 | 0 | – | 4 | 82 |
| Different-day reference | held out | – | – | 0 | 1,339 | 2,569 |
| Different-day reference | all | – | – | 0 | 5,717 | 9,897 |
| Different-day clip | held out | – | – | 0 | 201 | 1,753 |
| Different-day clip | all | – | – | 0 | 881 | 6,926 |
| No-hum clip | all | – | – | 0 | 0 | 1,300 |
| 24-hour search | held out | 19 / 56 | 0 | – | 2 | 35 |
| 24-hour search | all | 41 / 113 | 0 | – | 3 | 69 |

"All" includes pairs that mix a development clip with a held-out clip.
"No decision" means a clip lacked 300 s of valid, changing hum in the overlap.

**Offset error.** The 44 accepted simultaneous pairs had a median absolute
error of 2 s and a maximum of 4 s against the dataset's alignment. The errors
cluster between −2 s and +4 s. Part of this spread may come from how the
dataset cut each reference, not from the matcher.

**24-hour search.** Each clip was searched across its whole day's reference,
about 86,000 candidate offsets. The truth is where the clip's clean reference
sits in that day. For 17 clips, the clean reference matched its own day log at
r < 0.99 or not at all, so they were left out. For example, clip 031 scored
0.979. Of the other 113, 41 were found within 4 s (errors −4 s to +2 s), and
none was placed at a wrong offset.

**False matches.** None of the 6,598 scored different-day pairs was accepted.
Taken as independent trials, that bounds the false-match rate below about
0.05% per pair (95%, rule of three). The pairs share clips and are not
independent, so treat that bound as optimistic.

**Fundamental.** At 50 Hz, none of the 130 phone clips produced a usable
trace. All 130 simultaneous pairs ended with no decision. The likely cause is
low-frequency filtering in phone microphones and recorders.

**Coverage.** Only 46 of 130 clips had at least 80% valid frames at the second
harmonic. Most failures are no-decisions, not wrong answers. The method
declines weak clips instead of guessing.

![Real phone clip aligned with its mains reference](../assets/real-match.png)

`scripts/plot_enf_whu_example.py 100` draws this figure.

### What this does and does not show

- It shows that real phone recordings with audible 100 Hz hum can be aligned
  with a simultaneous mains log to within a few seconds. The thresholds
  rejected every scored different-day control in this dataset.
- Each simultaneous pair here is a microphone recording against a direct mains
  log. Two microphone recordings made at the same time have not been tested
  against each other. That is the two-location test below.
- All clips come from one city, one grid, and a few devices. Other grids,
  devices, compression, and rooms may behave differently.
- The thresholds are screening heuristics. They are not forensic confidence
  levels.

## Your own two-location test

Not yet done. Two simultaneous recordings in different places, with start
times logged independently, plus a different-time control, are needed to test
the clip-to-clip case. Follow [two-location-protocol.md](two-location-protocol.md)
and run `grid-clock validate`.

## Absolute timestamps

Not supported. A dated, public grid-frequency reference with fine enough
resolution is needed before any recording can be placed in calendar time. No
such source is integrated or validated. Until one is, `grid-clock` reports
relative offsets only.

## Synthetic tests

`uv run pytest` covers known drift in noise, both harmonics, 50 and 60 Hz,
positive and negative offsets, missing frames, unrelated and periodic traces,
manifest validation, and the scoring rules. These tests confirm that the code
does what it says. They do not show that real recordings will behave the same
way.

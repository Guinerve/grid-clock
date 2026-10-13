# Two-location recording test

This test checks `grid-clock` on your own recordings. Two people record at the
same time in two places on the same grid. Each person logs their start time on
their own. A third recording, made at a different time, is the negative control.

`grid-clock validate` compares each measured offset with the difference between
the logged start times. It also counts false matches. It does not report an
absolute time. The logged times are only used as differences.

## Safety

Record the sound of normal, enclosed equipment only. **Never connect a
microphone, probe, cable, or circuit to mains.**

## What you need

- Two phones or recorders, one at each location.
- A mains-powered appliance near each recorder. Try a laptop on its charger, a
  fridge, a desk lamp, or a fluorescent light.
- Both locations on the same synchronous grid. In Australia, mainland NEM
  states share one grid. Tasmania and Western Australia each run separately.
- A clock that shows seconds and sets itself from the network. A phone with
  automatic date and time works.

## Steps

1. Turn off noise reduction and voice enhancement in the recording app if you
   can. Use the highest-quality or lossless setting.
2. Put each recorder near its appliance. Keep the room quiet if possible.
3. Agree on a rough start time, such as 7 pm. Each person starts on their own.
   An exact simultaneous start is not needed.
4. At the moment you press record, note the start time to the second. A
   screenshot of a clock that shows seconds is the easiest record. Write down
   how far off your note could be. One or two seconds is typical.
5. Record for at least **8 minutes**. The matcher needs five minutes of valid,
   overlapping hum. The extra time absorbs a late start and weak sections.
6. For the control, record again with one of the devices at a clearly
   different time, such as the next morning. Log it the same way.
7. Copy the files to `data/raw/two-location/`. Git ignores `data/raw/`.

The two logs must be independent. Do not copy one person's time into the other
person's log, and do not adjust either log after seeing the result.

## Run the check

Copy `examples/two-location.manifest.json` and fill in your file names, start
times, and uncertainties. Each `logged_start` needs a UTC offset, such as
`+11:00`, so daylight saving cannot shift it. Relative audio paths are read from
the manifest's folder.

```bash
uv run grid-clock validate my-manifest.json --harmonic 2 --output output/two-location
uv run grid-clock validate my-manifest.json --harmonic 1 --output output/two-location-h1
```

Phone microphones usually remove 50 Hz. On the ENF-WHU phone recordings, only
the 100 Hz harmonic (`--harmonic 2`) gave usable traces. Run both harmonics
and report both results.

Every pair of recordings gets one of these labels:

| Kind | When | Expected result |
| --- | --- | --- |
| `simultaneous` | Logged intervals overlap by at least `--min-overlap` seconds after both uncertainties | `correct`: accepted, within tolerance |
| `different-time` | Logged intervals are separated by more than both uncertainties | `rejected` or `no-decision` |
| `partial-overlap` | Neither of the above | Listed, not scored |

The tolerance is the sum of both start uncertainties plus one hop (1 s by
default). An accepted simultaneous pair outside tolerance is a `wrong-offset`.
An accepted different-time pair is a `false-match`. Both count as false matches.
`no-decision` means one clip did not have enough valid, changing hum.

The command writes `validation.json` and `pairs.csv` and prints a summary.
Exit code `0` means the experiment passed: at least one simultaneous pair was
correct, at least one control was rejected, and nothing was falsely matched.
Exit code `1` means it did not pass, and the summary says why. Exit code `2`
means a manifest, audio, or settings error.

## Reporting a result

Report the counts from `summary`, the offset errors from `pairs.csv`, the
harmonic, the devices, and the recording app settings. Report failures too.
Do not share the recordings themselves if they contain private speech.

One passing pair shows that the method worked once, under those conditions.
It does not establish an error rate. Repeat the test at different times and
places before relying on it.

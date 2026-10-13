"""Measure offset error and false matches on real recordings from ENF-WHU.

Run `scripts/fetch_enf_whu.py` first. Each H1 clip was recorded on a phone or
voice recorder while a separate logger captured the mains frequency (H1_ref).
The dataset aligns each pair, so the expected offset is 0 s. Clips from
different days cannot share a grid pattern and serve as negative controls.
H0 clips contain no grid hum. With `--one-day`, every clip is also searched
across its full 24-hour reference.

Nothing here produces a calendar time. The dataset publishes no dates.

    uv run python scripts/benchmark_enf_whu.py
"""

import argparse
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from itertools import combinations
from pathlib import Path

import numpy as np

from grid_clock.audio import load_audio
from grid_clock.match import MIN_CORRELATION, MIN_OVERLAP_S, InsufficientHumError, match_traces
from grid_clock.trace import FrequencyTrace, TraceConfig, extract_trace
from grid_clock.validate import PairOutcome, score_pair, summarise, write_pairs

# H1_ref_one_day file names at the pinned commit: clips recorded on the same day.
DAY_GROUPS = (
    "001 002 003-004 005 006-007 008-009 010 011 012-013 014 015 016-019 020-025 026-028 "
    "029 030-033 034-037 038 039-042 043-059 060-064 065-069 070 071-079 080-088 089-107 "
    "108-115 116-130"
).split()
TOLERANCE_S = 16  # One analysis window: the matcher's own "different peak" radius.


def day_of(clip: int) -> str:
    for group in DAY_GROUPS:
        first, _, last = group.partition("-")
        if int(first) <= clip <= int(last or first):
            return group
    raise ValueError(f"Clip {clip} is not in a day group.")


def trace_file(path: Path, harmonic: int) -> FrequencyTrace:
    audio = load_audio(path)
    return extract_trace(audio.samples, audio.sample_rate, TraceConfig(harmonic=harmonic))


def trace_all(paths: list[Path], harmonic: int, workers: int) -> dict[str, FrequencyTrace]:
    with ProcessPoolExecutor(max_workers=workers) as pool:
        traces = pool.map(partial(trace_file, harmonic=harmonic), paths, chunksize=4)
        return {path.stem: trace for path, trace in zip(paths, traces, strict=True)}


def valid_fractions(traces: dict[str, FrequencyTrace]) -> dict:
    fractions = np.array([np.mean(t.valid) for t in traces.values()])
    return {
        "clips": int(fractions.size),
        "median_valid_fraction": float(np.median(fractions)),
        "clips_at_least_80_percent_valid": int(np.sum(fractions >= 0.8)),
    }


def search_day(group: str, root: Path, clips: dict[str, FrequencyTrace], **screening) -> list:
    """Search each clip across its 24-hour reference. Truth comes from the clean reference."""
    path = root / "H1_ref_one_day" / f"{group}_ref.wav"
    if not path.is_file():
        raise ValueError(f"Missing {path}. Run fetch_enf_whu.py --one-day.")
    day = trace_file(path, 1)
    print(f"day {group}: {np.mean(day.valid):.1%} valid frames", file=sys.stderr, flush=True)
    first, _, last = group.partition("-")
    results = []
    for clip in range(int(first), int(last or first) + 1):
        name = f"{clip:03d}"
        reference = trace_file(root / "H1_ref" / f"{name}_ref.wav", 1)
        try:
            truth = match_traces(day, reference)
        except InsufficientHumError:
            truth = None  # No eligible offset, so there is no reliable truth.
        if truth is None or not truth.accepted or truth.correlation < 0.99:
            results.append((name, None))
            continue
        outcome = score_pair(
            f"day-{group}",
            name,
            day,
            clips[name],
            expected_offset_s=truth.offset_s,
            tolerance_s=TOLERANCE_S,
            **screening,
        )
        results.append((name, outcome))
    return results


def split_of(outcome: PairOutcome) -> str:
    """Odd clips chose the default thresholds; even clips are held out."""
    numbers = [int(n[:3]) for n in (outcome.a, outcome.b) if re.fullmatch(r"\d{3}(_ref)?", n)]
    parities = {n % 2 for n in numbers}
    return {frozenset({1}): "development", frozenset({0}): "held_out"}.get(
        frozenset(parities), "mixed"
    )


def report_set(outcomes: list[PairOutcome]) -> dict:
    result = {"all": summarise(outcomes)}
    for split in ("development", "held_out"):
        result[split] = summarise([o for o in outcomes if split_of(o) == split])
    errors = [o.offset_error_s for o in outcomes if o.accepted and o.offset_error_s is not None]
    if errors:
        result["accepted_offset_errors_s"] = sorted(errors)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path("data/raw/enf-whu"))
    parser.add_argument("--output", type=Path, default=Path("output/enf-whu"))
    parser.add_argument("--one-day", action="store_true", help="Also run 24-hour searches")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--min-overlap", type=float, default=MIN_OVERLAP_S)
    parser.add_argument("--min-correlation", type=float, default=MIN_CORRELATION)
    args = parser.parse_args(argv)
    screening = {"min_overlap_s": args.min_overlap, "min_correlation": args.min_correlation}
    clips = sorted((args.data / "H1").glob("*.wav"))
    references = sorted((args.data / "H1_ref").glob("*_ref.wav"))
    no_hum = sorted((args.data / "H0").glob("O*.wav"))
    if len(clips) != 130 or len(references) != 130 or len(no_hum) != 10:
        raise SystemExit("Expected 130 H1, 130 H1_ref and 10 H0 files. Run fetch_enf_whu.py.")
    args.output.mkdir(parents=True, exist_ok=True)

    refs = {k.removesuffix("_ref"): v for k, v in trace_all(references, 1, args.workers).items()}
    report = {
        "dataset": "ENF-WHU, commit 78ed7f3784949f769f291fc1cb94acd10da6322f (MIT licence)",
        "settings": {
            "window_s": 16,
            "hop_s": 1,
            "min_strength_db": 20,
            **screening,
            "max_offset_s": None,
            "tolerance_s": TOLERANCE_S,
            "reference_harmonic": 1,
        },
        "references": valid_fractions(refs),
        "note": "Relative offsets only. No absolute timestamp is inferred.",
    }
    for harmonic in (1, 2):
        traces = trace_all(clips, harmonic, args.workers)
        silent = trace_all(no_hum, harmonic, args.workers)
        sets: dict[str, list[PairOutcome]] = {
            "recording_vs_simultaneous_reference": [],
            "recording_vs_other_day_reference": [],
            "recording_vs_other_day_recording": [],
            "no_hum_recording_vs_reference": [],
        }
        for name, trace in traces.items():
            sets["recording_vs_simultaneous_reference"].append(
                score_pair(
                    name,
                    f"{name}_ref",
                    trace,
                    refs[name],
                    expected_offset_s=0,
                    tolerance_s=TOLERANCE_S,
                    **screening,
                )
            )
            for other, reference in refs.items():
                if day_of(int(other)) != day_of(int(name)):
                    sets["recording_vs_other_day_reference"].append(
                        score_pair(
                            name,
                            f"{other}_ref",
                            trace,
                            reference,
                            expected_offset_s=None,
                            **screening,
                        )
                    )
        for (a, a_trace), (b, b_trace) in combinations(traces.items(), 2):
            if day_of(int(a)) != day_of(int(b)):
                sets["recording_vs_other_day_recording"].append(
                    score_pair(a, b, a_trace, b_trace, expected_offset_s=None, **screening)
                )
        for name, trace in silent.items():
            for other, reference in refs.items():
                sets["no_hum_recording_vs_reference"].append(
                    score_pair(
                        name, f"{other}_ref", trace, reference, expected_offset_s=None, **screening
                    )
                )
        key = f"harmonic_{harmonic}"
        report[key] = {"recordings": valid_fractions(traces), "no_hum": valid_fractions(silent)}
        for label, outcomes in sets.items():
            write_pairs(args.output / f"{key}.{label}.csv", outcomes)
            report[key][label] = report_set(outcomes)
        print(f"harmonic {harmonic} done", file=sys.stderr, flush=True)
        if args.one_day and harmonic == 2:
            with ProcessPoolExecutor(max_workers=min(args.workers, 4)) as pool:
                search = partial(search_day, root=args.data, clips=traces, **screening)
                results = [r for group in pool.map(search, DAY_GROUPS) for r in group]
            scored = [outcome for _, outcome in results if outcome is not None]
            write_pairs(args.output / f"{key}.one_day_search.csv", scored)
            report[key]["one_day_search"] = {
                **report_set(scored),
                "skipped_without_clean_truth": [n for n, o in results if o is None],
            }
    (args.output / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

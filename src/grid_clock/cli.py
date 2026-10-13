"""One-command audio trace extraction and relative-time matching."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

from grid_clock.audio import load_audio
from grid_clock.demo import DEMO_OFFSET_S, create_demo
from grid_clock.match import (
    MIN_CORRELATION,
    MIN_DRIFT_STD_HZ,
    MIN_OVERLAP_S,
    MIN_PEAK_MARGIN,
    MIN_VALID_FRACTION,
    match_traces,
)
from grid_clock.output import plot_traces, trace_summary, write_json, write_trace
from grid_clock.trace import FrequencyTrace, TraceConfig, extract_trace
from grid_clock.validate import load_manifest, validate_recordings, write_pairs


def _trace_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--nominal", type=float, choices=[50, 60], default=50, help="Grid frequency in Hz"
    )
    parser.add_argument(
        "--harmonic",
        type=int,
        choices=[1, 2],
        default=1,
        help="1 tracks the fundamental, 2 the second harmonic (try 2 for phones)",
    )
    parser.add_argument("--window", type=float, default=16, help="Analysis window in seconds")
    parser.add_argument("--hop", type=float, default=1, help="Trace step in seconds")
    parser.add_argument(
        "--min-strength", type=float, default=20, help="Lowest peak to noise ratio in dB"
    )
    parser.add_argument(
        "--channel", type=int, help="Audio channel, counting from 0 (default: highest RMS)"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grid-clock",
        description=(
            "Line up audio recordings using the hum of the power grid. "
            "Gives relative offsets only. Never connect anything to mains."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    trace = commands.add_parser("trace", help="Write a frequency trace, strength plot, and summary")
    trace.add_argument("clip", type=Path, help="Audio file (WAV, FLAC, or M4A with ffmpeg)")
    trace.add_argument("--output", type=Path, default=Path("output/trace"), help="Output folder")
    _trace_options(trace)
    match = commands.add_parser("match", help="Estimate when B started relative to A")
    match.add_argument("a", type=Path, help="First audio file (clip A)")
    match.add_argument("b", type=Path, help="Second audio file (clip B)")
    match.add_argument("--output", type=Path, default=Path("output/match"), help="Output folder")
    validate = commands.add_parser(
        "validate",
        help="Score matches against independently logged start times",
    )
    validate.add_argument("manifest", type=Path, help="JSON list of recordings and logged starts")
    validate.add_argument(
        "--output", type=Path, default=Path("output/validation"), help="Output folder"
    )
    for command in (match, validate):
        command.add_argument(
            "--min-overlap",
            type=float,
            default=MIN_OVERLAP_S,
            help="Valid seconds that both clips must share",
        )
        command.add_argument(
            "--max-offset",
            type=float,
            help="Search only within plus or minus this many seconds",
        )
        _trace_options(command)
    demo = commands.add_parser("demo", help="Generate and match noisy synthetic hum clips")
    demo.add_argument("--output", type=Path, default=Path("output/demo"), help="Output folder")
    demo.add_argument("--force", action="store_true", help="Replace existing demo audio files")
    return parser


def _compare(
    a_path: Path,
    b_path: Path,
    output: Path,
    config: TraceConfig,
    *,
    channel: int | None = None,
    min_overlap_s: float = MIN_OVERLAP_S,
    max_offset_s: float | None = None,
    synthetic: bool = False,
) -> tuple[dict, FrequencyTrace, FrequencyTrace]:
    audio_a = load_audio(a_path, channel=channel)
    audio_b = load_audio(b_path, channel=channel)
    a = extract_trace(audio_a.samples, audio_a.sample_rate, config)
    b = extract_trace(audio_b.samples, audio_b.sample_rate, config)
    result = match_traces(a, b, min_overlap_s=min_overlap_s, max_offset_s=max_offset_s)
    summary = asdict(result)
    summary.update(
        {
            "offset_convention": "Positive offset means B started later than A.",
            "a": {"source": str(a_path), **trace_summary(a, channel=audio_a.channel)},
            "b": {"source": str(b_path), **trace_summary(b, channel=audio_b.channel)},
            "screening": {
                "min_overlap_s": min_overlap_s,
                "max_offset_s": max_offset_s,
                "min_correlation": MIN_CORRELATION,
                "min_peak_margin": MIN_PEAK_MARGIN,
                "min_drift_std_hz": MIN_DRIFT_STD_HZ,
                "min_valid_fraction": MIN_VALID_FRACTION,
            },
            "note": "Candidate alignment only. No absolute timestamp or forensic confidence.",
        }
    )
    output.mkdir(parents=True, exist_ok=True)
    write_trace(output / "a.trace.csv", a)
    write_trace(output / "b.trace.csv", b)
    label = "Synthetic demo" if synthetic else "Candidate alignment"
    if not result.accepted:
        label += " (not accepted)"
    plot_traces(
        output / "match.png",
        a,
        b,
        offset_s=result.offset_s,
        title=f"{label}: B starts {result.offset_s:+g} s relative to A",
    )
    return summary, a, b


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "demo":
            truth_times, truth_frequency = create_demo(args.output, force=args.force)
            summary, a, b = _compare(
                args.output / "a.wav",
                args.output / "b.wav",
                args.output,
                TraceConfig(),
                synthetic=True,
            )
            errors = [
                np.abs(
                    trace.frequency_hz[trace.valid]
                    - np.interp(
                        trace.time_s[trace.valid] + start,
                        truth_times,
                        truth_frequency,
                    )
                )
                for trace, start in [(a, 0), (b, DEMO_OFFSET_S)]
            ]
            summary.update(
                {
                    "synthetic": True,
                    "expected_offset_s": DEMO_OFFSET_S,
                    "max_trace_error_hz": float(np.max(np.concatenate(errors))),
                }
            )
            write_json(args.output / "match.json", summary)
            print(json.dumps(summary, indent=2, allow_nan=False))
            return 0 if summary["accepted"] else 1
        config = TraceConfig(args.nominal, args.harmonic, args.window, args.hop, args.min_strength)
        if args.command == "validate":
            report = validate_recordings(
                load_manifest(args.manifest),
                config,
                channel=args.channel,
                min_overlap_s=args.min_overlap,
                max_offset_s=args.max_offset,
            )
            args.output.mkdir(parents=True, exist_ok=True)
            write_pairs(args.output / "pairs.csv", report["pairs"])
            report["pairs"] = [asdict(pair) for pair in report["pairs"]]
            write_json(args.output / "validation.json", report)
            print(json.dumps({k: report[k] for k in ("passed", "summary", "warnings")}, indent=2))
            return 0 if report["passed"] else 1
        if args.command == "match":
            summary, _, _ = _compare(
                args.a,
                args.b,
                args.output,
                config,
                channel=args.channel,
                min_overlap_s=args.min_overlap,
                max_offset_s=args.max_offset,
            )
            write_json(args.output / "match.json", summary)
            print(json.dumps(summary, indent=2, allow_nan=False))
            return 0 if summary["accepted"] else 1
        audio = load_audio(args.clip, channel=args.channel)
        trace = extract_trace(audio.samples, audio.sample_rate, config)
        args.output.mkdir(parents=True, exist_ok=True)
        summary = trace_summary(trace, channel=audio.channel)
        summary["source"] = str(args.clip)
        write_trace(args.output / "trace.csv", trace)
        plot_traces(args.output / "trace.png", trace)
        write_json(args.output / "summary.json", summary)
        print(json.dumps(summary, indent=2, allow_nan=False))
        return 0 if np.any(trace.valid) else 1
    except (ValueError, OSError) as error:
        print(f"grid-clock: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Plot one real ENF-WHU phone clip against its simultaneous mains reference.

Writes assets/real-match.png. Run scripts/fetch_enf_whu.py first.

    uv run python scripts/plot_enf_whu_example.py 100
"""

import argparse
from pathlib import Path

from grid_clock.audio import load_audio
from grid_clock.match import match_traces
from grid_clock.output import plot_traces
from grid_clock.trace import TraceConfig, extract_trace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("clip", help="H1 clip number, such as 100")
    parser.add_argument("--data", type=Path, default=Path("data/raw/enf-whu"))
    parser.add_argument("--output", type=Path, default=Path("assets/real-match.png"))
    args = parser.parse_args(argv)
    name = f"{int(args.clip):03d}"
    reference = load_audio(args.data / "H1_ref" / f"{name}_ref.wav")
    clip = load_audio(args.data / "H1" / f"{name}.wav")
    a = extract_trace(reference.samples, reference.sample_rate, TraceConfig(harmonic=1))
    b = extract_trace(clip.samples, clip.sample_rate, TraceConfig(harmonic=2))
    result = match_traces(a, b)
    print(result)
    plot_traces(
        args.output,
        a,
        b,
        offset_s=result.offset_s,
        title=f"Real clip {name}: offset {result.offset_s:+g} s, r = {result.correlation:.4f}",
        labels=("Mains reference (50 Hz)", f"Phone clip {name} (100 Hz ÷ 2, aligned)"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

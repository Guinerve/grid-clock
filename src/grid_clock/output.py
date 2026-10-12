"""Portable CSV/JSON output and headless plots."""

import csv
import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from grid_clock.trace import FrequencyTrace  # noqa: E402


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_trace(path: Path, trace: FrequencyTrace) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["time_s", "frequency_hz", "strength_db", "valid"])
        for time, frequency, strength, valid in zip(
            trace.time_s,
            trace.frequency_hz,
            trace.strength_db,
            trace.valid,
            strict=True,
        ):
            writer.writerow(
                [
                    f"{time:.6f}",
                    f"{frequency:.8f}" if valid else "",
                    f"{strength:.3f}",
                    int(valid),
                ]
            )


def trace_summary(trace: FrequencyTrace, *, channel: int) -> dict:
    return {
        "frames": int(trace.time_s.size),
        "valid_frames": int(np.count_nonzero(trace.valid)),
        "valid_fraction": float(np.mean(trace.valid)),
        "channel": channel,
        "nominal_hz": trace.config.nominal_hz,
        "harmonic": trace.config.harmonic,
        "window_s": trace.config.window_s,
        "hop_s": trace.config.hop_s,
        "min_strength_db": trace.config.min_strength_db,
        "strength_note": "Peak-to-nearby-noise ratio; not a confidence probability.",
    }


def plot_traces(
    path: Path,
    a: FrequencyTrace,
    b: FrequencyTrace | None = None,
    *,
    offset_s: float = 0,
    title: str = "Grid frequency candidate",
) -> None:
    with plt.rc_context(
        {
            "figure.facecolor": "#101a29",
            "axes.facecolor": "#101a29",
            "text.color": "#e8eef5",
            "axes.labelcolor": "#b9cadb",
            "xtick.color": "#b9cadb",
            "ytick.color": "#b9cadb",
            "axes.edgecolor": "#34445a",
            "font.size": 11,
            "grid.color": "#34445a",
            "grid.alpha": 0.5,
        }
    ):
        fig, (frequency_axis, strength_axis) = plt.subplots(
            2,
            1,
            figsize=(11, 6),
            sharex=True,
            gridspec_kw={"height_ratios": [2, 1]},
            layout="constrained",
        )
        try:
            fig.suptitle(title, fontsize=17, fontweight="bold")
            traces = [(a, 0, "#51dac7", "Clip A" if b is not None else "Hum trace")]
            if b is not None:
                traces.append((b, offset_s, "#b99aff", "Clip B (aligned)"))
            for trace, shift, colour, label in traces:
                time = trace.time_s + shift
                frequency_axis.plot(time, trace.frequency_hz, color=colour, label=label, lw=2)
                strength_axis.plot(time, trace.strength_db, color=colour, lw=1.4)
                strength_axis.fill_between(
                    time,
                    trace.config.min_strength_db,
                    trace.strength_db,
                    where=trace.valid,
                    color=colour,
                    alpha=0.15,
                )
            strength_axis.axhline(
                a.config.min_strength_db,
                color="#f6bc69",
                ls="--",
                lw=1,
                label="Strength cutoff",
            )
            frequency_axis.set_ylabel("Grid frequency (Hz)")
            frequency_axis.ticklabel_format(axis="y", style="plain", useOffset=False)
            strength_axis.set_ylabel("Strength (dB)")
            strength_axis.set_xlabel("Time from the start of clip A (s)")
            for axis in (frequency_axis, strength_axis):
                axis.grid(True)
                axis.spines[["top", "right"]].set_visible(False)
                axis.legend(facecolor="#101a29", edgecolor="#34445a", labelcolor="#e8eef5")
            fig.savefig(path, dpi=160)
        finally:
            plt.close(fig)

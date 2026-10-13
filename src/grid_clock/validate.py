"""Score offset estimates against independently logged start times.

Logged start times are only used as differences between recordings. Nothing
here infers, prints, or stores an absolute timestamp.
"""

import csv
import json
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from itertools import combinations
from pathlib import Path

import numpy as np

from grid_clock.audio import load_audio
from grid_clock.match import MIN_CORRELATION, MIN_OVERLAP_S, InsufficientHumError, match_traces
from grid_clock.output import trace_summary
from grid_clock.trace import FrequencyTrace, TraceConfig, extract_trace

SIMULTANEOUS = "simultaneous"
DIFFERENT_TIME = "different-time"
PARTIAL = "partial-overlap"


@dataclass(frozen=True)
class Recording:
    id: str
    path: Path
    location: str
    logged_start: datetime
    start_uncertainty_s: float


@dataclass(frozen=True)
class PairOutcome:
    a: str
    b: str
    kind: str
    outcome: str
    expected_offset_s: float | None
    tolerance_s: float | None = None
    offset_s: float | None = None
    offset_error_s: float | None = None
    correlation: float | None = None
    competing_correlation: float | None = None
    valid_overlap_s: float | None = None
    accepted: bool = False
    reason: str = ""


def score_pair(
    a_id: str,
    b_id: str,
    a: FrequencyTrace,
    b: FrequencyTrace,
    *,
    expected_offset_s: float | None,
    tolerance_s: float | None = None,
    min_overlap_s: float = MIN_OVERLAP_S,
    max_offset_s: float | None = None,
    min_correlation: float = MIN_CORRELATION,
) -> PairOutcome:
    """Match one pair and grade it. `expected_offset_s=None` marks a different-time control.

    Outcomes: `correct`, `wrong-offset` (accepted outside tolerance),
    `false-match` (an accepted control), `rejected`, or `no-decision`
    (not enough valid, changing hum to score).
    """
    kind = DIFFERENT_TIME if expected_offset_s is None else SIMULTANEOUS
    if kind == SIMULTANEOUS and (tolerance_s is None or tolerance_s < 0):
        raise ValueError("A simultaneous pair needs a non-negative offset tolerance.")
    try:
        result = match_traces(
            a,
            b,
            min_overlap_s=min_overlap_s,
            max_offset_s=max_offset_s,
            min_correlation=min_correlation,
        )
    except InsufficientHumError as error:
        return PairOutcome(
            a_id,
            b_id,
            kind,
            "no-decision",
            expected_offset_s,
            tolerance_s,
            reason=str(error),
        )
    error_s = None if expected_offset_s is None else result.offset_s - expected_offset_s
    if not result.accepted:
        outcome = "rejected"
    elif error_s is None:
        outcome = "false-match"
    else:
        outcome = "correct" if abs(error_s) <= tolerance_s + 1e-9 else "wrong-offset"
    return PairOutcome(
        a_id,
        b_id,
        kind,
        outcome,
        expected_offset_s,
        tolerance_s,
        result.offset_s,
        error_s,
        result.correlation,
        result.competing_correlation,
        result.valid_overlap_s,
        result.accepted,
        result.reason,
    )


def summarise(outcomes: list[PairOutcome]) -> dict:
    """Count outcomes per pair kind. False matches include accepted wrong offsets."""

    def count(kind: str, outcome: str) -> int:
        return sum(o.kind == kind and o.outcome == outcome for o in outcomes)

    errors = np.array(
        [abs(o.offset_error_s) for o in outcomes if o.kind == SIMULTANEOUS and o.accepted]
    )
    simultaneous = {
        "pairs": sum(o.kind == SIMULTANEOUS for o in outcomes),
        "correct": count(SIMULTANEOUS, "correct"),
        "wrong_offset": count(SIMULTANEOUS, "wrong-offset"),
        "rejected": count(SIMULTANEOUS, "rejected"),
        "no_decision": count(SIMULTANEOUS, "no-decision"),
        "accepted_abs_offset_error_s": None
        if not errors.size
        else {
            "median": float(np.median(errors)),
            "p95": float(np.percentile(errors, 95)),
            "max": float(np.max(errors)),
        },
    }
    different_time = {
        "pairs": sum(o.kind == DIFFERENT_TIME for o in outcomes),
        "false_matches": count(DIFFERENT_TIME, "false-match"),
        "rejected": count(DIFFERENT_TIME, "rejected"),
        "no_decision": count(DIFFERENT_TIME, "no-decision"),
    }
    return {
        SIMULTANEOUS: simultaneous,
        DIFFERENT_TIME: different_time,
        "not_tested": sum(o.kind == PARTIAL for o in outcomes),
        "false_matches": simultaneous["wrong_offset"] + different_time["false_matches"],
    }


def write_pairs(path: Path, outcomes: list[PairOutcome]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=[field.name for field in fields(PairOutcome)])
        writer.writeheader()
        for outcome in outcomes:
            writer.writerow({k: "" if v is None else v for k, v in asdict(outcome).items()})


def load_manifest(path: Path) -> list[Recording]:
    """Read recordings. Relative audio paths resolve from the manifest's folder."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Manifest is not valid JSON: {error}") from error
    entries = data.get("recordings") if isinstance(data, dict) else None
    if not isinstance(entries, list) or len(entries) < 2:
        raise ValueError("Manifest needs a 'recordings' list with at least two entries.")
    recordings = []
    for index, entry in enumerate(entries):
        where = f"Recording {index + 1}"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be an object.")
        missing = {"id", "path", "location", "logged_start", "start_uncertainty_s"} - set(entry)
        if missing:
            raise ValueError(f"{where} is missing: {', '.join(sorted(missing))}.")
        if not all(
            isinstance(entry[key], str) and entry[key] for key in ("id", "path", "location")
        ):
            raise ValueError(f"{where} needs non-empty text for id, path, and location.")
        try:
            start = datetime.fromisoformat(entry["logged_start"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"{where} has an invalid ISO 8601 logged_start.") from error
        if start.utcoffset() is None:
            raise ValueError(f"{where} logged_start needs a UTC offset, such as +10:00.")
        uncertainty = entry["start_uncertainty_s"]
        if (
            isinstance(uncertainty, bool)
            or not isinstance(uncertainty, (int, float))
            or not np.isfinite(uncertainty)
            or uncertainty < 0
        ):
            raise ValueError(f"{where} start_uncertainty_s must be a non-negative number.")
        recordings.append(
            Recording(
                entry["id"],
                path.parent / entry["path"],
                entry["location"],
                start,
                float(uncertainty),
            )
        )
    if len({r.id for r in recordings}) != len(recordings):
        raise ValueError("Recording ids must be unique.")
    return recordings


def validate_recordings(
    recordings: list[Recording],
    config: TraceConfig,
    *,
    channel: int | None = None,
    min_overlap_s: float = MIN_OVERLAP_S,
    max_offset_s: float | None = None,
) -> dict:
    """Grade every recording pair against the logged start difference.

    Pairs whose logged intervals overlap by at least `min_overlap_s` after
    allowing for both start uncertainties are simultaneous. Pairs separated by
    a gap larger than both uncertainties are different-time controls. Other
    pairs are listed as not tested. A simultaneous pair is correct when the
    accepted offset is within both uncertainties plus one hop.
    """
    traces, details = {}, []
    for recording in recordings:
        audio = load_audio(recording.path, channel=channel)
        traces[recording.id] = extract_trace(audio.samples, audio.sample_rate, config)
        duration = audio.samples.size / audio.sample_rate
        details.append(
            {
                "id": recording.id,
                "location": recording.location,
                "source": str(recording.path),
                "duration_s": duration,
                "start_uncertainty_s": recording.start_uncertainty_s,
                **trace_summary(traces[recording.id], channel=audio.channel),
            }
        )
    durations = {d["id"]: d["duration_s"] for d in details}
    outcomes = []
    for a, b in combinations(recordings, 2):
        logged_offset = (b.logged_start - a.logged_start).total_seconds()
        overlap = min(durations[a.id], logged_offset + durations[b.id]) - max(0, logged_offset)
        margin = a.start_uncertainty_s + b.start_uncertainty_s
        if overlap - margin >= min_overlap_s:
            outcome = score_pair(
                a.id,
                b.id,
                traces[a.id],
                traces[b.id],
                expected_offset_s=logged_offset,
                tolerance_s=margin + config.hop_s,
                min_overlap_s=min_overlap_s,
                max_offset_s=max_offset_s,
            )
        elif overlap + margin < 0:
            outcome = score_pair(
                a.id,
                b.id,
                traces[a.id],
                traces[b.id],
                expected_offset_s=None,
                min_overlap_s=min_overlap_s,
                max_offset_s=max_offset_s,
            )
        else:
            outcome = PairOutcome(
                a.id,
                b.id,
                PARTIAL,
                "not-tested",
                logged_offset,
                reason="Logged overlap is too short to test but is not a clear gap.",
            )
        outcomes.append(outcome)
    summary = summarise(outcomes)
    warnings = []
    if not summary[SIMULTANEOUS]["correct"]:
        warnings.append("No simultaneous pair produced an accepted offset within tolerance.")
    if not summary[DIFFERENT_TIME]["rejected"]:
        warnings.append("No different-time control was scored and rejected.")
    if summary["false_matches"]:
        warnings.append("At least one false match was accepted.")
    return {
        "passed": not warnings,
        "summary": summary,
        "warnings": warnings,
        "recordings": details,
        "pairs": outcomes,
        "settings": {
            "min_overlap_s": min_overlap_s,
            "max_offset_s": max_offset_s,
            "tolerance": "Sum of both start uncertainties plus one hop.",
        },
        "offset_convention": "Positive offset means B started later than A.",
        "note": (
            "Logged start times are used only as differences. "
            "No absolute timestamp is inferred or reported."
        ),
    }

import csv
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from scipy.ndimage import gaussian_filter1d

from grid_clock.cli import main
from grid_clock.trace import FrequencyTrace, TraceConfig
from grid_clock.validate import load_manifest, score_pair

RATE = 1000


def drift(seed: int, seconds: int = 900) -> np.ndarray:
    values = gaussian_filter1d(np.random.default_rng(seed).normal(0, 0.1, seconds + 1), 3)
    return 50 + values - values.mean()


def make_trace(frequency: np.ndarray) -> FrequencyTrace:
    valid = np.isfinite(frequency)
    return FrequencyTrace(
        np.arange(frequency.size) + 8.0,
        frequency,
        np.full(frequency.size, 30.0),
        valid,
        TraceConfig(),
    )


def write_hum(path, grid, start_s, seconds, seed):
    rng = np.random.default_rng(seed)
    time = start_s + np.arange(seconds * RATE) / RATE
    frequency = np.interp(time, np.arange(grid.size), grid)
    phase = rng.uniform(0, 2 * np.pi) + 2 * np.pi * np.cumsum(frequency) / RATE
    sf.write(path, 0.3 * np.sin(phase) + rng.normal(0, 0.5, time.size), RATE)


def write_experiment(directory, *, logged_b="2026-10-14T19:00:38+11:00"):
    today, other_day = drift(1), drift(2)
    write_hum(directory / "home.wav", today, 100, 420, seed=10)
    write_hum(directory / "office.wav", today, 137, 420, seed=11)
    write_hum(directory / "control.wav", other_day, 100, 420, seed=12)
    manifest = {
        "recordings": [
            {
                "id": "home",
                "path": "home.wav",
                "location": "home",
                "logged_start": "2026-10-14T19:00:00+11:00",
                "start_uncertainty_s": 1,
                "clock": "Phone clock, network time",
            },
            {
                "id": "office",
                "path": "office.wav",
                "location": "office",
                "logged_start": logged_b,
                "start_uncertainty_s": 1,
            },
            {
                "id": "control",
                "path": "control.wav",
                "location": "home",
                "logged_start": "2026-10-15T08:00:00Z",
                "start_uncertainty_s": 1,
            },
        ]
    }
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_two_location_experiment_with_control_passes_and_reports_offset_error(tmp_path, capsys):
    manifest = write_experiment(tmp_path)
    output = tmp_path / "report"

    assert main(["validate", str(manifest), "--output", str(output)]) == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed["passed"] is True
    summary = printed["summary"]
    assert summary["simultaneous"]["pairs"] == 1
    assert summary["simultaneous"]["correct"] == 1
    # Logged difference is 38 s; the audio was cut 37 s apart.
    assert summary["simultaneous"]["accepted_abs_offset_error_s"]["max"] == 1
    assert summary["different-time"] == {
        "pairs": 2,
        "false_matches": 0,
        "rejected": 2,
        "no_decision": 0,
    }
    assert summary["false_matches"] == 0
    with (output / "pairs.csv").open() as file:
        rows = {(row["a"], row["b"]): row for row in csv.DictReader(file)}
    home_office = rows[("home", "office")]
    assert home_office["outcome"] == "correct"
    assert float(home_office["expected_offset_s"]) == 38
    assert float(home_office["offset_s"]) == 37
    assert float(home_office["tolerance_s"]) == 3
    report_text = (output / "validation.json").read_text()
    assert "2026-10" not in report_text, "Absolute logged times must not reach the report."
    assert json.loads(report_text)["pairs"][0]["outcome"] == "correct"


def test_a_badly_logged_start_is_counted_as_a_false_match(tmp_path, capsys):
    manifest = write_experiment(tmp_path, logged_b="2026-10-14T19:01:30+11:00")
    assert main(["validate", str(manifest), "--output", str(tmp_path / "report")]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["passed"] is False
    assert printed["summary"]["simultaneous"]["wrong_offset"] == 1
    assert printed["summary"]["false_matches"] == 1
    assert "At least one false match was accepted." in printed["warnings"]


def test_short_logged_overlap_is_listed_but_not_scored(tmp_path, capsys):
    manifest = write_experiment(tmp_path, logged_b="2026-10-14T19:03:20+11:00")
    assert main(["validate", str(manifest), "--output", str(tmp_path / "report")]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["summary"]["not_tested"] == 1
    assert printed["summary"]["simultaneous"]["pairs"] == 0
    assert "No simultaneous pair" in printed["warnings"][0]


def test_accepted_control_is_a_false_match_and_missing_hum_is_no_decision():
    grid = drift(3, 300)
    same = make_trace(grid)
    control = score_pair("a", "b", same, same, expected_offset_s=None)
    assert control.outcome == "false-match"
    assert control.offset_error_s is None
    silent = make_trace(np.full(300, np.nan))
    empty = score_pair("a", "b", same, silent, expected_offset_s=0, tolerance_s=1)
    assert empty.outcome == "no-decision"
    assert "Not enough" in empty.reason
    with pytest.raises(ValueError, match="tolerance"):
        score_pair("a", "b", same, same, expected_offset_s=0)
    with pytest.raises(ValueError, match="Minimum overlap"):
        score_pair("a", "b", same, same, expected_offset_s=None, min_overlap_s=0)


@pytest.mark.parametrize(
    "change, message",
    [
        ({"logged_start": "2026-10-14T19:00:00"}, "UTC offset"),
        ({"logged_start": "yesterday"}, "ISO 8601"),
        ({"start_uncertainty_s": -1}, "non-negative"),
        ({"start_uncertainty_s": True}, "non-negative"),
        ({"id": "office"}, "unique"),
        ({"location": ""}, "non-empty"),
        ({"logged_start": None}, "ISO 8601"),
    ],
)
def test_manifest_rejects_ambiguous_or_incomplete_logs(tmp_path, change, message):
    first = {
        "id": "home",
        "path": "home.wav",
        "location": "home",
        "logged_start": "2026-10-14T19:00:00+11:00",
        "start_uncertainty_s": 1,
    }
    second = {**first, "id": "office", "location": "office"}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"recordings": [{**first, **change}, second]}))
    with pytest.raises(ValueError, match=message):
        load_manifest(path)


@pytest.mark.parametrize(
    "content, message",
    [
        ("{", "not valid JSON"),
        ('{"recordings": []}', "at least two"),
        ('{"recordings": [{"id": "a"}, {"id": "b"}]}', "missing"),
    ],
)
def test_validate_command_reports_manifest_errors(tmp_path, capsys, content, message):
    path = tmp_path / "manifest.json"
    path.write_text(content)
    assert main(["validate", str(path)]) == 2
    assert message in capsys.readouterr().err


def test_example_manifest_parses():
    recordings = load_manifest(Path(__file__).parents[1] / "examples/two-location.manifest.json")
    assert [r.location for r in recordings] == ["home", "office", "home"]
    assert all(r.logged_start.utcoffset() is not None for r in recordings)

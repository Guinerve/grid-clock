import csv
import json

import numpy as np
import pytest
import soundfile as sf

from grid_clock.cli import main


def test_demo_preserves_existing_audio_unless_replacement_is_requested(tmp_path, capsys):
    existing = tmp_path / "b.wav"
    existing.write_bytes(b"original recording")
    assert main(["demo", "--output", str(tmp_path)]) == 2
    assert "--force" in capsys.readouterr().err
    assert existing.read_bytes() == b"original recording"
    assert not (tmp_path / "a.wav").exists()
    assert main(["demo", "--output", str(tmp_path), "--force"]) == 0
    assert existing.read_bytes() != b"original recording"


def test_extreme_window_is_a_clear_input_error(capsys):
    assert main(["trace", "missing.wav", "--window", "1e308"]) == 2
    assert "Window" in capsys.readouterr().err


@pytest.mark.parametrize("kind, expected_code", [("silence", 2), ("periodic", 1)])
def test_unsuccessful_match_exit_codes_and_artifacts(tmp_path, capsys, kind, expected_code):
    rate = 1000
    time = np.arange(400 * rate) / rate
    samples = np.zeros(time.size)
    if kind == "periodic":
        frequency = 50 + 0.04 * np.sin(2 * np.pi * time / 40)
        samples = 0.5 * np.sin(2 * np.pi * np.cumsum(frequency) / rate)
    clip = tmp_path / "clip.wav"
    sf.write(clip, samples, rate)
    output = tmp_path / "result"
    assert main(["match", str(clip), str(clip), "--output", str(output)]) == expected_code
    captured = capsys.readouterr()
    if kind == "silence":
        assert "Not enough valid, changing hum" in captured.err
        assert not output.exists()
    else:
        result = json.loads(captured.out)
        assert not result["accepted"]
        assert "ambiguous" in result["reason"]
        assert (output / "match.json").is_file()
        assert (output / "match.png").is_file()


def test_trace_command_writes_machine_readable_trace_and_plot(tmp_path, capsys):
    rate = 1000
    time = np.arange(40 * rate) / rate
    clip = tmp_path / "hum.wav"
    sf.write(clip, 0.2 * np.sin(2 * np.pi * 50.025 * time), rate)
    output = tmp_path / "trace"

    assert main(["trace", str(clip), "--output", str(output)]) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["valid_frames"] == 25
    with (output / "trace.csv").open() as file:
        rows = list(csv.DictReader(file))
    assert abs(float(rows[0]["frequency_hz"]) - 50.025) < 0.001
    assert (output / "trace.png").read_bytes().startswith(b"\x89PNG")
    assert json.loads((output / "summary.json").read_text()) == summary


def test_missing_audio_returns_a_clear_error(tmp_path, capsys):
    assert main(["trace", str(tmp_path / "missing.wav")]) == 2
    assert "Audio file not found" in capsys.readouterr().err


def test_silence_writes_a_rejected_trace_instead_of_a_timestamp(tmp_path, capsys):
    clip = tmp_path / "silence.wav"
    sf.write(clip, np.zeros(20000), 1000)
    output = tmp_path / "trace"
    assert main(["trace", str(clip), "--output", str(output)]) == 1
    assert json.loads(capsys.readouterr().out)["valid_frames"] == 0
    assert (output / "trace.csv").is_file()


def test_demo_recovers_known_offset_through_audio_files(tmp_path, capsys):
    output = tmp_path / "demo"
    assert main(["demo", "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["synthetic"] is True
    assert result["expected_offset_s"] == 37
    assert result["offset_s"] == 37
    assert result["accepted"] is True
    assert result["correlation"] > 0.99
    assert result["max_trace_error_hz"] < 0.005
    assert (output / "match.png").read_bytes().startswith(b"\x89PNG")

    assert (
        main(
            [
                "match",
                str(output / "a.wav"),
                str(output / "b.wav"),
                "--output",
                str(tmp_path / "match"),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["offset_s"] == 37

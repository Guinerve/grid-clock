import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from grid_clock.audio import load_audio


@pytest.mark.parametrize("extension", ["wav", "flac"])
def test_loads_stereo_without_cancelling_opposite_phase_hum(tmp_path, extension):
    time = np.arange(2000) / 1000
    hum = 0.5 * np.sin(2 * np.pi * 50 * time)
    path = tmp_path / f"clip.{extension}"
    sf.write(path, np.column_stack([hum, -hum]), 1000)
    audio = load_audio(path)
    assert audio.sample_rate == 1000
    assert audio.channel == 0
    np.testing.assert_allclose(audio.samples, hum, atol=4e-5)


def test_can_select_a_specific_audio_channel(tmp_path):
    stereo = np.column_stack([np.zeros(2000), np.full(2000, 0.4)])
    path = tmp_path / "clip.wav"
    sf.write(path, stereo, 1000)
    audio = load_audio(path, channel=1)
    assert audio.channel == 1
    np.testing.assert_allclose(audio.samples, 0.4, atol=4e-5)
    with pytest.raises(ValueError, match="Channel"):
        load_audio(path, channel=2)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="M4A decoding needs ffmpeg")
def test_decodes_real_m4a_through_ffmpeg(tmp_path):
    rate = 16000
    time = np.arange(2 * rate) / rate
    source = tmp_path / "source.wav"
    encoded = tmp_path / "clip.m4a"
    sf.write(source, 0.5 * np.sin(2 * np.pi * 50 * time), rate)
    subprocess.run(
        [shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-i", str(source), str(encoded)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    audio = load_audio(encoded)
    assert audio.sample_rate == rate
    assert abs(audio.samples.size / rate - 2) < 0.1
    frequency = np.fft.rfftfreq(audio.samples.size, 1 / rate)
    peak = np.argmax(np.abs(np.fft.rfft(audio.samples)))
    assert abs(frequency[peak] - 50) < 1


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="M4A decoding needs ffmpeg")
def test_ffmpeg_decode_allows_rf64_so_long_recordings_are_not_truncated(tmp_path, monkeypatch):
    # A plain WAV header holds at most 4 GiB. ffmpeg then writes a broken size and
    # soundfile silently reads a shorter clip (6000 s of stereo read back as 5592 s).
    rate = 8000
    source = tmp_path / "source.wav"
    encoded = tmp_path / "clip.m4a"
    sf.write(source, 0.5 * np.sin(2 * np.pi * 50 * np.arange(rate) / rate), rate)
    subprocess.run(
        [shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-i", str(source), str(encoded)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    commands = []
    real_run = subprocess.run

    def recording_run(command, **kwargs):
        commands.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    load_audio(encoded)
    [command] = commands
    position = command.index("-rf64")
    assert command[position + 1] == "auto"

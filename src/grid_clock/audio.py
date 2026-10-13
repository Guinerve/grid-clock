"""Decode audio without executing shell input or mixing stereo channels."""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from numpy.typing import NDArray


@dataclass(frozen=True)
class Audio:
    samples: NDArray[np.float64]
    sample_rate: int
    channel: int


def load_audio(path: str | Path, *, channel: int | None = None) -> Audio:
    """Use the highest-RMS channel by default; never average away phase-inverted hum."""
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(f"Audio file not found: {path}")
    try:
        samples, rate = sf.read(path, dtype="float64", always_2d=True)
    except sf.LibsndfileError as error:
        decoder = shutil.which("ffmpeg")
        if decoder is None:
            raise ValueError(
                "Cannot decode this audio file. M4A/AAC needs ffmpeg on PATH."
            ) from error
        with tempfile.TemporaryDirectory(prefix="grid-clock-") as directory:
            decoded = Path(directory) / "decoded.wav"
            try:
                subprocess.run(
                    [
                        decoder,
                        "-nostdin",
                        "-v",
                        "error",
                        "-i",
                        str(path),
                        "-map",
                        "0:a:0",
                        "-vn",
                        "-c:a",
                        "pcm_f64le",
                        # A plain WAV header stops at 4 GiB (about 93 minutes of
                        # 48 kHz stereo). Past that, soundfile reads a shorter clip.
                        "-rf64",
                        "auto",
                        str(decoded),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
            except subprocess.CalledProcessError as decode_error:
                raise ValueError("ffmpeg could not decode an audio stream from this file.") from (
                    decode_error
                )
            except subprocess.TimeoutExpired as decode_error:
                raise ValueError("Audio decoding exceeded the 120-second limit.") from decode_error
            samples, rate = sf.read(decoded, dtype="float64", always_2d=True)
    if not samples.size or not np.all(np.isfinite(samples)):
        raise ValueError("Audio must contain finite samples.")
    if channel is None:
        channel = int(np.argmax(np.mean(samples**2, axis=0)))
    if not isinstance(channel, int) or not 0 <= channel < samples.shape[1]:
        raise ValueError(f"Channel must be between 0 and {samples.shape[1] - 1}.")
    return Audio(samples[:, channel], int(rate), channel)

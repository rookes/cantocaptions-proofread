"""Report clips line up with the subtitles even when the container delays its audio (some dubs
start their audio a second or more after the video)."""
import shutil
import subprocess

import numpy as np
import pytest

from ccp import report

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")


def _delayed(tmp_path):
    """Video from 0 s; a tone muxed to start at 1.0 s."""
    media = tmp_path / "delayed.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=3:s=160x120:r=25",
                    "-itsoffset", "1", "-f", "lavfi", "-i", "sine=f=1000:d=2", "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(media)], check=True)
    return str(media)


def _duration_and_onset(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    a = np.frombuffer(raw, dtype=np.float32)
    return len(a) / 16000, np.argmax(np.abs(a) > 0.05) / 16000


@pytest.mark.parametrize("video", [False, True])
@pytest.mark.parametrize("start, end", [(0.2, 2.2), (1.5, 2.5)])
def test_clip_keeps_the_audio_delay(tmp_path, start, end, video):
    media = _delayed(tmp_path)
    delay = report.audio_delay(media, 0)
    assert delay == pytest.approx(1.0, abs=0.01)
    out = tmp_path / f"clip.{'mp4' if video else 'm4a'}"
    assert report._clip(media, 0, start, end, out, video, delay) is None
    dur, onset = _duration_and_onset(out)
    assert dur == pytest.approx(end - start, abs=0.05)
    assert onset == pytest.approx(max(1.0 - start, 0.0), abs=0.03)    # the tone where the subtitles expect it

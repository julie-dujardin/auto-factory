import sys
import time
from pathlib import Path

import pytest

from auto_factory.control import recording
from auto_factory.control.recording import record, video_time


def test_video_time_reads_as_hours_minutes_seconds() -> None:
    assert video_time(0) == "00:00:00.0"
    assert video_time(59.96) == "00:01:00.0"
    assert video_time(3725.3) == "01:02:05.3"


@pytest.fixture
def linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recording.sys, "platform", "linux")
    monkeypatch.setattr(recording.shutil, "which", lambda _: "/usr/bin/ffmpeg")


def fake_ffmpeg(monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    monkeypatch.setattr(
        recording,
        "ffmpeg_command",
        lambda display, path: [sys.executable, "-c", script, str(path)],
    )


@pytest.mark.usefixtures("linux")
def test_display_recording_clock_starts_with_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_ffmpeg(
        monkeypatch,
        "import sys, time; open(sys.argv[1], 'wb').write(b'ftyp'); time.sleep(30)",
    )
    path = tmp_path / "recordings/run.mp4"

    with record(path) as clock:
        time.sleep(0.2)
        elapsed = clock()

    assert path.read_bytes() == b"ftyp"
    assert "00:00:00.2" <= elapsed < "00:00:02.0"


@pytest.mark.usefixtures("linux")
def test_display_recording_reports_ffmpeg_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_ffmpeg(monkeypatch, "import sys; sys.exit(':99: cannot open display')")

    with (
        pytest.raises(RuntimeError, match="cannot open display"),
        record(tmp_path / "run.mp4"),
    ):
        pass

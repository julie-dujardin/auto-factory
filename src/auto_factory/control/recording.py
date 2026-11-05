from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from typing import Any

from .computer import factorio_window, screen_capture
from .display import stop

FRAME_RATE = 30
BIT_RATE = 3_000_000
# Players seek to keyframes, and a killed run loses at most one interval.
KEYFRAME_INTERVAL = 2 * FRAME_RATE
START_TIMEOUT = 10.0
STOP_TIMEOUT = 30.0


def video_time(seconds: float) -> str:
    tenths = round(max(seconds, 0.0) * 10)
    hours, tenths = divmod(tenths, 36000)
    minutes, tenths = divmod(tenths, 600)
    return f"{hours:02}:{minutes:02}:{tenths / 10:04.1f}"


@contextmanager
def record(path: Path) -> Generator[Callable[[], str]]:
    """Record the game as HEVC to path while the block runs, and give a clock that
    reads the video's current time."""
    path.parent.mkdir(parents=True, exist_ok=True)
    capture = _record_window if sys.platform == "darwin" else _record_display
    with capture(path) as started:
        yield lambda: video_time(time.monotonic() - started)


def ffmpeg_command(display: str, path: Path) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-f",
        "x11grab",
        "-framerate",
        str(FRAME_RATE),
        "-i",
        display,
        "-c:v",
        "libx265",
        "-preset",
        "ultrafast",
        "-b:v",
        str(BIT_RATE),
        "-g",
        str(KEYFRAME_INTERVAL),
        "-x265-params",
        "log-level=error",
        "-pix_fmt",
        "yuv420p",
        # QuickTime only plays HEVC tagged hvc1.
        "-tag:v",
        "hvc1",
        # Fragments keep the file playable when the run dies before closing it.
        "-movflags",
        "+frag_keyframe+empty_moov+default_base_moof",
        str(path),
    ]


@contextmanager
def _record_display(path: Path) -> Generator[float]:
    """Record the isolated X display with ffmpeg; gives when recording started."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not installed.")
    display = os.environ.get("AUTO_FACTORY_DISPLAY", ":99")
    with tempfile.TemporaryFile() as log:
        ffmpeg = subprocess.Popen(
            ffmpeg_command(display, path),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=log,
        )
        # The first frame lands a fraction of a second after launch.
        started = time.monotonic()
        try:
            while not (path.exists() and path.stat().st_size):
                if ffmpeg.poll() is not None:
                    log.seek(0)
                    error = log.read().decode(errors="replace").strip()
                    raise RuntimeError(f"ffmpeg could not record {display}: {error}")
                if time.monotonic() - started > START_TIMEOUT:
                    raise RuntimeError("ffmpeg did not start writing the recording.")
                time.sleep(0.05)
            yield started
        finally:
            stop(ffmpeg)


@contextmanager
def _record_window(path: Path) -> Generator[float]:
    """Record the Factorio window with ScreenCaptureKit, even when other windows
    cover it; gives when recording started."""
    quartz = screen_capture()
    window_id = factorio_window(quartz)
    # PyObjC creates framework symbols lazily, out of type checkers' sight.
    av: Any = importlib.import_module("AVFoundation")
    core_media: Any = importlib.import_module("CoreMedia")
    foundation: Any = importlib.import_module("Foundation")
    sck: Any = importlib.import_module("ScreenCaptureKit")

    (content,) = _wait(
        lambda done: (
            sck.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
                True, False, done
            )
        ),
        "list windows",
    )
    window = next(
        (each for each in content.windows() if each.windowID() == window_id), None
    )
    if window is None:
        raise RuntimeError("ScreenCaptureKit cannot see the Factorio window.")
    size = window.frame().size
    # One pixel per point, as for the agent's screenshots; HEVC needs even sizes.
    width, height = int(size.width) // 2 * 2, int(size.height) // 2 * 2

    writer, error = av.AVAssetWriter.alloc().initWithURL_fileType_error_(
        foundation.NSURL.fileURLWithPath_(str(path)), av.AVFileTypeMPEG4, None
    )
    if writer is None:
        raise RuntimeError(f"Could not create {path}: {_describe(error)}")
    # Fragments keep the file playable when the run dies before closing it.
    writer.setMovieFragmentInterval_(
        core_media.CMTimeMake(KEYFRAME_INTERVAL, FRAME_RATE)
    )
    video = av.AVAssetWriterInput.alloc().initWithMediaType_outputSettings_(
        av.AVMediaTypeVideo,
        {
            av.AVVideoCodecKey: av.AVVideoCodecTypeHEVC,
            av.AVVideoWidthKey: width,
            av.AVVideoHeightKey: height,
            av.AVVideoCompressionPropertiesKey: {
                av.AVVideoAverageBitRateKey: BIT_RATE,
                av.AVVideoExpectedSourceFrameRateKey: FRAME_RATE,
                av.AVVideoMaxKeyFrameIntervalKey: KEYFRAME_INTERVAL,
            },
        },
    )
    video.setExpectsMediaDataInRealTime_(True)
    writer.addInput_(video)
    if not writer.startWriting():
        raise RuntimeError(f"Could not write {path}: {_describe(writer.error())}")

    frames = _frame_writer().alloc().init()
    frames.writer = writer
    frames.video = video
    frames.lock = threading.Lock()
    frames.started = threading.Event()
    frames.closed = False
    frames.error = None

    settings = sck.SCStreamConfiguration.alloc().init()
    settings.setWidth_(width)
    settings.setHeight_(height)
    settings.setMinimumFrameInterval_(core_media.CMTimeMake(1, FRAME_RATE))
    settings.setPixelFormat_(quartz.kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange)
    settings.setShowsCursor_(False)
    stream = sck.SCStream.alloc().initWithFilter_configuration_delegate_(
        sck.SCContentFilter.alloc().initWithDesktopIndependentWindow_(window),
        settings,
        None,
    )
    added, error = stream.addStreamOutput_type_sampleHandlerQueue_error_(
        frames, sck.SCStreamOutputTypeScreen, None, None
    )
    if not added:
        raise RuntimeError(f"Could not capture the window: {_describe(error)}")

    _wait(stream.startCaptureWithCompletionHandler_, "start capturing the window")
    try:
        if not frames.started.wait(START_TIMEOUT):
            raise RuntimeError("ScreenCaptureKit sent no frame of the window.")
        yield frames.started_at
    finally:
        try:
            _wait(stream.stopCaptureWithCompletionHandler_, "stop capturing")
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
        with frames.lock:
            frames.closed = True
        video.markAsFinished()
        finished = threading.Event()
        writer.finishWritingWithCompletionHandler_(finished.set)
        if not finished.wait(STOP_TIMEOUT):
            print(f"Timed out finishing {path}.", file=sys.stderr)
        elif writer.status() != av.AVAssetWriterStatusCompleted:
            print(f"Recording failed: {_describe(writer.error())}", file=sys.stderr)
        if frames.error is not None:
            print(f"Recording dropped frames: {frames.error}", file=sys.stderr)


def _describe(error: Any) -> str:
    return "unknown error" if error is None else str(error.localizedDescription())


def _wait(start: Callable[[Callable[..., None]], None], action: str) -> list[Any]:
    """Run a ScreenCaptureKit call that reports through a completion handler, and
    give the values the handler got before its error."""
    finished = threading.Event()
    received: list[Any] = []

    def done(*values: Any) -> None:
        received.extend(values)
        finished.set()

    start(done)
    if not finished.wait(START_TIMEOUT):
        raise RuntimeError(f"Timed out waiting to {action}.")
    *values, error = received
    if error is not None:
        raise RuntimeError(f"Could not {action}: {_describe(error)}")
    return values


@cache
def _frame_writer() -> Any:
    """The SCStreamOutput class that appends complete frames to an AVAssetWriter;
    Objective-C classes can only be defined once per process."""
    objc: Any = importlib.import_module("objc")
    core_media: Any = importlib.import_module("CoreMedia")
    foundation: Any = importlib.import_module("Foundation")
    sck: Any = importlib.import_module("ScreenCaptureKit")

    class AutoFactoryFrameWriter(
        foundation.NSObject, protocols=[objc.protocolNamed("SCStreamOutput")]
    ):
        def stream_didOutputSampleBuffer_ofType_(
            self, stream: Any, buffer: Any, kind: int
        ) -> None:
            # An exception escaping to ScreenCaptureKit's queue would kill the run.
            try:
                attachments = core_media.CMSampleBufferGetSampleAttachmentsArray(
                    buffer, False
                )
                # Idle frames, sent while the window is unchanged, carry no image.
                if (
                    not attachments
                    or attachments[0].get(sck.SCStreamFrameInfoStatus)
                    != sck.SCFrameStatusComplete
                ):
                    return
                with self.lock:
                    if self.closed:
                        return
                    if not self.started.is_set():
                        self.writer.startSessionAtSourceTime_(
                            core_media.CMSampleBufferGetPresentationTimeStamp(buffer)
                        )
                        self.started_at = time.monotonic()
                        self.started.set()
                    if self.video.isReadyForMoreMediaData():
                        self.video.appendSampleBuffer_(buffer)
            except Exception as exc:
                self.error = exc

    return AutoFactoryFrameWriter

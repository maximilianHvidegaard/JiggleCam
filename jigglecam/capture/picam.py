"""Small Picamera2 helpers shared by capture sources."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

# libcamera AfMode values (controls.AfModeEnum). picamera2 accepts plain ints.
AF_MANUAL = 0
AF_CONTINUOUS = 2


class CameraUnavailable(RuntimeError):
    pass


def check_camera_index(Picamera2, index: int) -> None:
    cams = Picamera2.global_camera_info()
    if not cams:
        raise CameraUnavailable(
            "No cameras detected. Check the ribbon cable orientation and run "
            "`rpicam-hello --list-cameras`."
        )
    if index >= len(cams):
        raise CameraUnavailable(f"camera.index={index} but only {len(cams)} camera(s) found: {cams}")


def make_transform(rotate_180: bool):
    from libcamera import Transform

    return Transform(hflip=1, vflip=1) if rotate_180 else Transform()


@dataclass
class FrameRateMeter:
    """Counts frames delivered by the camera. Attach with attach(picam2).

    picam2.post_callback runs for every completed request, so this measures
    the real camera frame rate, independent of how often the UI repaints.
    """

    _count: int = 0
    _last_count: int = 0
    _last_time: float = 0.0

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._last_time = time.monotonic()

    def attach(self, picam2) -> None:
        picam2.post_callback = self._on_frame

    def _on_frame(self, _request) -> None:
        with self._lock:
            self._count += 1

    def sample(self) -> float:
        """Frames per second since the previous call to sample()."""
        now = time.monotonic()
        with self._lock:
            count = self._count
        dt = now - self._last_time
        fps = (count - self._last_count) / dt if dt > 0 else 0.0
        self._last_count, self._last_time = count, now
        return fps

"""Open and configure a single Picamera2 camera for live preview.

Phase 2 will wrap this behind CaptureSource (preview stream + 4-frame
capture). For now it is a thin, explicit helper so the UI does not have to
know about libcamera configuration details.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from jigglecam.config import CameraConfig, PreviewConfig


class CameraUnavailable(RuntimeError):
    pass


def list_cameras() -> list[dict]:
    from picamera2 import Picamera2

    return Picamera2.global_camera_info()


def open_preview_camera(cam_cfg: CameraConfig, prev_cfg: PreviewConfig):
    """Return a configured (not yet started) Picamera2 instance."""
    from libcamera import Transform
    from picamera2 import Picamera2

    cams = Picamera2.global_camera_info()
    if not cams:
        raise CameraUnavailable(
            "No cameras detected. Check the ribbon cable orientation and run "
            "`rpicam-hello --list-cameras`."
        )
    if cam_cfg.index >= len(cams):
        raise CameraUnavailable(f"camera.index={cam_cfg.index} but only {len(cams)} camera(s) found: {cams}")

    picam2 = Picamera2(cam_cfg.index)
    transform = Transform(hflip=1, vflip=1) if cam_cfg.rotate_180 else Transform()
    config = picam2.create_preview_configuration(
        main={"size": (prev_cfg.width, prev_cfg.height)},
        transform=transform,
    )
    picam2.configure(config)
    return picam2


@dataclass
class FrameRateMeter:
    """Counts frames delivered by the camera. Attach with attach(picam2).

    picam2.post_callback runs on the camera thread for every completed
    request, so this measures the real camera frame rate, independent of
    how often the UI repaints.
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

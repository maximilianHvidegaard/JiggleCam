"""The CaptureSource interface: everything above the capture layer talks to this.

A source does two separate jobs:
  1. **Viewfinder.** `preview_camera` is the one Picamera2 the UI hands to its
     preview widget. With 4 cameras this is still a single chosen lens (owner
     decision), e.g. the local CSI camera, or one view of a quad HAT.
  2. **Capture.** `capture()` returns a FrameSet: N views (4) taken as close
     to the same instant as the hardware allows, with identical exposure,
     gain, white balance and focus, plus per-frame metadata.

`capture()` BLOCKS (camera mode switch + several frames), so it must never be
called on the UI thread. The CaptureController runs it on a worker thread.

Lifecycle: open() -> [UI creates the preview widget] -> start() -> capture()* -> close().
picamera2's Qt widget must exist before the camera starts, hence open/start
are separate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FrameMeta:
    view_index: int                 # 0..N-1, left to right
    camera_index: int               # physical camera that produced it
    sensor_timestamp_ns: int        # libcamera SensorTimestamp (start of exposure readout)
    exposure_time_us: int
    analogue_gain: float
    digital_gain: float | None = None
    colour_gains: tuple[float, float] | None = None  # (red, blue)
    lens_position: float | None = None               # dioptres; None = fixed focus
    colour_temperature: int | None = None
    lux: float | None = None


@dataclass(frozen=True)
class Frame:
    image: Any  # numpy uint8 array, H x W x 3, RGB channel order
    meta: FrameMeta


@dataclass(frozen=True)
class ExposureLock:
    """The settings every view of one capture shares."""
    exposure_time_us: int
    analogue_gain: float
    colour_gains: tuple[float, float]
    lens_position: float | None  # None when the camera has no autofocus


@dataclass(frozen=True)
class FrameSet:
    frames: tuple[Frame, ...]
    captured_at: datetime
    source: str                         # e.g. "single_camera_burst"
    lock: ExposureLock
    lock_verified: bool                 # metadata confirmed the lock took effect
    extra: dict = field(default_factory=dict)  # source-specific notes, saved to set.json

    @property
    def spread_ms(self) -> float:
        """Time between first and last frame. 0 for truly simultaneous capture."""
        ts = [f.meta.sensor_timestamp_ns for f in self.frames]
        return (max(ts) - min(ts)) / 1e6


class CaptureError(RuntimeError):
    pass


class CaptureSource(ABC):
    name: str = "abstract"
    num_views: int = 4

    @abstractmethod
    def open(self) -> None:
        """Acquire and configure the camera(s). Does not start streaming."""

    @property
    @abstractmethod
    def preview_camera(self) -> Any:
        """The Picamera2 instance the viewfinder widget shows."""

    @abstractmethod
    def start(self) -> None:
        """Start the viewfinder stream."""

    @abstractmethod
    def capture(self) -> FrameSet:
        """Blocking. Lock exposure/WB/focus, grab all views, return to preview."""

    @abstractmethod
    def close(self) -> None:
        """Stop and release all cameras. Safe to call more than once."""

    def info(self) -> dict[str, str]:
        """Human-readable facts for the settings screen (label -> value)."""
        return {"Source": self.name, "Views": str(self.num_views)}

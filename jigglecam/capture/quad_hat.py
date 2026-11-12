"""QuadHatSource: STUB (phase 6). 4 sensors on one CSI port via a quad-camera HAT.

How it would work (Arducam CamArray style):
  - The HAT merges the 4 sensors into ONE libcamera camera that outputs one
    combined frame (typically 4 views side by side or 2x2). All views share
    one frame start, so **sync comes from the hardware**. No software sync is needed.
  - capture(): one request -> split the combined image into 4 views by the
    known layout. All views share one metadata dict, so one ExposureLock
    covers them automatically.
  - Viewfinder: crop one view (owner decision: the viewfinder shows one lens)
    from the combined stream. Needs a custom preview widget or picamera2's
    overlay/crop. QPicamera2 shows the whole stream.
  - Costs: each view gets ~1/4 of the sensor bandwidth (lower per-view
    resolution), and only the sensors/driver versions Arducam supports.

To check when the hardware arrives: Pi 5 support for the specific HAT, the
combined-frame layout, and whether per-view ISP tuning differs.
"""

from __future__ import annotations

from jigglecam.capture.base import CaptureSource, FrameSet


class QuadHatSource(CaptureSource):
    name = "quad_hat"

    def __init__(self, *_args, **_kwargs):
        raise NotImplementedError("QuadHatSource is planned for phase 6 (hardware not available yet)")

    def open(self) -> None:  # pragma: no cover
        raise NotImplementedError

    @property
    def preview_camera(self):  # pragma: no cover
        raise NotImplementedError

    def start(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def capture(self) -> FrameSet:  # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover
        pass

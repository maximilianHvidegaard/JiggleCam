"""SingleCameraSource: develop the whole pipeline with one camera.

How it fakes 4 views (owner decision): a **burst of consecutive frames**.
At 30 fps that's ~33 ms between frames, ~100 ms for all 4. Slide the camera
sideways while pressing the shutter and the frames get real parallax, which
is what phase 3's alignment needs to be tested properly.

Capture sequence (runs on a worker thread, never the UI thread):
  1. Read the current auto-exposure / AWB / autofocus result from the
     viewfinder's metadata. That becomes the ExposureLock.
  2. Switch the camera to a capture configuration (full capture size, RGB)
     with AE, AWB and AF *disabled* and the locked values set explicitly.
     The viewfinder freezes briefly during the switch; that's the shutter
     "blackout", like on a real camera.
  3. Throw away frames until the metadata shows the locked values are in
     effect (at most capture.max_settle_frames), then keep N consecutive
     frames. If the lock never shows up, capture anyway and mark the set
     lock_verified = False.
  4. Switch back to the viewfinder configuration (AE/AWB/AF automatic again).

The viewfinder and capture modes use the same 16:9 aspect, and on Camera
Module 3 the same 2x2-binned sensor mode, so exposure values carry over
1:1 and the switch is quick.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Callable

from jigglecam.capture.base import CaptureError, CaptureSource, ExposureLock, Frame, FrameMeta, FrameSet
from jigglecam.capture.picam import AF_CONTINUOUS, AF_MANUAL, check_camera_index, make_transform
from jigglecam.config import CameraConfig, CaptureConfig, PreviewConfig

EXPOSURE_TOLERANCE = 0.03  # sensor exposure is quantised to readout lines
GAIN_TOLERANCE = 0.03
COLOUR_GAIN_TOLERANCE = 0.01


def frame_meta(md: dict, view_index: int, camera_index: int) -> FrameMeta:
    cg = md.get("ColourGains")
    return FrameMeta(
        view_index=view_index,
        camera_index=camera_index,
        sensor_timestamp_ns=int(md["SensorTimestamp"]),
        exposure_time_us=int(md["ExposureTime"]),
        analogue_gain=float(md["AnalogueGain"]),
        digital_gain=float(md["DigitalGain"]) if "DigitalGain" in md else None,
        colour_gains=(float(cg[0]), float(cg[1])) if cg else None,
        lens_position=float(md["LensPosition"]) if "LensPosition" in md else None,
        colour_temperature=int(md["ColourTemperature"]) if "ColourTemperature" in md else None,
        lux=float(md["Lux"]) if "Lux" in md else None,
    )


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(abs(b), 1e-9)


def lock_applied(md: dict, lock: ExposureLock) -> bool:
    """True if this frame's metadata shows the locked settings in effect."""
    if not _close(md.get("ExposureTime", -1), lock.exposure_time_us, EXPOSURE_TOLERANCE):
        return False
    if not _close(md.get("AnalogueGain", -1), lock.analogue_gain, GAIN_TOLERANCE):
        return False
    cg = md.get("ColourGains")
    if cg is None or not all(_close(a, b, COLOUR_GAIN_TOLERANCE) for a, b in zip(cg, lock.colour_gains)):
        return False
    return True


class SingleCameraSource(CaptureSource):
    name = "single_camera_burst"

    def __init__(
        self,
        camera: CameraConfig,
        preview: PreviewConfig,
        capture: CaptureConfig,
        picamera2_factory: Callable[[int], Any] | None = None,
    ):
        self._cam_cfg = camera
        self._prev_cfg = preview
        self._cap_cfg = capture
        self._factory = picamera2_factory
        self.num_views = capture.views
        self._picam2 = None
        self._has_af = False
        self._preview_config = None
        self._busy = threading.Lock()

    # -- lifecycle -----------------------------------------------------------
    def open(self) -> None:
        if self._factory is None:
            from picamera2 import Picamera2

            check_camera_index(Picamera2, self._cam_cfg.index)
            factory = Picamera2
        else:
            factory = self._factory
        picam2 = factory(self._cam_cfg.index)
        self._picam2 = picam2
        self._has_af = "AfMode" in picam2.camera_controls

        controls: dict[str, Any] = {"AeEnable": True, "AwbEnable": True}
        if self._has_af:
            controls["AfMode"] = AF_CONTINUOUS
        self._preview_config = picam2.create_preview_configuration(
            main={"size": (self._prev_cfg.width, self._prev_cfg.height)},
            transform=self._transform(),
            controls=controls,
        )
        picam2.configure(self._preview_config)

    @property
    def preview_camera(self):
        if self._picam2 is None:
            raise CaptureError("source not opened")
        return self._picam2

    @property
    def has_autofocus(self) -> bool:
        return self._has_af

    def start(self) -> None:
        self.preview_camera.start()

    def close(self) -> None:
        if self._picam2 is not None:
            try:
                self._picam2.stop()
            finally:
                self._picam2.close()
                self._picam2 = None

    # -- capture -------------------------------------------------------------
    def read_lock(self) -> ExposureLock:
        """Freeze whatever auto exposure/WB/focus has settled on right now."""
        md = self.preview_camera.capture_metadata()
        cg = md.get("ColourGains") or (1.0, 1.0)
        return ExposureLock(
            exposure_time_us=int(md["ExposureTime"]),
            analogue_gain=float(md["AnalogueGain"]),
            colour_gains=(float(cg[0]), float(cg[1])),
            lens_position=float(md["LensPosition"]) if self._has_af and "LensPosition" in md else None,
        )

    def _lock_controls(self, lock: ExposureLock) -> dict[str, Any]:
        controls: dict[str, Any] = {
            "AeEnable": False,
            "AwbEnable": False,
            "ExposureTime": lock.exposure_time_us,
            "AnalogueGain": lock.analogue_gain,
            "ColourGains": lock.colour_gains,
        }
        if self._has_af and lock.lens_position is not None:
            controls["AfMode"] = AF_MANUAL
            controls["LensPosition"] = lock.lens_position
        return controls

    def capture(self) -> FrameSet:
        if not self._busy.acquire(blocking=False):
            raise CaptureError("capture already in progress")
        try:
            return self._capture_locked()
        finally:
            self._busy.release()

    def _capture_locked(self) -> FrameSet:
        picam2 = self.preview_camera
        captured_at = datetime.now()
        lock = self.read_lock()
        capture_config = picam2.create_video_configuration(
            # BGR888 in libcamera naming = R,G,B byte order in memory: an RGB array.
            main={"size": (self._cap_cfg.width, self._cap_cfg.height), "format": "BGR888"},
            buffer_count=self.num_views + 2,
            transform=self._transform(),
            controls=self._lock_controls(lock),
        )
        frames: list[Frame] = []
        verified = False
        discarded = 0
        try:
            picam2.switch_mode(capture_config)
            while len(frames) < self.num_views:
                request = picam2.capture_request()
                try:
                    md = request.get_metadata()
                    if not verified:
                        if lock_applied(md, lock):
                            verified = True
                        elif discarded < self._cap_cfg.max_settle_frames:
                            discarded += 1
                            continue
                    image = request.make_array("main")
                finally:
                    request.release()
                frames.append(Frame(image=image, meta=frame_meta(md, len(frames), self._cam_cfg.index)))
        except CaptureError:
            raise
        except Exception as exc:
            raise CaptureError(f"capture failed: {type(exc).__name__}: {exc}") from exc
        finally:
            try:
                picam2.switch_mode(self._preview_config)
            except Exception as exc:  # viewfinder dead is worse than a lost shot
                raise CaptureError(f"could not return to viewfinder: {exc}") from exc

        return FrameSet(
            frames=tuple(frames),
            captured_at=captured_at,
            source=self.name,
            lock=lock,
            lock_verified=verified,
            extra={"settle_frames_discarded": discarded},
        )

    def _transform(self):
        if self._factory is not None and not self._cam_cfg.rotate_180:
            return None  # tests with a fake camera: no libcamera import needed
        return make_transform(self._cam_cfg.rotate_180)

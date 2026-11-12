"""SingleCameraSource burst + exposure lock, against a fake camera."""

import pytest

from jigglecam.capture.base import CaptureError
from jigglecam.capture.picam import AF_MANUAL
from jigglecam.capture.single import SingleCameraSource
from jigglecam.config import CameraConfig, CaptureConfig, PreviewConfig
from tests.fakes import AUTO_MD, FakePicamera2


def make(**fake_kw):
    fake = FakePicamera2(**fake_kw)
    src = SingleCameraSource(CameraConfig(), PreviewConfig(), CaptureConfig(width=64, height=36),
                             picamera2_factory=lambda _i: fake)
    src.open()
    src.start()
    return src, fake


def test_burst_locks_and_returns_to_preview():
    src, fake = make(settle_frames=2)
    fs = src.capture()
    assert len(fs.frames) == 4
    assert fs.lock_verified
    assert fs.extra["settle_frames_discarded"] == 2
    # every kept frame shows the locked values
    for f in fs.frames:
        assert f.meta.exposure_time_us == AUTO_MD["ExposureTime"]
        assert f.meta.analogue_gain == AUTO_MD["AnalogueGain"]
    assert [f.meta.view_index for f in fs.frames] == [0, 1, 2, 3]
    # consecutive frames, ~33 ms apart -> ~100 ms spread
    assert 95 < fs.spread_ms < 105
    assert fs.frames[0].image.shape == (36, 64, 3)
    assert fake.modes_seen == ["preview", "video", "preview"]


def test_capture_mode_disables_auto_and_locks_focus():
    src, fake = make()
    src.capture()
    assert fake.mode["kind"] == "preview"  # back in the viewfinder, auto again
    assert fake.mode["controls"]["AeEnable"] is True
    lock_cfg = src._lock_controls(src.read_lock())
    assert lock_cfg["AeEnable"] is False and lock_cfg["AwbEnable"] is False
    assert lock_cfg["AfMode"] == AF_MANUAL and lock_cfg["LensPosition"] == AUTO_MD["LensPosition"]


def test_fixed_focus_camera_has_no_af_controls():
    src, _ = make(has_af=False)
    lock = src.read_lock()
    assert lock.lens_position is None
    assert "AfMode" not in src._lock_controls(lock)


def test_unverified_lock_still_captures():
    src, _ = make(never_settle=True)
    fs = src.capture()
    assert len(fs.frames) == 4
    assert not fs.lock_verified
    assert fs.extra["settle_frames_discarded"] == CaptureConfig().max_settle_frames


def test_failure_raises_and_restores_viewfinder():
    src, fake = make(fail_after=3)
    with pytest.raises(CaptureError, match="sensor fell over"):
        src.capture()
    assert fake.mode["kind"] == "preview"
    # and the source is usable again afterwards
    fake.fail_after = None
    assert len(src.capture().frames) == 4

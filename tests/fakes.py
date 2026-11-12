"""A fake Picamera2, so capture logic can be tested without a camera."""

from __future__ import annotations

import numpy as np

AUTO_MD = {"ExposureTime": 10000, "AnalogueGain": 2.0, "ColourGains": (1.8, 1.5), "LensPosition": 1.25,
           "DigitalGain": 1.0, "ColourTemperature": 4500, "Lux": 300.0}


class FakeRequest:
    def __init__(self, md, size):
        self._md = md
        self._size = size
        self.released = False

    def get_metadata(self):
        return dict(self._md)

    def make_array(self, _name):
        w, h = self._size
        return np.full((h, w, 3), self._md["SensorTimestamp"] % 255, dtype=np.uint8)

    def release(self):
        self.released = True


class FakePicamera2:
    """settle_frames: how many frames after a mode switch still show the old (auto) values.
    never_settle: the lock never shows up in metadata. fail_after: raise on the Nth request."""

    def __init__(self, index=0, *, settle_frames=2, has_af=True, never_settle=False, fail_after=None):
        self.index = index
        self.camera_controls = {"AfMode": (0, 2, 0)} if has_af else {}
        self.settle_frames = settle_frames
        self.never_settle = never_settle
        self.fail_after = fail_after
        self.mode = None
        self.modes_seen = []
        self.started = False
        self.closed = False
        self._ts = 1_000_000_000
        self._since_switch = 0
        self._requests = 0
        self.post_callback = None

    def create_preview_configuration(self, **kw):
        return {"kind": "preview", **kw}

    def create_video_configuration(self, **kw):
        return {"kind": "video", **kw}

    def configure(self, cfg):
        self.mode = cfg
        self.modes_seen.append(cfg["kind"])

    def switch_mode(self, cfg):
        self.configure(cfg)
        self._since_switch = 0

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True

    def capture_metadata(self):
        self._ts += 33_333_000
        return {**AUTO_MD, "SensorTimestamp": self._ts}

    def capture_request(self):
        self._requests += 1
        if self.fail_after is not None and self._requests > self.fail_after:
            raise RuntimeError("sensor fell over")
        self._ts += 33_333_000
        self._since_switch += 1
        md = {**AUTO_MD, "SensorTimestamp": self._ts}
        controls = self.mode.get("controls", {})
        settled = not self.never_settle and self._since_switch > self.settle_frames
        if settled and controls.get("AeEnable") is False:
            md.update(ExposureTime=controls["ExposureTime"], AnalogueGain=controls["AnalogueGain"],
                      ColourGains=controls["ColourGains"])
        elif controls.get("AeEnable") is False:
            md.update(ExposureTime=20000, AnalogueGain=4.0)  # still drifting
        return FakeRequest(md, self.mode["main"]["size"])

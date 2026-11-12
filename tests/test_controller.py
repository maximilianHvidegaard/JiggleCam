"""CaptureController: non-blocking shutter, busy handling, event order."""

import threading

from jigglecam.config import StorageConfig
from jigglecam.controller import CaptureController
from jigglecam.storage import SetStore
from tests.test_storage import frameset


class SlowSource:
    name = "fake"

    def __init__(self, fail=False):
        self.release = threading.Event()
        self.fail = fail

    def capture(self):
        self.release.wait(5)
        if self.fail:
            raise RuntimeError("boom")
        return frameset()


def run(source, tmp_path):
    events, done = [], threading.Event()

    def on_event(ev):
        events.append(ev)
        if ev.kind in ("saved", "failed"):
            done.set()

    ctl = CaptureController(source, SetStore(StorageConfig(root=str(tmp_path))), on_event)
    return ctl, events, done


def test_trigger_returns_immediately_and_saves(tmp_path):
    src = SlowSource()
    ctl, events, done = run(src, tmp_path)
    assert ctl.trigger() is True          # returns while capture is still blocked
    assert ctl.trigger() is False         # second press while busy is refused
    src.release.set()
    assert done.wait(5)
    ctl.shutdown()
    kinds = [e.kind for e in events]
    assert kinds == ["busy", "started", "captured", "saved"] or kinds == ["started", "busy", "captured", "saved"]
    assert events[-1].detail.path.exists()


def test_failure_reported_and_shutter_rearmed(tmp_path):
    src = SlowSource(fail=True)
    src.release.set()
    ctl, events, done = run(src, tmp_path)
    ctl.trigger()
    assert done.wait(5)
    ctl.shutdown()
    assert events[-1].kind == "failed" and "boom" in events[-1].detail
    assert not ctl.capturing

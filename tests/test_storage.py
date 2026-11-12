"""Set storage: folder of JPEGs + set.json."""

import json
from datetime import datetime

import numpy as np

from jigglecam.capture.base import ExposureLock, Frame, FrameMeta, FrameSet
from jigglecam.config import StorageConfig
from jigglecam.storage import FORMAT_VERSION, SetStore


def frameset(when=datetime(2026, 11, 12, 14, 3, 22), views=4):
    frames = tuple(
        Frame(np.full((36, 64, 3), 40 * i, dtype=np.uint8),
              FrameMeta(view_index=i, camera_index=0, sensor_timestamp_ns=1_000_000 + i * 33_333_000,
                        exposure_time_us=10000, analogue_gain=2.0, colour_gains=(1.8, 1.5)))
        for i in range(views)
    )
    return FrameSet(frames=frames, captured_at=when, source="test",
                    lock=ExposureLock(10000, 2.0, (1.8, 1.5), None), lock_verified=True)


def test_save_writes_folder(tmp_path):
    store = SetStore(StorageConfig(root=str(tmp_path)))
    stored = store.save(frameset())
    assert stored.name == "2026-11-12_14-03-22"
    names = sorted(p.name for p in stored.path.iterdir())
    assert names == ["frame_1.jpg", "frame_2.jpg", "frame_3.jpg", "frame_4.jpg", "set.json", "thumb.jpg"]
    meta = json.loads((stored.path / "set.json").read_text())
    assert meta["format_version"] == FORMAT_VERSION
    assert meta["views"] == 4 and meta["size"] == [64, 36]
    assert meta["frames"][2]["view_index"] == 2
    assert meta["lock"]["exposure_time_us"] == 10000
    assert abs(meta["spread_ms"] - 100.0) < 0.01
    assert not any(p.name.startswith(".tmp") for p in tmp_path.iterdir())


def test_same_second_gets_unique_name(tmp_path):
    store = SetStore(StorageConfig(root=str(tmp_path)))
    a = store.save(frameset())
    b = store.save(frameset())
    assert a.path != b.path and b.name.endswith("_2")


def test_list_newest_first_and_skips_junk(tmp_path):
    store = SetStore(StorageConfig(root=str(tmp_path)))
    store.save(frameset(datetime(2026, 1, 1, 10, 0, 0)))
    store.save(frameset(datetime(2026, 1, 2, 10, 0, 0)))
    (tmp_path / ".tmp-crashed").mkdir()
    (tmp_path / "random-folder").mkdir()
    names = [s.name for s in store.list()]
    assert names == ["2026-01-02_10-00-00", "2026-01-01_10-00-00"]
    assert store.latest().name == "2026-01-02_10-00-00"
    assert store.latest().frame_paths[0].exists()


def test_empty_store(tmp_path):
    assert SetStore(StorageConfig(root=str(tmp_path / "missing"))).latest() is None

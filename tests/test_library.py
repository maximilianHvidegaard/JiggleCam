"""Library pieces without Qt: wiggle order, frame decoding, delete, usage."""

import pytest

from jigglecam.config import StorageConfig
from jigglecam.storage import SetStore
from jigglecam.ui.frames import decode_for_screen, wiggle_order
from tests.test_storage import frameset


def test_wiggle_order():
    assert wiggle_order(4) == [0, 1, 2, 3, 2, 1]
    assert wiggle_order(2) == [0, 1]
    assert wiggle_order(3) == [0, 1, 2, 1]


def test_decode_fits_screen(tmp_path):
    from PIL import Image

    p = tmp_path / "f.jpg"
    Image.new("RGB", (2304, 1296), (200, 10, 10)).save(p, quality=90)
    f = decode_for_screen(p, 800, 450)
    assert f.width <= 800 and f.height <= 450 and f.width >= 790
    assert len(f.rgb) == f.width * f.height * 3


def test_delete_removes_set_and_usage(tmp_path):
    store = SetStore(StorageConfig(root=str(tmp_path)))
    a = store.save(frameset())
    store.save(frameset())
    count, used = store.usage()
    assert count == 2 and used > 0
    store.delete(a)
    assert not a.path.exists()
    assert [s.name for s in store.list()] == ["2026-11-12_14-03-22_2"]
    assert not any(p.name.startswith(".trash") for p in tmp_path.iterdir())


def test_delete_refuses_paths_outside_store(tmp_path):
    store = SetStore(StorageConfig(root=str(tmp_path / "caps")))
    other = SetStore(StorageConfig(root=str(tmp_path / "elsewhere"))).save(frameset())
    with pytest.raises(ValueError):
        store.delete(other)
    assert other.path.exists()

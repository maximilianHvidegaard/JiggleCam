"""Config loading tests. Pure Python, runs on the Pi or a desktop."""

from pathlib import Path

import pytest

from jigglecam import config as cfgmod


def test_defaults_load():
    cfg = cfgmod.load()
    assert cfg.preview.backend in ("gl", "software")
    assert cfg.preview.width > 0 and cfg.preview.height > 0
    assert cfg.ui.exit_hold_ms > 0


def test_override_merges_key_by_key(tmp_path: Path):
    extra = tmp_path / "x.toml"
    extra.write_text("[preview]\nwidth = 640\n")
    cfg = cfgmod.load(extra)
    assert cfg.preview.width == 640
    assert cfg.preview.height == cfgmod.load().preview.height  # untouched key kept


def test_unknown_key_rejected(tmp_path: Path):
    extra = tmp_path / "x.toml"
    extra.write_text("[preview]\nwidht = 640\n")
    with pytest.raises(cfgmod.ConfigError, match="widht"):
        cfgmod.load(extra)


def test_bad_backend_rejected(tmp_path: Path):
    extra = tmp_path / "x.toml"
    extra.write_text('[preview]\nbackend = "vulkan"\n')
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load(extra)


def test_missing_extra_file_rejected(tmp_path: Path):
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load(tmp_path / "nope.toml")

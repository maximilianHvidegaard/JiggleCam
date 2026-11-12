"""Qt platform selection (eglfs on Pi OS Lite). Pure Python, no Qt needed."""

import json
import sys
from pathlib import Path

import pytest

from jigglecam.config import ConfigError, DisplayConfig
from jigglecam import platform_env


def _fake_drm(tmp_path: Path, connectors: dict[str, str]) -> str:
    for name, status in connectors.items():
        d = tmp_path / name
        d.mkdir()
        (d / "status").write_text(status + "\n")
    return str(tmp_path)


def test_finds_connected_card(tmp_path):
    root = _fake_drm(tmp_path, {"card1-HDMI-A-1": "disconnected", "card2-DSI-1": "connected"})
    assert platform_env.find_connected_drm_card(root) == "/dev/dri/card2"


def test_no_connected_card(tmp_path):
    root = _fake_drm(tmp_path, {"card1-HDMI-A-1": "disconnected"})
    assert platform_env.find_connected_drm_card(root) is None


def test_respects_existing_platform():
    env = {"QT_QPA_PLATFORM": "xcb"}
    assert platform_env.configure_qt_platform(DisplayConfig(), env) == {}
    assert env == {"QT_QPA_PLATFORM": "xcb"}


def test_desktop_session_left_alone():
    env = {"WAYLAND_DISPLAY": "wayland-0"}
    assert platform_env.configure_qt_platform(DisplayConfig(), env) == {}


def test_lite_uses_eglfs(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    env: dict[str, str] = {}
    cfg = DisplayConfig(kms_device="/dev/dri/card1", rotation=180)
    out = platform_env.configure_qt_platform(cfg, env)
    assert env["QT_QPA_PLATFORM"] == "eglfs"
    assert env["QT_QPA_EGLFS_ROTATION"] == "180"
    kms = json.loads(Path(env["QT_QPA_EGLFS_KMS_CONFIG"]).read_text())
    assert kms["device"] == "/dev/dri/card1"
    assert out == env


def test_bad_rotation_rejected():
    with pytest.raises(ConfigError):
        DisplayConfig(rotation=45)

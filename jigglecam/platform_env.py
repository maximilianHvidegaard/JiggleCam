"""Choose how Qt reaches the screen. Must run BEFORE any Qt import.

Decision (see CLAUDE.md): the Pi runs Raspberry Pi OS **Lite**, with no desktop
and no compositor. Qt then draws straight to the display through DRM/KMS using
its `eglfs` platform plugin and reads the touchscreen itself (libinput/evdev).

Rules:
  - If QT_QPA_PLATFORM is already set, respect it (manual override).
  - If a desktop session exists (WAYLAND_DISPLAY / DISPLAY), let Qt use it.
    That keeps `--windowed` debugging possible on a desktop machine.
  - Otherwise, on Linux, use eglfs and point it at the DRM card that has a
    connected screen. The Pi 5 exposes several /dev/dri/cardN devices (GPU
    render node vs display controller) and Qt does not always pick the right one.
"""

from __future__ import annotations

import glob
import json
import os
import sys
import tempfile
from pathlib import Path

from jigglecam.config import DisplayConfig


def find_connected_drm_card(sys_drm: str = "/sys/class/drm") -> str | None:
    """Return /dev/dri/cardN for the first connector reporting 'connected'."""
    for status_file in sorted(glob.glob(f"{sys_drm}/card*-*/status")):
        try:
            if Path(status_file).read_text().strip() == "connected":
                connector = Path(status_file).parent.name  # e.g. "card1-DSI-1"
                return f"/dev/dri/{connector.split('-', 1)[0]}"
        except OSError:
            continue
    return None


def configure_qt_platform(display: DisplayConfig, environ=os.environ) -> dict[str, str]:
    """Set Qt environment variables for this machine. Returns what was set."""
    if environ.get("QT_QPA_PLATFORM"):
        return {}
    if environ.get("WAYLAND_DISPLAY") or environ.get("DISPLAY"):
        return {}
    if not sys.platform.startswith("linux"):
        return {}

    env = {"QT_QPA_PLATFORM": "eglfs"}
    device = display.kms_device if display.kms_device != "auto" else find_connected_drm_card()
    if device:
        kms_cfg = Path(tempfile.gettempdir()) / "jigglecam-kms.json"
        kms_cfg.write_text(json.dumps({"device": device, "hwcursor": not display.hide_cursor}))
        env["QT_QPA_EGLFS_KMS_CONFIG"] = str(kms_cfg)
    if display.rotation:
        env["QT_QPA_EGLFS_ROTATION"] = str(display.rotation)
    if display.hide_cursor:
        env["QT_QPA_EGLFS_HIDECURSOR"] = "1"
    environ.update(env)
    return env

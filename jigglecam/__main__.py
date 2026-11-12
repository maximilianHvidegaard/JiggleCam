"""Entry point: `python -m jigglecam` (or the `jigglecam` command after install)."""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from jigglecam import config as config_mod


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jigglecam", description="4-camera wigglegram camera")
    p.add_argument("--config", type=Path, help="extra TOML file layered over default/local config")
    p.add_argument("--windowed", action="store_true", help="run in a window with a visible cursor (debugging)")
    p.add_argument("--software", action="store_true", help="use the CPU preview instead of GL")
    args = p.parse_args(argv)

    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as exc:
        print(f"[jigglecam] config error: {exc}", file=sys.stderr)
        return 2

    if args.windowed:
        cfg = dataclasses.replace(
            cfg, display=dataclasses.replace(cfg.display, fullscreen=False, hide_cursor=False)
        )
    if args.software:
        cfg = dataclasses.replace(cfg, preview=dataclasses.replace(cfg.preview, backend="software"))

    # Must happen before anything imports Qt (eglfs on Pi OS Lite).
    from jigglecam.platform_env import configure_qt_platform

    qt_env = configure_qt_platform(cfg.display)
    if qt_env:
        print(f"[jigglecam] Qt platform env: {qt_env}")

    from jigglecam.capture.picam import CameraUnavailable
    from jigglecam.ui.app import run

    try:
        return run(cfg)
    except (CameraUnavailable, NotImplementedError) as exc:
        print(f"[jigglecam] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

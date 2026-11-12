"""Capture layer. Owns all camera access. The UI only receives the viewfinder's
Picamera2 object to hand to picamera2's preview widget.

See base.py for the CaptureSource interface.
"""

from __future__ import annotations

from jigglecam.capture.base import CaptureError, CaptureSource, ExposureLock, Frame, FrameMeta, FrameSet
from jigglecam.config import Config

__all__ = ["CaptureError", "CaptureSource", "ExposureLock", "Frame", "FrameMeta", "FrameSet", "make_source"]


def make_source(cfg: Config) -> CaptureSource:
    if cfg.capture.source == "single":
        from jigglecam.capture.single import SingleCameraSource

        return SingleCameraSource(cfg.camera, cfg.preview, cfg.capture)
    if cfg.capture.source == "quad_hat":
        from jigglecam.capture.quad_hat import QuadHatSource

        return QuadHatSource(cfg)
    from jigglecam.capture.networked import NetworkedNodesSource

    return NetworkedNodesSource(cfg)

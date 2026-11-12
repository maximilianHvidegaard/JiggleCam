"""Capture layer. Owns all camera access; the UI never imports picamera2 directly
for anything except the preview widget.

Phase 1 only has picam.py (open one camera for live preview). Phase 2 adds
the CaptureSource interface and SingleCameraSource.
"""

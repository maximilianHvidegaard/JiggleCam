"""Phase 1 UI: fullscreen live preview + status bar + hold-to-exit button.

Layout:
    +---------------------------------------------+
    |                                             |
    |          live preview (fills space)         |
    |                                             |
    +---------------------------------------------+
    | 30.0 fps | PyQt5 (Qt 5.15) ...   [ hold ✕ ] |
    +---------------------------------------------+

The status bar sits *below* the preview rather than overlaid on it: the GL
preview is a native surface, and ordinary Qt widgets drawn on top of it
don't reliably show. Overlays (focus point, guides) will use picamera2's
set_overlay() in later phases.
"""

from __future__ import annotations

from jigglecam.capture.picam import FrameRateMeter
from jigglecam.config import Config
from jigglecam.ui import qt_compat
from jigglecam.ui.qt_compat import QShortcut, Qt, QtCore, QtGui, QtWidgets


class HoldButton(QtWidgets.QPushButton):
    """Emits `held` only after being pressed continuously for `hold_ms`."""

    held = QtCore.pyqtSignal()

    def __init__(self, text: str, hold_ms: int, parent=None):
        super().__init__(text, parent)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(hold_ms)
        self._timer.timeout.connect(self.held.emit)
        self.pressed.connect(self._timer.start)
        self.released.connect(self._timer.stop)


class PreviewWindow(QtWidgets.QWidget):
    def __init__(self, cfg: Config, picam2):
        super().__init__()
        self.setWindowTitle("JiggleCam")
        self.setStyleSheet("background: #141414; color: #ddd;")

        widget_cls = qt_compat.QGlPicamera2 if cfg.preview.backend == "gl" else qt_compat.QPicamera2
        if widget_cls is None:
            raise RuntimeError(f"picamera2 Qt preview unavailable: {qt_compat.PREVIEW_IMPORT_ERROR}")
        self.preview = widget_cls(
            picam2,
            width=cfg.preview.width,
            height=cfg.preview.height,
            keep_ar=cfg.preview.keep_aspect,
        )

        self.fps_label = QtWidgets.QLabel("-- fps")
        self.info_label = QtWidgets.QLabel(f"{cfg.preview.backend} | {qt_compat.BINDING}")
        self.info_label.setStyleSheet("color: #888;")
        exit_btn = HoldButton("hold to exit", cfg.ui.exit_hold_ms)
        exit_btn.setMinimumSize(160, 56)  # finger-sized
        exit_btn.setStyleSheet("background: #333; border-radius: 8px; padding: 8px;")
        exit_btn.held.connect(self.close)

        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(12, 4, 12, 4)
        bar.addWidget(self.fps_label)
        bar.addSpacing(16)
        bar.addWidget(self.info_label)
        bar.addStretch(1)
        bar.addWidget(exit_btn)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.preview, 1)
        root.addLayout(bar)

        # Keyboard escape hatch for debugging with a keyboard attached.
        QShortcut(QtGui.QKeySequence("Esc"), self, activated=self.close)
        QShortcut(QtGui.QKeySequence("Q"), self, activated=self.close)

        self.meter = FrameRateMeter()
        self.meter.attach(picam2)
        self._fps_timer = QtCore.QTimer(self)
        self._fps_timer.timeout.connect(self._update_fps)
        self._fps_timer.start(1000)

    def _update_fps(self) -> None:
        self.fps_label.setText(f"{self.meter.sample():.1f} fps")


def run(cfg: Config) -> int:
    from jigglecam.capture.picam import open_preview_camera

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    if cfg.display.hide_cursor:
        app.setOverrideCursor(QtGui.QCursor(Qt.CursorShape.BlankCursor))

    picam2 = open_preview_camera(cfg.camera, cfg.preview)
    try:
        win = PreviewWindow(cfg, picam2)  # widget must exist before start()
        picam2.start()
        if cfg.display.fullscreen:
            win.showFullScreen()
        else:
            win.resize(1024, 640)
            win.show()
        print(f"[jigglecam] running: {qt_compat.summary()}, platform={app.platformName()}")
        return app.exec()
    finally:
        picam2.stop()
        picam2.close()

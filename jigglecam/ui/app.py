"""Camera screen: viewfinder + right-hand side bar (owner decision).

    +----------------------------------------------+--------+
    |                                              | [hold✕]|
    |                                              | Ready  |
    |              viewfinder (one lens)           |        |
    |                                              |  (O)   |  <- shutter
    |                                              |        |
    |                                              | [thumb]|  <- last shot
    |                                              | 30 fps |
    +----------------------------------------------+--------+

Threading: the UI never waits on the camera or the SD card. The shutter
calls CaptureController.trigger(), which returns at once. Results come back
as CaptureEvents from worker threads and are moved onto the Qt thread by
the _EventBridge signal before touching any widget.
"""

from __future__ import annotations

from jigglecam.capture import CaptureSource, make_source
from jigglecam.capture.picam import FrameRateMeter
from jigglecam.config import Config
from jigglecam.controller import CaptureController, CaptureEvent
from jigglecam.storage import SetStore, StoredSet
from jigglecam.ui import qt_compat
from jigglecam.ui.qt_compat import QShortcut, Qt, QtCore, QtGui, QtWidgets

SIDEBAR_WIDTH = 112
SHUTTER_SIZE = 84
THUMB_SIZE = QtCore.QSize(96, 54)
FLASH_MS = 120


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


class _EventBridge(QtCore.QObject):
    """Carries CaptureEvents from worker threads to the Qt thread (queued signal)."""

    event = QtCore.pyqtSignal(object)


class CameraScreen(QtWidgets.QWidget):
    def __init__(self, cfg: Config, source: CaptureSource, store: SetStore, backend: str, widget_cls):
        super().__init__()
        self.setWindowTitle("JiggleCam")
        self.setStyleSheet("background: #141414; color: #ddd;")
        self.store = store

        picam2 = source.preview_camera
        self.preview = widget_cls(
            picam2, width=cfg.preview.width, height=cfg.preview.height, keep_ar=cfg.preview.keep_aspect
        )
        self.flash = QtWidgets.QWidget(self.preview)
        self.flash.setStyleSheet("background: rgba(255, 255, 255, 200);")
        self.flash.hide()

        self.bridge = _EventBridge()
        self.bridge.event.connect(self._on_event)
        self.controller = CaptureController(source, store, self.bridge.event.emit)

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.preview, 1)
        root.addWidget(self._build_sidebar(cfg, backend))

        QShortcut(QtGui.QKeySequence("Esc"), self, activated=self.close)
        QShortcut(QtGui.QKeySequence("Space"), self, activated=self.controller.trigger)

        self.meter = FrameRateMeter()
        self.meter.attach(picam2)
        self._fps_timer = QtCore.QTimer(self)
        self._fps_timer.timeout.connect(lambda: self.fps_label.setText(f"{self.meter.sample():.0f} fps"))
        self._fps_timer.start(1000)

        self._show_thumb(store.latest())

    def _build_sidebar(self, cfg: Config, backend: str) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget()
        bar.setFixedWidth(SIDEBAR_WIDTH)
        bar.setStyleSheet("background: #0c0c0c;")
        lay = QtWidgets.QVBoxLayout(bar)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        exit_btn = HoldButton("hold ✕", cfg.ui.exit_hold_ms)
        exit_btn.setFixedHeight(40)
        exit_btn.setStyleSheet("background: #262626; border-radius: 6px; color: #aaa;")
        exit_btn.held.connect(self.close)

        self.status = QtWidgets.QLabel("Ready")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.status.setStyleSheet("font-size: 13px;")

        self.shutter = QtWidgets.QPushButton()
        self.shutter.setFixedSize(SHUTTER_SIZE, SHUTTER_SIZE)
        self._style_shutter(ready=True)
        self.shutter.pressed.connect(self.controller.trigger)  # fire on touch-down: less lag

        self.thumb = QtWidgets.QLabel()
        self.thumb.setFixedSize(THUMB_SIZE)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background: #222; border-radius: 4px; color: #555; font-size: 11px;")

        self.fps_label = QtWidgets.QLabel("-- fps")
        self.fps_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.fps_label.setStyleSheet("color: #666; font-size: 11px;")
        self.fps_label.setToolTip(f"{backend} preview, {qt_compat.BINDING}")

        lay.addWidget(exit_btn)
        lay.addWidget(self.status)
        lay.addStretch(1)
        lay.addWidget(self.shutter, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)
        lay.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.fps_label)
        return bar

    def _style_shutter(self, ready: bool) -> None:
        r = SHUTTER_SIZE // 2
        fill = "#f2f2f2" if ready else "#777"
        self.shutter.setStyleSheet(
            f"QPushButton {{ background: {fill}; border: 4px solid #555; border-radius: {r}px; }}"
            f"QPushButton:pressed {{ background: #bbb; }}"
        )

    def _show_thumb(self, stored: StoredSet | None) -> None:
        if stored is None or not stored.thumb_path.exists():
            self.thumb.setText("no shots")
            return
        pix = QtGui.QPixmap(str(stored.thumb_path))
        self.thumb.setPixmap(pix.scaled(THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))

    def _flash(self) -> None:
        self.flash.setGeometry(self.preview.rect())
        self.flash.raise_()
        self.flash.show()
        QtCore.QTimer.singleShot(FLASH_MS, self.flash.hide)

    def _on_event(self, ev: CaptureEvent) -> None:
        """Runs on the Qt thread."""
        if ev.kind == "started":
            self._style_shutter(ready=False)
            self.status.setText("Capturing…")
            self._flash()
        elif ev.kind == "captured":
            self._style_shutter(ready=True)
            note = "" if ev.detail.lock_verified else "\n⚠ lock unverified"
            self.status.setText(f"Saving…\n{ev.detail.spread_ms:.0f} ms{note}")
        elif ev.kind == "saved":
            self.status.setText(f"Saved\n{ev.detail.name[-8:]}")
            self._show_thumb(ev.detail)
        elif ev.kind == "failed":
            self._style_shutter(ready=True)
            self.status.setText(f"<span style='color:#ff6b6b'>Error</span>")
            self.status.setToolTip(str(ev.detail))
            print(f"[jigglecam] {ev.detail}")

    def closeEvent(self, event) -> None:
        self.status.setText("Finishing…")
        QtWidgets.QApplication.processEvents()
        self.controller.shutdown()  # waits for the running capture and pending saves
        super().closeEvent(event)


# Qt platforms with no display server: picamera2's GL widgets need X11 or
# Wayland, so only the CPU widget can work here.
_NO_DISPLAY_SERVER = ("eglfs", "linuxfb")


def choose_preview(requested: str, platform: str) -> tuple[str, type]:
    """Pick the preview widget, falling back to software (with a log line) when GL can't work."""
    backend = requested
    if backend == "gl" and platform in _NO_DISPLAY_SERVER:
        print(f"[jigglecam] GL preview needs X11/Wayland but Qt platform is {platform!r}; "
              "using the software preview")
        backend = "software"
    widget_cls = qt_compat.preview_widget(backend)
    if widget_cls is None and backend == "gl":
        print(f"[jigglecam] GL preview unavailable ({qt_compat.preview_error('gl')}); "
              "using the software preview")
        backend = "software"
        widget_cls = qt_compat.preview_widget(backend)
    if widget_cls is None:
        raise RuntimeError(f"picamera2 Qt preview unavailable: {qt_compat.preview_error(backend)}")
    return backend, widget_cls


def run(cfg: Config) -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    if cfg.display.hide_cursor:
        app.setOverrideCursor(QtGui.QCursor(Qt.CursorShape.BlankCursor))
    backend, widget_cls = choose_preview(cfg.preview.backend, app.platformName())

    source = make_source(cfg)
    store = SetStore(cfg.storage)
    source.open()
    try:
        win = CameraScreen(cfg, source, store, backend, widget_cls)  # widget must exist before start()
        source.start()
        if cfg.display.fullscreen:
            win.showFullScreen()
        else:
            win.resize(800, 480)
            win.show()
        print(f"[jigglecam] running: {source.name}, {backend} preview, {qt_compat.BINDING} "
              f"(Qt {QtCore.QT_VERSION_STR}), platform={app.platformName()}, saving to {store.root}")
        return app.exec()
    finally:
        source.close()

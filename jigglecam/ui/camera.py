"""Camera screen: viewfinder + right-hand side bar (owner decision).

    +----------------------------------------------+--------+
    |                                              | [☰ Menu]|
    |                                              | Ready  |
    |              viewfinder (one lens)           |        |
    |                                              |  (O)   |  <- shutter
    |                                              |        |
    |                                              | [thumb]|  <- last shot (tap: open it)
    |                                              | 30 fps |
    +----------------------------------------------+--------+

"Menu" slides a panel in from the right over a dimmed viewfinder (owner
decision): Library, Settings, hold-to-exit. Tapping the dimmed area closes it.

Threading: the UI never waits on the camera or the SD card. The shutter
calls CaptureController.trigger(), which returns at once. Results come back
as CaptureEvents from worker threads and are moved onto the Qt thread by
the _EventBridge signal before touching any widget.
"""

from __future__ import annotations

from jigglecam.capture import CaptureSource
from jigglecam.capture.picam import FrameRateMeter
from jigglecam.config import Config
from jigglecam.controller import CaptureController, CaptureEvent
from jigglecam.storage import SetStore, StoredSet
from jigglecam.ui import qt_compat
from jigglecam.ui.qt_compat import Qt, QtCore, QtGui, QtWidgets
from jigglecam.ui.widgets import BAR_BG, BG, BUTTON, ClickableLabel, HoldButton, Shade, button

SIDEBAR_WIDTH = 112
SHUTTER_SIZE = 84
THUMB_SIZE = QtCore.QSize(96, 54)
FLASH_MS = 120
MENU_WIDTH = 220
MENU_ANIM_MS = 160


class _EventBridge(QtCore.QObject):
    """Carries CaptureEvents from worker threads to the Qt thread (queued signal)."""

    event = QtCore.pyqtSignal(object)


class MenuPanel(QtWidgets.QWidget):
    """Slide-over menu: covers the whole screen; a shade on the left, the panel on the right."""

    library = QtCore.pyqtSignal()
    settings = QtCore.pyqtSignal()
    quit = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget, exit_hold_ms: int):
        super().__init__(parent)
        self.hide()
        self.shade = Shade(150, self)
        self.shade.clicked.connect(self.close_menu)

        self.panel = QtWidgets.QFrame(self)
        self.panel.setStyleSheet(f"QFrame {{ background: {BAR_BG}; }}")
        lay = QtWidgets.QVBoxLayout(self.panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        close_btn = button("✕  Close", height=48)
        lib_btn = button("▦  Library", height=64)
        set_btn = button("⚙  Settings", height=64)
        exit_btn = HoldButton("hold to exit", exit_hold_ms)
        exit_btn.setFixedHeight(48)
        exit_btn.setStyleSheet(BUTTON + "color: #999;")
        exit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        close_btn.clicked.connect(self.close_menu)
        lib_btn.clicked.connect(lambda: self._pick(self.library))
        set_btn.clicked.connect(lambda: self._pick(self.settings))
        exit_btn.held.connect(self.quit.emit)

        lay.addWidget(close_btn)
        lay.addSpacing(8)
        lay.addWidget(lib_btn)
        lay.addWidget(set_btn)
        lay.addStretch(1)
        lay.addWidget(exit_btn)

        self._anim = QtCore.QPropertyAnimation(self.panel, b"pos", self)
        self._anim.setDuration(MENU_ANIM_MS)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

    def _layout(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.shade.setGeometry(self.rect())
        self.panel.setFixedSize(MENU_WIDTH, self.height())

    def open_menu(self) -> None:
        self._layout()
        self.raise_()
        self.show()
        self._anim.stop()
        self._anim.setStartValue(QtCore.QPoint(self.width(), 0))
        self._anim.setEndValue(QtCore.QPoint(self.width() - MENU_WIDTH, 0))
        self._anim.start()

    def close_menu(self) -> None:
        self._anim.stop()
        self.hide()

    def _pick(self, signal) -> None:
        self.close_menu()
        signal.emit()


class CameraScreen(QtWidgets.QWidget):
    open_library = QtCore.pyqtSignal()
    open_settings = QtCore.pyqtSignal()
    open_set = QtCore.pyqtSignal(object)  # StoredSet
    quit = QtCore.pyqtSignal()

    def __init__(self, cfg: Config, source: CaptureSource, store: SetStore, backend: str, widget_cls):
        super().__init__()
        self.setStyleSheet(f"background: {BG}; color: #ddd;")
        self.store = store
        self._latest: StoredSet | None = None

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
        root.addWidget(self._build_sidebar(backend))

        self.menu = MenuPanel(self, cfg.ui.exit_hold_ms)
        self.menu.library.connect(self.open_library.emit)
        self.menu.settings.connect(self.open_settings.emit)
        self.menu.quit.connect(self.quit.emit)

        self.meter = FrameRateMeter()
        self.meter.attach(picam2)
        self._fps_timer = QtCore.QTimer(self)
        self._fps_timer.timeout.connect(lambda: self.fps_label.setText(f"{self.meter.sample():.0f} fps"))
        self._fps_timer.start(1000)

        self.refresh_thumb()

    def _build_sidebar(self, backend: str) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget()
        bar.setFixedWidth(SIDEBAR_WIDTH)
        bar.setStyleSheet(f"background: {BAR_BG};")
        lay = QtWidgets.QVBoxLayout(bar)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        menu_btn = button("☰  Menu", height=44)
        menu_btn.setStyleSheet(BUTTON + "padding: 0;")
        menu_btn.clicked.connect(lambda: self.menu.open_menu())

        self.status = QtWidgets.QLabel("Ready")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.status.setStyleSheet("font-size: 13px;")

        self.shutter = QtWidgets.QPushButton()
        self.shutter.setFixedSize(SHUTTER_SIZE, SHUTTER_SIZE)
        self.shutter.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._style_shutter(ready=True)
        self.shutter.pressed.connect(self.controller.trigger)  # fire on touch-down: less lag

        self.thumb = ClickableLabel()
        self.thumb.setFixedSize(THUMB_SIZE)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background: #222; border-radius: 4px; color: #555; font-size: 11px;")
        self.thumb.clicked.connect(self._thumb_tapped)

        self.fps_label = QtWidgets.QLabel("-- fps")
        self.fps_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.fps_label.setStyleSheet("color: #666; font-size: 11px;")
        self.fps_label.setToolTip(f"{backend} preview, {qt_compat.BINDING}")

        lay.addWidget(menu_btn)
        lay.addWidget(self.status)
        lay.addStretch(1)
        lay.addWidget(self.shutter, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)
        lay.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.fps_label)
        return bar

    # -- actions ---------------------------------------------------------------
    def trigger_shortcut(self) -> None:
        """Keyboard shutter (Space): only when the camera screen is really in front."""
        if self.isVisible() and not self.menu.isVisible():
            self.controller.trigger()

    def _thumb_tapped(self) -> None:
        if self._latest is not None and self._latest.path.exists():
            self.open_set.emit(self._latest)

    def refresh_thumb(self) -> None:
        """Re-read the newest set from disk (it may have been deleted in the library)."""
        self._show_thumb(self.store.latest())

    def shutdown(self) -> None:
        self.status.setText("Finishing…")
        QtWidgets.QApplication.processEvents()
        self.controller.shutdown()  # waits for the running capture and pending saves

    # -- display ---------------------------------------------------------------
    def _style_shutter(self, ready: bool) -> None:
        r = SHUTTER_SIZE // 2
        fill = "#f2f2f2" if ready else "#777"
        self.shutter.setStyleSheet(
            f"QPushButton {{ background: {fill}; border: 4px solid #555; border-radius: {r}px; }}"
            f"QPushButton:pressed {{ background: #bbb; }}"
        )

    def _show_thumb(self, stored: StoredSet | None) -> None:
        self._latest = stored
        if stored is None or not stored.thumb_path.exists():
            self.thumb.clear()
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
            self.status.setText("<span style='color:#ff6b6b'>Error</span>")
            self.status.setToolTip(str(ev.detail))
            print(f"[jigglecam] {ev.detail}")

"""Main window: one screen at a time in a stack.

    Camera  --(☰ Menu)-->  slide-over panel  --> Library / Settings / exit
    Camera  --(tap thumbnail)-->  Viewer (latest shot)
    Library --(tap a shot)-->  Viewer  --(Back or Delete)-->  Library

The camera keeps streaming while another screen is in front, so going back
to the viewfinder is instant and the controller can finish saving a shot in
the background. Screens talk to each other only through signals wired here.
"""

from __future__ import annotations

from jigglecam.capture import CaptureSource, make_source
from jigglecam.config import Config
from jigglecam.storage import SetStore, StoredSet
from jigglecam.ui import qt_compat
from jigglecam.ui.camera import CameraScreen
from jigglecam.ui.library import LibraryScreen, SetViewer
from jigglecam.ui.qt_compat import QShortcut, Qt, QtCore, QtGui, QtWidgets
from jigglecam.ui.settings import SettingsScreen, gather_info


class MainWindow(QtWidgets.QStackedWidget):
    def __init__(self, cfg: Config, source: CaptureSource, store: SetStore, backend: str, widget_cls):
        super().__init__()
        self.setWindowTitle("JiggleCam")
        self.store = store
        self.camera = CameraScreen(cfg, source, store, backend, widget_cls)
        self.library = LibraryScreen(store)
        self.viewer = SetViewer(store, cfg.ui.playback_frame_ms)

        def info():
            app = QtWidgets.QApplication.instance()
            g = app.primaryScreen().geometry()
            return gather_info(cfg, source, store, backend, app.platformName(), f"{g.width()}x{g.height()}")

        self.settings = SettingsScreen(info)
        for w in (self.camera, self.library, self.viewer, self.settings):
            self.addWidget(w)
        self._viewer_return: QtWidgets.QWidget = self.library

        self.camera.open_library.connect(self.show_library)
        self.camera.open_settings.connect(self.show_settings)
        self.camera.open_set.connect(lambda s: self.show_viewer(s, return_to=self.camera))
        self.camera.quit.connect(self.close)
        self.library.back.connect(self.show_camera)
        self.library.open_set.connect(lambda s: self.show_viewer(s, return_to=self.library))
        self.viewer.back.connect(self._leave_viewer)
        self.viewer.deleted.connect(self._after_delete)
        self.settings.back.connect(self.show_camera)

        QShortcut(QtGui.QKeySequence("Esc"), self, activated=self.close)
        QShortcut(QtGui.QKeySequence("Space"), self, activated=self.camera.trigger_shortcut)

    def show_camera(self) -> None:
        self.camera.refresh_thumb()
        self.setCurrentWidget(self.camera)

    def show_library(self) -> None:
        self.library.refresh()
        self.setCurrentWidget(self.library)

    def show_settings(self) -> None:
        self.settings.refresh()
        self.setCurrentWidget(self.settings)

    def show_viewer(self, stored: StoredSet, return_to: QtWidgets.QWidget) -> None:
        self._viewer_return = return_to
        self.setCurrentWidget(self.viewer)
        self.viewer.show_set(stored)

    def _leave_viewer(self) -> None:
        self.show_camera() if self._viewer_return is self.camera else self.show_library()

    def _after_delete(self) -> None:
        self.camera.refresh_thumb()
        self._leave_viewer()

    def closeEvent(self, event) -> None:
        self.viewer.shutdown()
        self.camera.shutdown()
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
        win = MainWindow(cfg, source, store, backend, widget_cls)  # widget must exist before start()
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

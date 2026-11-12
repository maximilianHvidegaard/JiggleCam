#!/usr/bin/env python3
"""Phase 1 hardware check: display + touchscreen + Qt binding.

Run on the Pi (works straight from an SSH session on Pi OS Lite; Qt draws
to the screen via eglfs):
    python scripts/check_touch.py

Shows a fullscreen page with a crosshair near each corner. Tap each one:
  - your tap is drawn as a dot with its offset from the nearest target;
    big offsets / mirrored positions mean the touch input is rotated or
    scaled differently from the display (common with DSI panels).
  - "touch" vs "mouse" tells you whether Qt gets real multi-touch events
    or only emulated mouse clicks.
The header reports which Qt binding picamera2 uses (PyQt5 vs PyQt6), the
Qt platform plugin, and screen geometry.

Exit: hold the button for 1 s, or press Esc.
Also works on a desktop PC (without picamera2) for layout testing.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jigglecam import config as _config  # noqa: E402
from jigglecam.platform_env import configure_qt_platform  # noqa: E402

# Same display setup as the app (eglfs on Pi OS Lite); must precede Qt imports.
_QT_ENV = configure_qt_platform(_config.load().display)

from jigglecam.ui import qt_compat  # noqa: E402
from jigglecam.ui.app import HoldButton  # noqa: E402
from jigglecam.ui.qt_compat import QShortcut, Qt, QtCore, QtGui, QtWidgets  # noqa: E402

MARGIN = 60


def _touch_points(event):
    if hasattr(event, "points"):  # Qt6
        return [p.position() for p in event.points()]
    return [p.pos() for p in event.touchPoints()]  # Qt5


class TouchCanvas(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.dots: list[tuple[QtCore.QPointF, str]] = []
        self.last = "tap the crosshairs"
        self.max_fingers = 0

    def targets(self) -> list[QtCore.QPointF]:
        w, h = self.width(), self.height()
        return [QtCore.QPointF(x, y) for x, y in
                ((MARGIN, MARGIN), (w - MARGIN, MARGIN), (MARGIN, h - MARGIN), (w - MARGIN, h - MARGIN))]

    def _record(self, pos: QtCore.QPointF, source: str, fingers: int = 1) -> None:
        self.max_fingers = max(self.max_fingers, fingers)
        nearest = min(self.targets(), key=lambda t: math.dist((t.x(), t.y()), (pos.x(), pos.y())))
        dist = math.dist((nearest.x(), nearest.y()), (pos.x(), pos.y()))
        self.dots = (self.dots + [(QtCore.QPointF(pos), source)])[-40:]
        self.last = (f"{source}: ({pos.x():.0f}, {pos.y():.0f})  "
                     f"{dist:.0f}px from nearest target  | max fingers seen: {self.max_fingers}")
        self.update()

    def event(self, ev):
        t = ev.type()
        if t in (QtCore.QEvent.Type.TouchBegin, QtCore.QEvent.Type.TouchUpdate, QtCore.QEvent.Type.TouchEnd):
            pts = _touch_points(ev)
            if t == QtCore.QEvent.Type.TouchBegin and pts:
                for p in pts:
                    self._record(p, "touch", len(pts))
            elif pts:
                self.max_fingers = max(self.max_fingers, len(pts))
            ev.accept()
            return True
        return super().event(ev)

    def mousePressEvent(self, ev):
        pos = ev.position() if hasattr(ev, "position") else QtCore.QPointF(ev.pos())
        self._record(pos, "mouse")

    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#141414"))
        pen = QtGui.QPen(QtGui.QColor("#4caf50"), 2)
        p.setPen(pen)
        for t in self.targets():
            p.drawLine(QtCore.QPointF(t.x() - 25, t.y()), QtCore.QPointF(t.x() + 25, t.y()))
            p.drawLine(QtCore.QPointF(t.x(), t.y() - 25), QtCore.QPointF(t.x(), t.y() + 25))
            p.drawEllipse(t, 12, 12)
        for pos, source in self.dots:
            p.setBrush(QtGui.QColor("#ff5252" if source == "touch" else "#448aff"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(pos, 8, 8)
        p.setPen(QtGui.QColor("#ddd"))
        p.drawText(self.rect().adjusted(0, 0, 0, -MARGIN - 40),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, self.last)
        p.end()


class Window(QtWidgets.QWidget):
    def __init__(self, app):
        super().__init__()
        self.setStyleSheet("background: #141414; color: #ddd;")
        screen = app.primaryScreen()
        g = screen.geometry()
        info = QtWidgets.QLabel(
            f"Qt: {qt_compat.summary()}\n"
            f"platform plugin: {app.platformName()}   screen: {g.width()}x{g.height()} "
            f"@ {screen.devicePixelRatio():g}x DPR, {screen.physicalDotsPerInch():.0f} dpi, "
            f"{screen.refreshRate():.0f} Hz"
        )
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        exit_btn = HoldButton("hold to exit", 1000)
        exit_btn.setMinimumSize(160, 56)
        exit_btn.setStyleSheet("background: #333; border-radius: 8px;")
        exit_btn.held.connect(self.close)
        top = QtWidgets.QHBoxLayout()
        top.addStretch(1)
        top.addWidget(info)
        top.addStretch(1)
        top.addWidget(exit_btn)
        top.setContentsMargins(MARGIN * 2, 8, MARGIN * 2, 0)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top)
        lay.addWidget(TouchCanvas(), 1)
        QShortcut(QtGui.QKeySequence("Esc"), self, activated=self.close)
        print(f"[check_touch] {qt_compat.summary()} | platform={app.platformName()} | "
              f"screen={g.width()}x{g.height()} | qt env set: {_QT_ENV or 'none'}")


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    win = Window(app)
    if "--windowed" in sys.argv:
        win.resize(1024, 600)
        win.show()
    else:
        win.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

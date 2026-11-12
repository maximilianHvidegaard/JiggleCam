"""Small touch-friendly widgets shared by all screens.

Everything here is sized for an 800x480 touchscreen: buttons are at least
44 px tall, text at least 13 px.
"""

from __future__ import annotations

from jigglecam.ui.qt_compat import Qt, QtCore, QtGui, QtWidgets

BG = "#141414"
BAR_BG = "#0c0c0c"
BUTTON = "background: #262626; border-radius: 6px; color: #ddd; font-size: 15px; padding: 0 14px;"
DANGER = "background: #5a1d1d; border-radius: 6px; color: #fff; font-size: 15px; padding: 0 14px;"
TOP_BAR_HEIGHT = 52


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


class ClickableLabel(QtWidgets.QLabel):
    clicked = QtCore.pyqtSignal()

    def mouseReleaseEvent(self, event) -> None:  # touch arrives as synthesized mouse events
        if self.rect().contains(event.position().toPoint() if hasattr(event, "position") else event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Shade(QtWidgets.QWidget):
    """A translucent dark cover. Painted by hand so it works on any widget subclass."""

    clicked = QtCore.pyqtSignal()

    def __init__(self, alpha: int = 150, parent=None):
        super().__init__(parent)
        self._color = QtGui.QColor(0, 0, 0, alpha)

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), self._color)
        p.end()

    def mousePressEvent(self, _event) -> None:
        self.clicked.emit()


def button(text: str, style: str = BUTTON, height: int = 44) -> QtWidgets.QPushButton:
    b = QtWidgets.QPushButton(text)
    b.setFixedHeight(height)
    b.setStyleSheet(style)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


def top_bar(back_text: str, title: str) -> tuple[QtWidgets.QWidget, QtWidgets.QPushButton,
                                                   QtWidgets.QLabel, QtWidgets.QHBoxLayout]:
    """A bar with a back button on the left and a title; callers add buttons on the right."""
    bar = QtWidgets.QWidget()
    bar.setFixedHeight(TOP_BAR_HEIGHT)
    bar.setStyleSheet(f"background: {BAR_BG};")
    lay = QtWidgets.QHBoxLayout(bar)
    lay.setContentsMargins(6, 4, 6, 4)
    back = button(back_text)
    label = QtWidgets.QLabel(title)
    label.setStyleSheet("font-size: 16px; color: #ddd; padding-left: 8px;")
    lay.addWidget(back)
    lay.addWidget(label, 1)
    return bar, back, label, lay


def enable_touch_scroll(area: QtWidgets.QAbstractScrollArea) -> None:
    """Drag-to-scroll with momentum, like a phone. Taps still reach the buttons inside."""
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroller = QtWidgets.QScroller
    gesture = getattr(getattr(scroller, "ScrollerGestureType", scroller), "LeftMouseButtonGesture")
    scroller.grabGesture(area.viewport(), gesture)


class ConfirmOverlay(QtWidgets.QWidget):
    """Full-screen "are you sure?" with big buttons (QMessageBox is tiny on a touchscreen)."""

    confirmed = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget):
        super().__init__(parent)
        self.hide()
        shade = Shade(190, self)
        shade.clicked.connect(self.hide)
        self._shade = shade

        self.box = QtWidgets.QFrame(self)
        self.box.setStyleSheet("QFrame { background: #222; border-radius: 10px; }")
        lay = QtWidgets.QVBoxLayout(self.box)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(16)
        self.text = QtWidgets.QLabel()
        self.text.setWordWrap(True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setStyleSheet("font-size: 16px; color: #eee; background: transparent;")
        row = QtWidgets.QHBoxLayout()
        self.cancel = button("Cancel", height=52)
        self.ok = button("Delete", DANGER, height=52)
        self.cancel.clicked.connect(self.hide)
        self.ok.clicked.connect(self._accept)
        row.addWidget(self.cancel)
        row.addWidget(self.ok)
        lay.addWidget(self.text)
        lay.addLayout(row)

    def ask(self, text: str, ok_text: str = "Delete") -> None:
        self.text.setText(text)
        self.ok.setText(ok_text)
        parent = self.parentWidget()
        self.setGeometry(parent.rect())
        self._shade.setGeometry(self.rect())
        w = min(420, self.width() - 40)
        self.box.setFixedWidth(w)
        self.box.adjustSize()
        self.box.move((self.width() - w) // 2, (self.height() - self.box.height()) // 2)
        self.raise_()
        self.show()

    def _accept(self) -> None:
        self.hide()
        self.confirmed.emit()

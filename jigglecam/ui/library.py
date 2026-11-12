"""Library: a thumbnail grid of capture sets, and a viewer that plays one set.

    Grid (newest first)                      Viewer
    +-------------------------------------+  +-------------------------------------+
    | [‹ Camera]  Library (12)            |  | [‹ Back] 2026-11-12 15:23  [Delete] |
    | [thumb] [thumb] [thumb] [thumb]     |  |                                     |
    | [thumb] [thumb] [thumb] [thumb]     |  |      frames 1-2-3-4-3-2, looping    |
    |   ... drag to scroll ...            |  |      (tap the picture: pause/play)  |
    +-------------------------------------+  | [Pause] [◀] 2/4 [▶]    100 ms · ⚠    |
                                             +-------------------------------------+

The viewer plays the *raw, unaligned* frames. Alignment on a chosen subject
and GIF/MP4 export are phase 3. Frames are decoded on a worker thread
(see frames.py), so opening a set never freezes the screen.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from jigglecam.storage import SetStore, StoredSet
from jigglecam.ui.frames import DecodedFrame, decode_for_screen, wiggle_order
from jigglecam.ui.qt_compat import Qt, QtCore, QtGui, QtWidgets
from jigglecam.ui.widgets import BAR_BG, BG, DANGER, ConfirmOverlay, button, enable_touch_scroll, top_bar

GRID_COLUMNS = 4
GRID_ICON = QtCore.QSize(176, 99)
DECODE_SIZE = (800, 450)


def set_label(stored: StoredSet) -> str:
    try:
        return datetime.fromisoformat(stored.meta["captured_at"]).strftime("%d %b  %H:%M:%S")
    except (KeyError, ValueError):
        return stored.name


class LibraryScreen(QtWidgets.QWidget):
    back = QtCore.pyqtSignal()
    open_set = QtCore.pyqtSignal(object)  # StoredSet

    def __init__(self, store: SetStore):
        super().__init__()
        self.store = store
        self.setStyleSheet(f"background: {BG}; color: #ddd;")
        self._shown: list[str] = []
        self._pixmaps: dict[str, QtGui.QPixmap] = {}

        bar, back_btn, self.title, _ = top_bar("‹  Camera", "Library")
        back_btn.clicked.connect(self.back.emit)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; }")
        enable_touch_scroll(self.scroll)

        self.empty = QtWidgets.QLabel("No shots yet.\nGo back and press the shutter.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet("color: #777; font-size: 16px;")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(bar)
        lay.addWidget(self.scroll, 1)
        lay.addWidget(self.empty, 1)

    def refresh(self) -> None:
        """Rebuild the grid if the sets on disk changed since last time."""
        sets = self.store.list()
        names = [s.name for s in sets]
        self.title.setText(f"Library ({len(sets)})")
        self.empty.setVisible(not sets)
        self.scroll.setVisible(bool(sets))
        if names == self._shown:
            return
        self._shown = names
        self._pixmaps = {k: v for k, v in self._pixmaps.items() if k in names}

        grid_host = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(grid_host)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setSpacing(10)
        for i, stored in enumerate(sets):
            grid.addWidget(self._tile(stored), i // GRID_COLUMNS, i % GRID_COLUMNS)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(grid_host)  # deletes the previous grid

    def _tile(self, stored: StoredSet) -> QtWidgets.QToolButton:
        pix = self._pixmaps.get(stored.name)
        if pix is None:
            pix = QtGui.QPixmap(str(stored.thumb_path))
            if not pix.isNull():
                pix = pix.scaled(GRID_ICON, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            self._pixmaps[stored.name] = pix
        tile = QtWidgets.QToolButton()
        tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tile.setIcon(QtGui.QIcon(pix))
        tile.setIconSize(GRID_ICON)
        warn = "" if stored.meta.get("lock_verified", True) else "  ⚠"
        tile.setText(set_label(stored) + warn)
        tile.setStyleSheet("QToolButton { background: #1e1e1e; border-radius: 6px; padding: 4px;"
                           " color: #bbb; font-size: 12px; }")
        tile.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tile.clicked.connect(lambda _=False, s=stored: self.open_set.emit(s))
        return tile


class _Loaded(QtCore.QObject):
    done = QtCore.pyqtSignal(int, object)  # token, list[DecodedFrame] | Exception


class FrameView(QtWidgets.QWidget):
    """Draws the current frame scaled to fit. Tapping it emits `tapped`."""

    tapped = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self._frames: list[QtGui.QPixmap] = []
        self._scaled: list[QtGui.QPixmap] = []
        self._index = 0
        self.message = ""

    def set_frames(self, frames: list[QtGui.QPixmap]) -> None:
        self._frames = frames
        self._rescale()

    def show_index(self, i: int) -> None:
        self._index = i
        self.update()

    def _rescale(self) -> None:
        # Scale once per size change, not on every frame of the loop.
        self._scaled = [f.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation) for f in self._frames]
        self.update()

    def resizeEvent(self, event) -> None:
        self._rescale()
        super().resizeEvent(event)

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#000"))
        if self._scaled and 0 <= self._index < len(self._scaled):
            pix = self._scaled[self._index]
            p.drawPixmap((self.width() - pix.width()) // 2, (self.height() - pix.height()) // 2, pix)
        elif self.message:
            p.setPen(QtGui.QColor("#888"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
        p.end()

    def mousePressEvent(self, _event) -> None:
        self.tapped.emit()


class SetViewer(QtWidgets.QWidget):
    back = QtCore.pyqtSignal()
    deleted = QtCore.pyqtSignal()

    def __init__(self, store: SetStore, frame_ms: int):
        super().__init__()
        self.store = store
        self.stored: StoredSet | None = None
        self.setStyleSheet(f"background: {BG}; color: #ddd;")
        self._order: list[int] = []
        self._step = 0
        self._token = 0
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="decode")
        self._loaded = _Loaded()
        self._loaded.done.connect(self._on_loaded)

        bar, back_btn, self.title, bar_lay = top_bar("‹  Back", "")
        back_btn.clicked.connect(self.back.emit)
        delete_btn = button("Delete", DANGER)
        delete_btn.clicked.connect(self._ask_delete)
        bar_lay.addWidget(delete_btn)

        self.view = FrameView()
        self.view.tapped.connect(self.toggle_play)

        controls = QtWidgets.QWidget()
        controls.setFixedHeight(56)
        controls.setStyleSheet(f"background: {BAR_BG};")
        c = QtWidgets.QHBoxLayout(controls)
        c.setContentsMargins(6, 4, 10, 4)
        self.play_btn = button("Pause")
        self.play_btn.setFixedWidth(80)
        self.prev_btn = button("◀")
        self.next_btn = button("▶")
        for b in (self.prev_btn, self.next_btn):
            b.setFixedWidth(64)
        self.pos_label = QtWidgets.QLabel()
        self.pos_label.setFixedWidth(80)
        self.pos_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pos_label.setStyleSheet("font-size: 15px;")
        self.info = QtWidgets.QLabel()
        self.info.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.info.setStyleSheet("color: #888; font-size: 13px;")
        self.play_btn.clicked.connect(self.toggle_play)
        self.prev_btn.clicked.connect(lambda: self._step_view(-1))
        self.next_btn.clicked.connect(lambda: self._step_view(+1))
        c.addWidget(self.play_btn)
        c.addSpacing(12)
        c.addWidget(self.prev_btn)
        c.addWidget(self.pos_label)
        c.addWidget(self.next_btn)
        c.addWidget(self.info, 1)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(bar)
        lay.addWidget(self.view, 1)
        lay.addWidget(controls)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(frame_ms)
        self.timer.timeout.connect(self._tick)
        self.confirm = ConfirmOverlay(self)
        self.confirm.confirmed.connect(self._delete)

    # -- loading -----------------------------------------------------------------
    def show_set(self, stored: StoredSet) -> None:
        self.stored = stored
        self._token += 1
        self.timer.stop()
        self.view.set_frames([])
        self.view.message = "Loading…"
        self.title.setText(set_label(stored))
        views = len(stored.frame_paths)
        self._order = wiggle_order(views)
        self._step = 0
        bits = [f"{stored.meta.get('spread_ms', 0):.0f} ms"]
        if not stored.meta.get("lock_verified", True):
            bits.append("⚠ lock unverified")
        self.info.setText("  ·  ".join(bits))
        self._update_controls(playing=False)
        token, paths = self._token, stored.frame_paths
        self._pool.submit(self._decode, token, paths)

    def _decode(self, token: int, paths) -> None:
        """Worker thread: no Qt widgets here, only plain bytes go back."""
        try:
            result: object = [decode_for_screen(p, *DECODE_SIZE) for p in paths]
        except Exception as exc:  # missing/corrupt file: show it, don't crash
            result = exc
        self._loaded.done.emit(token, result)

    def _on_loaded(self, token: int, result) -> None:
        if token != self._token:
            return  # the user already moved on to another set
        if isinstance(result, Exception):
            self.view.message = f"Could not load frames:\n{result}"
            self.view.update()
            return
        pixmaps = []
        for f in result:  # type: DecodedFrame
            img = QtGui.QImage(f.rgb, f.width, f.height, f.width * 3, QtGui.QImage.Format.Format_RGB888)
            pixmaps.append(QtGui.QPixmap.fromImage(img.copy()))
        self.view.set_frames(pixmaps)
        self._show_step()
        if self.isVisible():
            self.play()

    # -- playback ----------------------------------------------------------------
    def play(self) -> None:
        if self._order:
            self.timer.start()
            self._update_controls(playing=True)

    def pause(self) -> None:
        self.timer.stop()
        self._update_controls(playing=False)

    def toggle_play(self) -> None:
        self.pause() if self.timer.isActive() else self.play()

    def _tick(self) -> None:
        self._step = (self._step + 1) % len(self._order)
        self._show_step()

    def _step_view(self, delta: int) -> None:
        """While paused: go to the previous/next *view* (1..4), not loop step."""
        views = len(self.stored.frame_paths) if self.stored else 0
        if not views:
            return
        current = self._order[self._step]
        target = (current + delta) % views
        self._step = self._order.index(target)
        self._show_step()

    def _show_step(self) -> None:
        if not self._order:
            return
        view = self._order[self._step]
        self.view.show_index(view)
        self.pos_label.setText(f"{view + 1} / {len(self.stored.frame_paths)}")

    def _update_controls(self, playing: bool) -> None:
        self.play_btn.setText("Pause" if playing else "Play")
        self.prev_btn.setEnabled(not playing)
        self.next_btn.setEnabled(not playing)

    def hideEvent(self, event) -> None:
        self.timer.stop()  # no point animating an invisible screen
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.confirm.hide()

    # -- delete ------------------------------------------------------------------
    def _ask_delete(self) -> None:
        if self.stored is None:
            return
        self.pause()
        self.confirm.ask(f"Delete the shot from {set_label(self.stored)}?\n"
                         "All 4 frames are removed for good.")

    def _delete(self) -> None:
        stored, self.stored = self.stored, None
        if stored is None:
            return
        try:
            self.store.delete(stored)
        except OSError as exc:
            self.info.setText(f"<span style='color:#ff6b6b'>Delete failed: {exc}</span>")
            self.stored = stored
            return
        self.deleted.emit()

    def shutdown(self) -> None:
        self._token += 1
        self._pool.shutdown(wait=False, cancel_futures=True)
